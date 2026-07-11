from datetime import datetime
from typing import Optional

from beanie import Document, Insert, Replace, Save, before_event


class SupportConfig(Document):
    singleton: str = "config"
    phone: str = "1800-ECO-TRACK"
    email: str = "support@ecotrack.in"
    whatsapp: str = "+91 98765 43210"
    officeAddress: str = "City Municipal Office, Ground Floor, Civic Center"
    officeHours: str = "Mon – Fri · 9 AM – 5 PM"
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    class Settings:
        name = "support_configs"

    @before_event(Insert)
    def _on_insert(self):
        now = datetime.utcnow()
        self.createdAt = now
        self.updatedAt = now

    @before_event(Replace, Save)
    def _on_update(self):
        self.updatedAt = datetime.utcnow()
