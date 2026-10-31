from datetime import datetime
from typing import Literal, Optional

import pymongo
from beanie import Document, Insert, before_event

DraftStatus = Literal["pending", "filing", "filed", "declined", "superseded", "failed"]


class ComplaintDraft(Document):
    """A delivery issue the assistant has summarised for a customer but NOT filed. It becomes a real DeliveryIssue only when
    that same customer, in that same session, confirms it before `expiresAt`. `contentHash` pins exactly what they were
    shown, so what is filed is what was confirmed; `status` makes the confirmation single-use."""

    draftId: str
    userId: str
    sessionId: str
    subject: str
    category: str
    description: str
    trackingNumber: Optional[str] = None
    isAnonymous: bool = False
    contentHash: str
    status: DraftStatus = "pending"
    complaintId: Optional[str] = None
    failureReason: Optional[str] = None
    expiresAt: datetime
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    class Settings:
        name = "complaint_drafts"
        indexes = [
            pymongo.IndexModel([("draftId", pymongo.ASCENDING)], unique=True),
            pymongo.IndexModel([("userId", pymongo.ASCENDING), ("sessionId", pymongo.ASCENDING), ("createdAt", pymongo.DESCENDING)]),
            pymongo.IndexModel([("createdAt", pymongo.ASCENDING)], expireAfterSeconds=7 * 24 * 3600),   # drafts are not kept for long
        ]

    @before_event(Insert)
    def _on_insert(self):
        self.createdAt = self.updatedAt = datetime.utcnow()
