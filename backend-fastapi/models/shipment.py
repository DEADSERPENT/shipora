import secrets
from datetime import datetime
from typing import Dict, List, Literal, Optional, Set

import pymongo
from beanie import Document, Insert, PydanticObjectId, Replace, Save, before_event
from pydantic import BaseModel, Field

from models.customer import Location
from validation import Address, Name, OptionalText, Phone

ShipmentStatus = Literal[
    "CREATED", "PICKUP_SCHEDULED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED",
    "DELIVERY_FAILED", "CUSTOMER_UNAVAILABLE", "ADDRESS_ISSUE", "DAMAGED",
    "CANCELLED", "RETURN_TO_ORIGIN",
]

# Failures that can occur at pickup or at delivery; where the shipment may
# resume depends on which leg it failed on (see allowed_next_statuses).
EXCEPTION_STATUSES: Set[str] = {"DELIVERY_FAILED", "CUSTOMER_UNAVAILABLE", "ADDRESS_ISSUE"}
TERMINAL_STATUSES: Set[str] = {"DELIVERED", "CANCELLED", "RETURN_TO_ORIGIN"}

# Happy path + forward exits. Exception-state exits are computed from history.
_TRANSITIONS: Dict[str, Set[str]] = {
    "CREATED": {"PICKUP_SCHEDULED", "CANCELLED"},
    "PICKUP_SCHEDULED": {"PICKED_UP", "CUSTOMER_UNAVAILABLE", "ADDRESS_ISSUE", "CANCELLED"},
    "PICKED_UP": {"IN_TRANSIT", "DAMAGED", "RETURN_TO_ORIGIN"},
    "IN_TRANSIT": {"OUT_FOR_DELIVERY", "DAMAGED", "RETURN_TO_ORIGIN"},
    "OUT_FOR_DELIVERY": {"DELIVERED", "DELIVERY_FAILED", "CUSTOMER_UNAVAILABLE", "ADDRESS_ISSUE", "DAMAGED"},
    "DAMAGED": {"RETURN_TO_ORIGIN", "CANCELLED"},
}

# Statuses a delivery agent may set; scheduling, cancelling and returning to
# origin are admin/customer decisions.
AGENT_SETTABLE: Set[str] = {
    "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED",
    "DELIVERY_FAILED", "CUSTOMER_UNAVAILABLE", "ADDRESS_ISSUE", "DAMAGED",
}
CUSTOMER_CANCELLABLE: Set[str] = {"CREATED", "PICKUP_SCHEDULED"}


class StatusEvent(BaseModel):
    status: str
    at: datetime
    byRole: str
    byId: Optional[str] = None
    note: str = ""


def allowed_next_statuses(current: str, history: List[StatusEvent]) -> Set[str]:
    if current in TERMINAL_STATUSES:
        return set()
    if current in EXCEPTION_STATUSES:
        # Which leg was the shipment on before the exception?
        prior = next((e.status for e in reversed(history[:-1]) if e.status not in EXCEPTION_STATUSES), "OUT_FOR_DELIVERY")
        if prior in ("PICKUP_SCHEDULED", "CREATED"):
            return {"PICKUP_SCHEDULED", "CANCELLED"}
        return {"OUT_FOR_DELIVERY", "RETURN_TO_ORIGIN"}
    return set(_TRANSITIONS.get(current, set()))


def _luhn_check_digit(body: str) -> str:
    """Luhn check digit for a string of digits (the same scheme as card numbers): catches every single-digit mistake and
    nearly all neighbouring swaps — exactly the errors speech recognition makes when a caller reads a number out."""
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return str((10 - total % 10) % 10)


def tracking_checksum_ok(ref: str) -> bool:
    """New-format IDs (SHP + 8 digits, the last is a check digit) are verified without touching the database. Legacy
    SHP + 10 hex IDs have no check digit and are always passed on to the lookup."""
    digits = ref[3:]
    if ref.startswith("SHP") and digits.isdigit():
        if len(digits) == 8:
            return _luhn_check_digit(digits[:-1]) == digits[-1]
        return len(digits) == 10          # an all-digit legacy hex ID; any other length means a digit was dropped or added
    return True


def generate_tracking_number() -> str:
    """SHP + 8 digits, e.g. SHP48217390. Digits only, because it is read aloud on phone calls: letters such as B/C/D/E
    sound alike, digits are what speech recognition hears best. 7 random digits + 1 check digit = 10 million IDs; the unique
    index plus the retry in services/booking.py handle collisions. Older SHP + 10 hex IDs stay valid."""
    body = "".join(secrets.choice("0123456789") for _ in range(7))
    if body[0] == "0":                      # no leading zero: "SHP zero..." is easy to mishear or drop
        body = str(secrets.choice("123456789")) + body[1:]
    return "SHP" + body + _luhn_check_digit(body)


class Party(BaseModel):
    name: Name
    phone: Phone
    address: Address
    location: Optional[Location] = None


class ParcelDetails(BaseModel):
    description: OptionalText = ""
    category: Literal["documents", "electronics", "clothing", "food", "fragile", "other"] = "other"
    weightKg: float = Field(default=1.0, gt=0, le=1000, allow_inf_nan=False)
    lengthCm: Optional[float] = Field(default=None, gt=0, le=1000, allow_inf_nan=False)
    widthCm: Optional[float] = Field(default=None, gt=0, le=1000, allow_inf_nan=False)
    heightCm: Optional[float] = Field(default=None, gt=0, le=1000, allow_inf_nan=False)
    declaredValue: float = Field(default=0.0, ge=0, le=10_000_000, allow_inf_nan=False)
    fragile: bool = False


class Shipment(Document):
    """A parcel moving from a sender to a recipient. New collection: `shipments`."""

    trackingNumber: str
    customerId: PydanticObjectId
    customerName: Optional[str] = None
    sender: Party
    recipient: Party
    parcel: ParcelDetails = ParcelDetails()
    serviceType: Literal["same_day"] = "same_day"  # Shipora is same-day only
    status: ShipmentStatus = "CREATED"
    fare: float = 0  # INR, estimated at booking (services/pricing.py)
    distanceKm: float = 0
    paymentMethod: Literal["cash", "upi"] = "cash"  # paid to the rider on delivery
    statusHistory: List[StatusEvent] = []
    assignedAgentId: Optional[PydanticObjectId] = None
    pickupScheduledAt: Optional[datetime] = None
    estimatedDelivery: Optional[datetime] = None
    deliveredAt: Optional[datetime] = None
    deliveryAttempts: int = 0
    rev: int = 0  # optimistic-concurrency counter, bumped by every mutation (see services/shipments.py)
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    class Settings:
        name = "shipments"
        indexes = [
            pymongo.IndexModel([("trackingNumber", pymongo.ASCENDING)], unique=True),
            pymongo.IndexModel([("customerId", pymongo.ASCENDING), ("createdAt", pymongo.DESCENDING)]),
            pymongo.IndexModel([("assignedAgentId", pymongo.ASCENDING), ("status", pymongo.ASCENDING)]),
        ]

    @before_event(Insert)
    def _on_insert(self):
        now = datetime.utcnow()
        self.createdAt = now
        self.updatedAt = now

    @before_event(Replace, Save)
    def _on_update(self):
        self.updatedAt = datetime.utcnow()

    def record(self, status: str, by_role: str, by_id: Optional[str] = None, note: str = "") -> None:
        self.status = status
        self.statusHistory.append(StatusEvent(status=status, at=datetime.utcnow(), byRole=by_role, byId=by_id, note=note))
