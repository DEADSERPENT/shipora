from datetime import datetime
from typing import Optional

from beanie import Document, Insert, Replace, Save, before_event

from auth_utils import compare_password


class Admin(Document):
    name: str
    email: str
    password: str  # bcrypt hash — callers must hash before assigning
    organization: str = ""
    role: str = "admin"
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    class Settings:
        name = "admins"

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
