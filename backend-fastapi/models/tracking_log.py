from datetime import datetime
from typing import List, Optional

import pymongo
from beanie import Document, Insert, PydanticObjectId, Replace, Save, before_event


class TrackingLog(Document):
    """Per-agent, per-day delivery tracking history (live position, current
    area, ETA, areas covered, shipments handled). Stored in the
    `tracking_logs` collection. Field names driverId / areasCompleted are kept
    so the unique (driverId, date) index and existing documents stay valid;
    they mean "delivery agent id" and "areas covered today"."""

    driverId: PydanticObjectId  # == DeliveryAgent.id
    date: str  # JS toDateString() format, e.g. "Wed Jul 3 2026"
    lat: Optional[float] = None
    lng: Optional[float] = None
    currentArea: Optional[str] = None
    eta: Optional[str] = None
    areasCompleted: List[str] = []
    activeShipmentIds: List[str] = []  # shipments currently out with this agent
    deliveredCount: int = 0
    lastUpdated: Optional[datetime] = None
    isActive: bool = True
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    class Settings:
        name = "tracking_logs"
        indexes = [
            pymongo.IndexModel(
                [("driverId", pymongo.ASCENDING), ("date", pymongo.ASCENDING)],
                unique=True,
            )
        ]

    @before_event(Insert)
    def _on_insert(self):
        now = datetime.utcnow()
        self.createdAt = now
        self.updatedAt = now

    @before_event(Replace, Save)
    def _on_update(self):
        self.updatedAt = datetime.utcnow()
