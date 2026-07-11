from datetime import datetime
from typing import List, Optional

import pymongo
from beanie import Document, Insert, PydanticObjectId, Replace, Save, before_event


class VehicleLog(Document):
    driverId: PydanticObjectId
    date: str  # JS toDateString() format, e.g. "Wed Jul 3 2026"
    lat: Optional[float] = None
    lng: Optional[float] = None
    currentArea: Optional[str] = None
    eta: Optional[str] = None
    areasCompleted: List[str] = []
    lastUpdated: Optional[datetime] = None
    isActive: bool = True
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    class Settings:
        name = "vehicle_logs"
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
