from datetime import datetime
from typing import Literal, Optional

import pymongo
from beanie import Document, Insert, Replace, Save, before_event
from pydantic import BaseModel, Field

from auth_utils import compare_password


class Location(BaseModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)


class Customer(Document):
    """Shipora customer (sender of parcels). Stored in the `customers` collection."""

    name: str
    email: str
    password: str  # bcrypt hash — callers must hash before assigning
    phone: str
    address: str
    location: Location
    customerType: Literal["individual", "business"] = "individual"
    deliveryInstructions: str = ""
    role: str = "user"  # wire-level role string kept as "user" for JWT/frontend compatibility
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    class Settings:
        name = "customers"
        indexes = [pymongo.IndexModel([("email", pymongo.ASCENDING)], unique=True)]  # one account per e-mail, enforced by MongoDB (not just the sign-up check)

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
