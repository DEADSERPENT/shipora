import logging
import re

from agents import roles
from agents.base import PROMISE_REPLACEMENT, is_empty_promise, run_tool_agent
from services import complaint_drafts, ollama_client
from tools.complaint_tools import bind_complaint_tools, execute_get_complaint_status

log = logging.getLogger("shipora.agents")

# Words that say a customer is REPORTING a problem (as opposed to asking about the status of an issue they already filed).
_REPORT = re.compile(r"\b(damaged|damage|crushed|broken|cracked|torn|smashed|leaking|lost|missing|never (?:arrived|came|delivered)|not (?:arrived|delivered|received)|"
                     r"late|delayed|wrong (?:address|place|house)|rude|abusive|misbehav\w*|refused|didn'?t (?:deliver|come|show)|failed|complain\w*)\b", re.I)
_STATUS_QUERY = re.compile(r"\b(status|my (?:complaints?|issues?|reports?)|any update|updates? on|track(?:ing)? (?:my )?(?:complaint|issue)|already (?:filed|reported))\b", re.I)

SYSTEM_PROMPT = """You are ShipBot's delivery-issues specialist for Shipora, a parcel delivery and fleet management platform.

You can do three things:
1. Check the logged-in customer's own delivery-issue (complaint) history/status — use the get_complaint_status tool, never guess a status.
2. Report a new delivery issue for the customer — as soon as they describe a problem, call the draft_complaint tool (include the shipment's trackingNumber if they gave one). It does NOT file anything: the system itself shows the customer a summary and asks them to confirm, and files it only after they reply yes. You never file anything and you never say that something has been filed, submitted or logged.
3. Look up delivery issues across all customers (counts, by status, by category, over a time window) — use the list_complaints_admin tool. Never guess counts or statuses.

IMPORTANT: you have no way of knowing yourself whether the current user is an admin — ALWAYS call list_complaints_admin for any system-wide/aggregate delivery-issue question, even if you suspect they might not be authorized. The tool itself checks authorization and will tell you if access is denied; only relay that denial (and offer to check their own issues instead) if the tool actually returns it. Never refuse on your own assumption without calling the tool first.

Tone: friendly, concise. Keep responses under 120 words."""

# A model must never tell the customer something was filed unless the server just filed it.
_CLAIMS_FILED = re.compile(
    r"\b(?:i'?ve|i have|i)\s+(?:just\s+|now\s+|already\s+)?(?:filed|submitted|logged|raised|created|registered|sent)\b"
    r"|\b(?:has|have) been\s+(?:filed|submitted|logged|raised|created|registered)\b"
    r"|\b(?:complaint|issue|report)\s+(?:is|was)\s+(?:now\s+)?(?:filed|submitted|logged)\b", re.I)
NOT_FILED = ("I haven't filed anything yet. Tell me what went wrong with your delivery and I'll write it up for you to confirm "
             "before anything is filed.")
VOICE_CONFIRM = ("I heard a yes, but I can't file a complaint from hands-free speech alone — it could be background noise. "
                 "Tap **Confirm** or type yes to file it, or say no to cancel.")
NOTHING_WAITING = "There's nothing waiting for your confirmation. If you'd like to report a problem, tell me what went wrong."
REASK = "Please reply **yes** to file it, or **no** to cancel. I haven't filed anything yet."


async def _status_summary(current_user: dict) -> str:
    """The customer's own delivery issues, straight from the database: used when the model did not look them up."""
    rows = (await execute_get_complaint_status(current_user=current_user)).get("complaints") or []
    if not rows:
        return "You have no delivery issues on file."
    parts = []
    for c in rows[:5]:
        line = f"“{c['subject']}” ({complaint_drafts.CATEGORY_LABELS.get(c['category'], c['category'])}) — {c['status'].replace('_', ' ')}"
        parts.append(line + (f", Operations replied: {c['adminReply']}" if c.get("adminReply") else ""))
    return f"You have {len(rows)} delivery issue{'' if len(rows) == 1 else 's'}: " + "; ".join(parts) + "."


