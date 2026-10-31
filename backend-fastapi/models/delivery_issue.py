from datetime import datetime
from typing import Literal, Optional

from beanie import Document, Insert, PydanticObjectId, Replace, Save, before_event

IssueCategory = Literal[
    "delayed_delivery", "lost_parcel", "damaged_parcel", "wrong_address",
    "agent_behaviour", "failed_delivery", "other",
]

class DeliveryIssue(Document):
    """A customer-reported problem with a delivery, optionally linked to a
    shipment. Stored in the `delivery_issues` collection."""

    customerId: Optional[PydanticObjectId] = None
    customerName: Optional[str] = None
    customerEmail: Optional[str] = None
    shipmentId: Optional[PydanticObjectId] = None
    trackingNumber: Optional[str] = None
    isAnonymous: bool = False
    subject: str
    category: IssueCategory
    description: str
    status: Literal["open", "in_progress", "resolved", "closed"] = "open"
    adminReply: str = ""
    resolvedAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    class Settings:
        name = "delivery_issues"

    @before_event(Insert)
    def _on_insert(self):
        now = datetime.utcnow()
        self.createdAt = now
        self.updatedAt = now

    @before_event(Replace, Save)
    def _on_update(self):
        self.updatedAt = datetime.utcnow()
