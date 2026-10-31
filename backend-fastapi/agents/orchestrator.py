"""Router agent: classifies intent + sentiment in one structured Ollama call, then dispatches to the matching specialist agent, falling back to
general_agent for anything unclassified or when a specialist can't produce
a reply (no API key, tool-call error, etc).

Accepts an optional on_stage(stage, detail=None) callback (see
agents/base.py's docstring) used to report progress during a voice turn.
"""

import asyncio
import logging
import re
from typing import Optional

import config
from services import metrics, ollama_client
from agents.base import PROMISE_REPLACEMENT
from services import complaint_drafts
from agents import roles, complaints_agent, general_agent, schedule_agent, support_agent, tracking_agent
log = logging.getLogger("shipora.agents")


_DID_YOU_MEAN = re.compile(r"Did you mean (SHP[0-9A-F]{8,10})\?")


def resolve_did_you_mean(message: str, history: list) -> str:
    """The assistant offered "Did you mean SHP…?" (a mis-heard number repaired against the caller's own shipments) and the caller said
    yes: the yes means "look that one up". Rewrites a bare confirmation into the lookup it stands for; anything else is unchanged."""
    said = roles.user_text(message)
    if complaint_drafts.classify_reply(said) != "confirm" or not history:
        return message
    last = next((h for h in reversed(history) if h.get("role") != "user"), None)
    m = _DID_YOU_MEAN.search((last or {}).get("content", ""))
    return f"Where is {m.group(1)}?" if m else message


def tracking_agent_extract(text: str):
    from tools.shipment_tools import extract_tracking_number
    return extract_tracking_number(text)

CLASSIFY_TOOL = {
    "name": "classify",
    "description": "Classify the user's Shipora message by which specialist should handle it, and the emotional tone of the message.",
    "input_schema": {
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "enum": ["tracking", "complaints", "schedule", "support", "general"],
                "description": "tracking = where a parcel/shipment is (by tracking number), delivery-vehicle location/ETA/GPS questions, delivery agent lookups, historical delivery logs. complaints = filing a delivery issue/complaint, checking a customer's OWN issue status, OR any issue-specific counts/stats/listing across all customers (e.g. 'how many delivery issues are pending', 'show damaged-parcel issues', 'delayed deliveries this week') — anything about complaints/issues specifically, even in aggregate. schedule = the user's OWN shipments' pickup time, status and estimated delivery date. support = contact details/hours. general = anything else (service type options, how to create a shipment, account help, greetings, off-topic, or a BROAD cross-domain summary like 'summarize today's operations' or 'what's today's performance' — NOT an issues-only stats question, which is 'complaints').",
            },
            "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
        },
        "required": ["agent", "sentiment"],
    },
}

_SPECIALISTS = {
    "tracking": tracking_agent,
    "complaints": complaints_agent,
    "schedule": schedule_agent,
    "support": support_agent,
}

_COMPLAINT_WORDS = re.compile(r"\b(complain\w*|damaged|lost|missing|broken|crushed|refund|rude|late|delayed|issue|problem|report)\b", re.I)
_ROUTE_RE = re.compile(r"\b(my route|my deliver\w*|what'?s next|next deliver\w*|(?:what|which) .{0,20}(?:pending|assigned))\b", re.I)
_MY_PARCEL_RE = re.compile(r"\bwhere(?:'s| is)?\s+(?:my|the)\s+(?:parcel|package|shipment|order)s?\b|\bmy\s+(?:parcel|package|shipment|order)s?\b", re.I)
# The support specialist only knows Shipora's contact details. A small classifier also sends it "can I cancel my shipment?" and
# "how much does delivery cost?", which it can only answer wrongly ("contact support").
_CONTACT_RE = re.compile(r"\b(phone|call|contact|e-?mail|whatsapp|helpline|customer care|care number|office|address|hours|reach (?:you|us|support)|talk to|speak to|support (?:team|number|line))\b", re.I)
_NEGATIVE_WORDS = {"angry", "furious", "terrible", "worst", "awful", "disgusting", "never", "useless", "broken"}
_POSITIVE_WORDS = {"thanks", "thank", "great", "awesome", "good", "love", "perfect", "excellent"}


# Zero-key router. Word-boundary matching (substring tests made "eta" fire inside "details" and "live" inside
# "delivery") and weighted scoring: specific intent words are strong signals; generic nouns (parcel, shipment,
# deliver) only tip a message that already has some other signal.
_STRONG, _WEAK = 1.0, 0.5
_KEYWORD_SIGNALS = {
    "tracking": {
        _STRONG: ("track", "tracking", "where", "eta", "vehicle", "driver", "agent", "rider", "live", "location", "gps", "shp\w*"),
        _WEAK: ("parcel", "package", "shipment", "order"),
    },
    "complaints": {
        2.0: ("complain\w*", "issues?", "damaged", "lost", "rude", "unacceptable", "refund", "broken", "missing", "reports?"),
    },
    "schedule": {
        _STRONG: ("schedule\w*", "pickup", "when will", "what time", "arrive\w*", "reach me"),
        _WEAK: ("deliver\w*",),
    },
    "support": {
        _STRONG: ("support", "contact", "phone", "email", "whatsapp", "helpline", "customer care", "call"),
    },
}
_KEYWORD_PATTERNS = {
    agent: [(weight, re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)) for weight, words in groups.items()]
    for agent, groups in _KEYWORD_SIGNALS.items()
}


