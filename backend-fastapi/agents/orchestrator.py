"""Router agent: classifies intent + sentiment in one Anthropic tool call,
then dispatches to the matching specialist agent, falling back to
general_agent for anything unclassified or when a specialist can't produce
a reply (no API key, tool-call error, etc).

Accepts an optional on_stage(stage, detail=None) callback (see
agents/base.py's docstring) used to report progress during a voice turn.
"""

import asyncio
from typing import Optional

import config
from agents import complaints_agent, general_agent, schedule_agent, support_agent, tracking_agent

CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"

CLASSIFY_TOOL = {
    "name": "classify",
    "description": "Classify the user's EcoTrack message by which specialist should handle it, and the emotional tone of the message.",
    "input_schema": {
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "enum": ["tracking", "complaints", "schedule", "support", "general"],
                "description": "tracking = truck location/ETA questions. complaints = filing or checking complaint status. schedule = the user's OWN pickup schedule/waste type. support = contact details/hours. general = anything else (schedule format options, waste types in general, account help, greetings, off-topic).",
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

_NEGATIVE_WORDS = {"angry", "furious", "terrible", "worst", "awful", "disgusting", "never", "useless", "broken"}
_POSITIVE_WORDS = {"thanks", "thank", "great", "awesome", "good", "love", "perfect", "excellent"}


def _keyword_classify(message: str) -> dict:
    lower = message.lower()
    if any(k in lower for k in ("track", "truck", "vehicle", "eta", "where")):
        agent = "tracking"
    elif any(k in lower for k in ("complaint", "complain", "report", "issue")):
        agent = "complaints"
    elif any(k in lower for k in ("schedule", "pickup", "daily", "alternate", "weekly", "frequency")):
        agent = "schedule"
    elif any(k in lower for k in ("support", "contact", "phone", "email", "whatsapp", "helpline")):
        agent = "support"
    else:
        agent = "general"

    if any(w in lower for w in _NEGATIVE_WORDS):
        sentiment = "negative"
    elif any(w in lower for w in _POSITIVE_WORDS):
        sentiment = "positive"
    else:
        sentiment = "neutral"
    return {"agent": agent, "sentiment": sentiment}


def _classify_sync(message: str, history: list) -> dict:
    from anthropic import Anthropic

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    messages = [{"role": h["role"], "content": h["content"]} for h in history[-6:]]
    messages.append({"role": "user", "content": message})
    resp = client.messages.create(
        model=CLASSIFIER_MODEL, max_tokens=100,
        tools=[CLASSIFY_TOOL], tool_choice={"type": "tool", "name": "classify"},
        messages=messages,
    )
    block = next(b for b in resp.content if b.type == "tool_use")
    return {"agent": block.input["agent"], "sentiment": block.input["sentiment"]}


async def classify(message: str, history: list) -> dict:
    if config.ANTHROPIC_API_KEY in config.PLACEHOLDER_VALUES:
        return _keyword_classify(message)
    try:
        return await asyncio.to_thread(_classify_sync, message, history)
    except Exception as err:
        print(f"classification error, falling back to keywords: {err}")
        return _keyword_classify(message)


async def route_and_reply(message: str, history: list, current_user: Optional[dict], on_stage=None) -> dict:
    if on_stage:
        on_stage("thinking", None)

    classification = await classify(message, history)
    agent_name, sentiment = classification["agent"], classification["sentiment"]

    reply, source = None, "ai"
    if agent_name in _SPECIALISTS:
        reply = await _SPECIALISTS[agent_name].handle(message, history, sentiment, current_user, on_stage=on_stage)

    if reply is None:
        # Covers: agent_name == "general", or a specialist genuinely failed
        # (no key / tool error) rather than declined — either way, log the
        # honest outcome as "general" so analytics never mislabels a failure.
        result = await general_agent.handle(message, history, sentiment, current_user, on_stage=on_stage)
        reply, source, agent_name = result["reply"], result["source"], "general"

    return {"reply": reply, "source": source, "agent": agent_name, "sentiment": sentiment}
