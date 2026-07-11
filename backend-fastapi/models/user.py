from datetime import datetime
from typing import Literal, Optional

from beanie import Document, Insert, Replace, Save, before_event
from pydantic import BaseModel

from auth_utils import compare_password


class Location(BaseModel):
    lat: float
    lng: float


class User(Document):
    name: str
    email: str
    password: str  # bcrypt hash — callers must hash before assigning
    phone: str
    address: str
    location: Location
    wasteType: Literal["household", "recyclable", "organic", "mixed"] = "mixed"
    pickupSchedule: Literal["daily", "alternate", "weekly"] = "daily"
    residentType: Literal["house", "flat"] = "house"
    role: str = "user"
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    class Settings:
        name = "users"

    @before_event(Insert)
    def _on_insert(self):
        now = datetime.utcnow()
        self.createdAt = now
        self.updatedAt = now
        self.email = self.email.lower()

    @before_event(Replace, Save)
    def _on_update(self):
        self.updatedAt = datetime.utcnow()

    def compare_password(self, plain: str) -> bool:
        return compare_password(plain, self.password)
