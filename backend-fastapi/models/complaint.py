from datetime import datetime
from typing import Literal, Optional

from beanie import Document, Insert, PydanticObjectId, Replace, Save, before_event


class Complaint(Document):
    residentId: Optional[PydanticObjectId] = None
    residentName: Optional[str] = None
    residentEmail: Optional[str] = None
    isAnonymous: bool = False
    subject: str
    category: Literal[
        "missed_pickup", "vehicle_issue", "timing", "cleanliness", "driver_behaviour", "other"
    ]
    description: str
    status: Literal["open", "in_progress", "resolved", "closed"] = "open"
    adminReply: str = ""
    resolvedAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    class Settings:
        name = "complaints"

    @before_event(Insert)
    def _on_insert(self):
        now = datetime.utcnow()
        self.createdAt = now
        self.updatedAt = now

    @before_event(Replace, Save)
    def _on_update(self):
        self.updatedAt = datetime.utcnow()
