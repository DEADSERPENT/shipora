"""Draft -> confirm -> file for delivery issues raised in chat (text or voice). The model may only DRAFT. Filing happens here,
on a clear yes from the same authenticated customer in the same session, against the exact content they were shown, once.
Every user-facing sentence about the outcome is written here from what actually happened, never by the model."""

import hashlib
import re
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from pymongo import ReturnDocument

import config
from models.complaint_draft import ComplaintDraft

CATEGORY_LABELS = {
    "delayed_delivery": "Delayed delivery", "lost_parcel": "Lost parcel", "damaged_parcel": "Damaged parcel",
    "wrong_address": "Wrong address", "agent_behaviour": "Agent behaviour", "failed_delivery": "Failed delivery", "other": "Other",
}

# A clean confirmation is short and carries no extra instruction. "yes but make it urgent" is an edit, not a yes.
_YES = re.compile(r"^\W*(?:yes|yeah|yep|yup|sure|ok(?:ay)?|go ahead|please(?: do| file| go ahead)?|file it|do it|confirm(?:ed)?|that'?s right|correct)\W*"
                  r"(?:please|thanks|thank you|file it|go ahead|do it)?\W*$", re.I)
_NO = re.compile(r"^\W*(?:no|nope|nah|cancel|don'?t|do not|stop|never ?mind|discard|forget it|not now|no thanks)\b", re.I)


def classify_reply(message: str) -> str:
    """'confirm' | 'decline' | 'other'. Only an unambiguous short yes confirms; anything else leaves the draft untouched."""
    m = (message or "").strip()
    if _NO.search(m):
        return "decline"
    if len(m.split()) <= 6 and _YES.match(m):
        return "confirm"
    return "other"


def content_hash(subject: str, category: str, description: str, tracking: Optional[str], anonymous: bool) -> str:
    raw = "\x1f".join([subject.strip(), category, description.strip(), (tracking or "").strip().upper(), "1" if anonymous else "0"])
    return hashlib.sha256(raw.encode()).hexdigest()


def _scope(user: dict, session_id: Optional[str]) -> dict:
    return {"userId": user["id"], "sessionId": session_id or f"user:{user['id']}"}


