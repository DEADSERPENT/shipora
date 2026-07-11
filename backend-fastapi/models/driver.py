from datetime import datetime
from typing import Optional

from beanie import Document, Insert, Replace, Save, before_event

from auth_utils import compare_password


class Driver(Document):
    name: str
    email: str
    password: str  # bcrypt hash — callers must hash before assigning
    phone: str
    vehicleNo: str
    licenseNo: str
    assignedArea: str
    role: str = "driver"
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    class Settings:
        name = "drivers"

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
