import re

from agents import roles
from agents.base import run_tool_agent
from services import complaint_drafts
from tools.complaint_tools import bind_complaint_tools

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


async def handle(message: str, history: list, sentiment: str, current_user: dict = None, on_stage=None, session_id: str = None,
                 channel: str = "text") -> str:
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

    reply = await run_tool_agent(SYSTEM_PROMPT + roles.prompt_context(current_user), tools, executors, message, history, sentiment, on_stage=on_stage)

    # What the customer reads about drafting and filing comes from what the server actually did, not from model text.
    if drafted:
        return drafted["summary"] if drafted.get("drafted") else f"I couldn't set that up: {drafted.get('note', 'something went wrong.')}"
    if reply and _CLAIMS_FILED.search(reply):
        return NOT_FILED
    return reply