def summary_text(d: ComplaintDraft) -> str:
    minutes = max(1, int(config.complaint_draft_ttl_seconds() // 60))
    lines = [
        "Here's what I'll file — nothing is filed yet:",
        f"• Subject: {d.subject}",
        f"• Category: {CATEGORY_LABELS.get(d.category, d.category)}",
        f"• Details: {d.description}",
    ]
    if d.trackingNumber:
        lines.append(f"• Parcel: {d.trackingNumber}")
    if d.isAnonymous:
        lines.append("• Your name will be hidden from Operations")
    lines.append(f"Reply **yes** to file it or **no** to cancel. This expires in {minutes} minutes.")
    return "\n".join(lines)


async def create_draft(user: dict, session_id: Optional[str], subject: str, category: str, description: str,
                       tracking: Optional[str], anonymous: bool) -> ComplaintDraft:
    scope = _scope(user, session_id)
    # A new draft replaces any pending one: only the content the customer last saw can ever be confirmed.
    await ComplaintDraft.get_motor_collection().update_many({**scope, "status": "pending"}, {"$set": {"status": "superseded", "updatedAt": datetime.utcnow()}})
    d = ComplaintDraft(
        draftId=uuid.uuid4().hex, subject=subject.strip(), category=category, description=description.strip(),
        trackingNumber=tracking.strip().upper() if tracking else None, isAnonymous=bool(anonymous),
        contentHash=content_hash(subject, category, description, tracking, bool(anonymous)),
        expiresAt=datetime.utcnow() + timedelta(seconds=config.complaint_draft_ttl_seconds()), **scope,
    )
    await d.insert()
    return d


async def latest(user: dict, session_id: Optional[str]) -> Optional[ComplaintDraft]:
    return await ComplaintDraft.find(_scope(user, session_id)).sort([("createdAt", -1), ("_id", -1)]).first_or_none()   # _id breaks ties: createdAt only has millisecond precision


async def has_pending(user: dict, session_id: Optional[str]) -> bool:
    d = await latest(user, session_id)
    return bool(d and d.status == "pending")


async def awaiting(user: dict, session_id: Optional[str]) -> bool:
    """True while this session has a draft that a yes/no could still concern: waiting for an answer, being filed, or filed in
    the last two minutes (so a repeated yes gets "already filed" instead of starting something new)."""
    d = await latest(user, session_id)
    if d is None:
        return False
    if d.status in ("pending", "filing"):
        return True
    return d.status == "filed" and bool(d.updatedAt) and datetime.utcnow() - d.updatedAt < timedelta(minutes=2)


async def decline(user: dict, session_id: Optional[str]) -> Optional[str]:
    res = await ComplaintDraft.get_motor_collection().find_one_and_update(
        {**_scope(user, session_id), "status": "pending"}, {"$set": {"status": "declined", "updatedAt": datetime.utcnow()}},
        sort=[("createdAt", -1), ("_id", -1)], return_document=ReturnDocument.AFTER)
    return "Okay — I haven't filed anything. Tell me if you'd like to report it later." if res else None


async def confirm(user: dict, session_id: Optional[str]) -> Optional[str]:
    """Files the pending draft, at most once. Returns the sentence to show, or None when there is nothing to confirm."""
    from tools.complaint_tools import insert_complaint        # late import: tools -> services is the normal direction

    scope = _scope(user, session_id)
    now = datetime.utcnow()
    # Atomic claim: of any number of simultaneous "yes" replies exactly one flips pending -> filing.
    claimed = await ComplaintDraft.get_motor_collection().find_one_and_update(
        {**scope, "status": "pending", "expiresAt": {"$gt": now}}, {"$set": {"status": "filing", "updatedAt": now}},
        sort=[("createdAt", -1), ("_id", -1)], return_document=ReturnDocument.AFTER)
    if claimed is None:
        d = await latest(user, session_id)
        if d is None:
            return None
        if d.status == "filing":
            return "I'm already filing that — one moment."
        if d.status == "filed" and d.updatedAt and datetime.utcnow() - d.updatedAt < timedelta(minutes=2):
            return f"That issue is already filed (reference {d.complaintId[-6:] if d.complaintId else 'on record'}). I haven't created a duplicate."
        if d.status == "pending":                                   # pending but past its expiry
            await ComplaintDraft.get_motor_collection().update_one({"_id": d.id, "status": "pending"}, {"$set": {"status": "failed", "failureReason": "expired"}})
            return "That draft expired, so I haven't filed anything. Tell me what happened again and I'll draft it afresh."
        return None
    d = await ComplaintDraft.get(claimed["_id"])
    if content_hash(d.subject, d.category, d.description, d.trackingNumber, d.isAnonymous) != d.contentHash:
        await _mark(d, "failed", reason="content changed after it was shown")
        return "I couldn't file that, because the details no longer match what I showed you. Please tell me again and I'll re-draft it."
    try:
        issue = await insert_complaint(d.subject, d.category, d.description, d.isAnonymous, user, d.trackingNumber)
    except HTTPException as err:
        await _mark(d, "failed", reason=str(err.detail))
        return f"I couldn't file that: {err.detail} Nothing was filed — please try again or use the Delivery Issues page."
    except Exception as err:                                          # never report success for a write that did not happen
        await _mark(d, "failed", reason=type(err).__name__)
        return "I couldn't file that right now, and nothing was filed. Please try again in a moment."
    await _mark(d, "filed", complaint=str(issue.id))
    return (f"Done — I've filed your delivery issue “{issue.subject}” ({CATEGORY_LABELS.get(issue.category, issue.category)}). "
            f"Status: {issue.status}. Reference: {str(issue.id)[-6:]}. Operations will review it.")


async def _mark(d: ComplaintDraft, status: str, complaint: Optional[str] = None, reason: Optional[str] = None) -> None:
    await ComplaintDraft.get_motor_collection().update_one(
        {"_id": d.id}, {"$set": {"status": status, "complaintId": complaint, "failureReason": reason, "updatedAt": datetime.utcnow()}})