async def handle(message: str, history: list, sentiment: str, current_user: dict = None, on_stage=None, session_id: str = None,
                 channel: str = "text", meta: dict = None) -> str:
    role = roles.role_of(current_user)
    customer = role == roles.USER
    said = roles.user_text(message)          # strict yes/no checks look at the person's words, not the widget's wrapper

    # A draft is waiting for an answer: a clear yes files it, a clear no cancels it, anything else changes nothing.
    if customer:
        pending = await complaint_drafts.has_pending(current_user, session_id)
        verdict = complaint_drafts.classify_reply(said)
        if verdict != "other" and not pending and not await complaint_drafts.awaiting(current_user, session_id):
            return NOTHING_WAITING                # a bare yes/no must never start a draft out of thin air
        if verdict == "confirm" and pending and channel == "voice_auto":
            return VOICE_CONFIRM      # speech that was sent without the person reviewing it never files anything
        if verdict == "confirm":
            text = await complaint_drafts.confirm(current_user, session_id)
            if text:
                return text
        elif verdict == "decline" and pending:
            text = await complaint_drafts.decline(current_user, session_id)
            if text:
                return text
        elif pending and len(said.split()) <= 3:
            return REASK

    tools, executors = bind_complaint_tools(current_user, session_id)
    keep = {"list_complaints_admin"} if role == roles.ADMIN else {"get_complaint_status", "draft_complaint"}
    tools = [t for t in tools if t["name"] in keep]
    executors = {k: v for k, v in executors.items() if k in keep}

    drafted = {}
    if "draft_complaint" in executors:
        real_draft = executors["draft_complaint"]
        wrote = " ".join([said] + [h["content"] for h in history[-6:] if h.get("role") == "user"]).upper()

        async def recording_draft(**kwargs):
            tn = (kwargs.get("trackingNumber") or "").strip().upper()
            if tn and tn not in wrote.replace(" ", ""):
                kwargs["trackingNumber"] = None      # a small model invents tracking numbers: only the customer's own words count
            drafted.update(await real_draft(**kwargs))
            return dict(drafted)
        executors["draft_complaint"] = recording_draft

    ran = []
    reply = await run_tool_agent(SYSTEM_PROMPT + roles.prompt_context(current_user), tools, executors, message, history, sentiment, on_stage=on_stage, ran_out=ran)

    # A small model often talks about the problem ("I'm sorry to hear that, please confirm...") instead of calling draft_complaint, so the
    # customer is asked to confirm something that does not exist. When the message plainly reports a problem and no draft was made,
    # read the report with structured output (a JSON schema cannot be answered with chat) and draft it ourselves.
    if customer and not drafted and "get_complaint_status" not in ran and _REPORT.search(said) and not _STATUS_QUERY.search(said) \
            and "draft_complaint" in executors and not ollama_client.is_unavailable():
        try:
            found = await ollama_client.extract_complaint(said, history)
        except Exception as err:
            log.warning("complaint extraction failed", extra={"event": "complaint_extract_failed", "error_type": type(err).__name__})
            found = None
        if found:
            await executors["draft_complaint"](**{k: v for k, v in found.items() if v})

    # "What's the status of my complaints?" is a database question. If the model did not look it up (it promised, chatted, or Ollama is
    # down), answer from the customer's own rows instead of a generic failure.
    if customer and not drafted and _STATUS_QUERY.search(said) and ("get_complaint_status" not in ran or reply is None
                                                                    or reply == PROMISE_REPLACEMENT or is_empty_promise(reply)):
        if meta is not None:
            meta["source"] = "builtin"
        return await _status_summary(current_user)

    # What the customer reads about drafting and filing comes from what the server actually did, not from model text.
    if drafted:
        return drafted["summary"] if drafted.get("drafted") else f"I couldn't set that up: {drafted.get('note', 'something went wrong.')}"
    if reply and _CLAIMS_FILED.search(reply):
        return NOT_FILED
    return reply
