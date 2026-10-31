from datetime import datetime
from typing import Literal, Optional

import pymongo
from beanie import Document, Insert, Replace, Save, before_event

from auth_utils import compare_password


class DeliveryAgent(Document):
    """Shipora delivery agent and their delivery vehicle. Stored in the
    `delivery_agents` collection. The vehicle is embedded as flat
    fields (vehicleNo / vehicleType) — one agent drives one vehicle in this
    model. `assignedArea` is the agent's delivery zone."""

    name: str
    email: str
    password: str  # bcrypt hash — callers must hash before assigning
    phone: str
    vehicleNo: str
    vehicleType: Literal["bike", "van", "truck"] = "van"
    licenseNo: str
    assignedArea: str
    availability: Literal["available", "on_delivery", "off_duty"] = "available"
    isSimulated: bool = False  # driven by services/simulator.py instead of a person
    role: str = "driver"  # wire-level role string kept as "driver" for JWT/frontend compatibility
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    class Settings:
        name = "delivery_agents"
        indexes = [pymongo.IndexModel([("email", pymongo.ASCENDING)], unique=True)]  # one account per e-mail, enforced by MongoDB (not just the sign-up check)

    @before_event(Insert)
    def _on_insert(self):
        now = datetime.utcnow()
        self.createdAt = now
        self.updatedAt = now
        self.email = self.email.lower()
        self.vehicleNo = self.vehicleNo.upper()
        self.licenseNo = self.licenseNo.upper()

    @before_event(Replace, Save)
    def _on_update(self):
        self.updatedAt = datetime.utcnow()

    def compare_password(self, plain: str) -> bool:
        return compare_password(plain, self.password)