def _keyword_scores(message: str) -> dict:
    lower = message.lower()
    return {agent: sum(weight * len(set(m.lower() for m in pattern.findall(lower))) for weight, pattern in patterns)
            for agent, patterns in _KEYWORD_PATTERNS.items()}


def keyword_is_decisive(message: str) -> bool:
    """True when the keyword router is confident enough to skip the LLM: a clear winner with at least two strong signals
    (e.g. 'where' + a tracking number) and a margin over the runner-up. Anything vaguer goes to the LLM."""
    ranked = sorted(_keyword_scores(message).values(), reverse=True)
    return ranked[0] >= 2 * _STRONG and ranked[0] - ranked[1] >= _STRONG


def _keyword_classify(message: str) -> dict:
    lower = message.lower()
    scores = _keyword_scores(message)
    agent, best = max(scores.items(), key=lambda kv: kv[1])
    if best < _STRONG:  # only weak signals ("how do I create a shipment") -> general knowledge, not a data lookup
        agent = "general"

    if any(w in lower for w in _NEGATIVE_WORDS):
        sentiment = "negative"
    elif any(w in lower for w in _POSITIVE_WORDS):
        sentiment = "positive"
    else:
        sentiment = "neutral"
    return {"agent": agent, "sentiment": sentiment}


async def classify(message: str, history: list) -> dict:
    with metrics.timed("classify_ms"):
        return await _classify(message, history)


async def _classify(message: str, history: list) -> dict:
    # CLASSIFIER_MODE=hybrid: the keyword router answers instantly when it is decisive; the LLM only sees ambiguous messages.
    if config.CLASSIFIER_MODE == "hybrid" and keyword_is_decisive(message):
        return _keyword_classify(message)
    if ollama_client.is_unavailable():
        return _keyword_classify(message)
    try:
        return await ollama_client.classify(message, history, CLASSIFY_TOOL)
    except Exception as err:
        log.warning("intent classification failed; using keywords", extra={"event": "classify_failed", "provider": "ollama",
                                                                           "error_type": type(err).__name__, "error": str(err)[:200]})
        return _keyword_classify(message)


async def route_and_reply(message: str, history: list, current_user: Optional[dict], on_stage=None, session_id: Optional[str] = None,
                          channel: str = "text") -> dict:
    if on_stage:
        on_stage("thinking", None)

    message = resolve_did_you_mean(message, history)
    blocked = roles.intent_denial(current_user, message)
    if blocked:
        return {"reply": blocked, "source": "builtin", "agent": "general", "sentiment": "neutral"}

    classification = await classify(message, history)
    agent_name, sentiment = classification["agent"], classification["sentiment"]
    said = roles.user_text(message)
    if roles.role_of(current_user) == roles.USER and await complaint_drafts.awaiting(current_user, session_id) \
            and (complaint_drafts.classify_reply(said) != "other" or len(said.split()) <= 3):
        agent_name = "complaints"        # a customer answering the confirmation question is never re-routed by a classifier
    elif agent_name in ("complaints", "general", "schedule") and tracking_agent_extract(said) and not _COMPLAINT_WORDS.search(said):
        agent_name = "tracking"          # "where is SHP…" is a shipment lookup, whatever a small model says
    elif agent_name == "general" and roles.role_of(current_user) == roles.DRIVER and _ROUTE_RE.search(said):
        agent_name = "tracking"          # a rider's route question: the tracking specialist has their assignments (and a database fallback)
    elif agent_name == "general" and roles.role_of(current_user) == roles.USER and _MY_PARCEL_RE.search(said) and not _COMPLAINT_WORDS.search(said) \
            and not tracking_agent.is_howto(said):       # "Can I cancel my shipment?" is a policy question, not a lookup
        agent_name = "tracking"
    if agent_name == "support" and not _CONTACT_RE.search(said):
        agent_name = "general"           # not a contact question: the general agent has the knowledge base
    agent_name, denial = roles.route_for(current_user, agent_name)   # each role only reaches the specialists meant for it
    if denial:
        return {"reply": denial, "source": "builtin", "agent": "general", "sentiment": sentiment}

    reply, source = None, "ai"
    if agent_name == "tracking":
        reply = await tracking_agent.direct(said, current_user)      # e.g. a rider's route: the exact rows, no model needed
        if reply is not None:
            return {"reply": reply, "source": "builtin", "agent": "tracking", "sentiment": sentiment}
    meta = {}
    if agent_name in _SPECIALISTS:
        extra = {"session_id": session_id, "channel": channel, "meta": meta} if agent_name == "complaints" else {"meta": meta} if agent_name in ("tracking", "support") else {}
        reply = await _SPECIALISTS[agent_name].handle(message, history, sentiment, current_user, on_stage=on_stage, **extra)
        source = meta.get("source", source)

    if reply == PROMISE_REPLACEMENT and agent_name == "tracking":
        reply = None                    # the model only promised a lookup: answer from the database instead
    if reply is None and agent_name == "tracking":
        reply = await tracking_agent.fallback(message, current_user)   # LLM down: still answer from the database
        if reply is not None:
            source = "builtin"

    if reply is None:
        # Covers: agent_name == "general", or a specialist genuinely failed
        # (no key / tool error) rather than declined — either way, log the
        # honest outcome as "general" so analytics never mislabels a failure.
        result = await general_agent.handle(message, history, sentiment, current_user, on_stage=on_stage)
        reply, source, agent_name = result["reply"], result["source"], "general"

    return {"reply": reply, "source": source, "agent": agent_name, "sentiment": sentiment}
