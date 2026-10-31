from datetime import datetime
from typing import Literal, Optional

from beanie import Document, Insert, PydanticObjectId, Replace, Save, before_event


class ChatAnalytics(Document):
    sessionId: str
    userId: Optional[PydanticObjectId] = None
    userRole: Optional[Literal["user", "driver", "admin"]] = None
    channel: Literal["text", "voice"]
    transcript: str
    reply: str
    agent: Literal["tracking", "complaints", "schedule", "support", "general"]
    sentiment: Literal["positive", "neutral", "negative"]
    source: Literal["ai", "builtin"]
    sttConfidence: Optional[float] = None
    latencyMs: dict = {}
    metrics: dict = {}          # per-turn instrumentation: stage timings, provider call counts, provider errors (services/metrics.py)
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    class Settings:
        name = "chat_analytics"

    @before_event(Insert)
    def _on_insert(self):
        now = datetime.utcnow()
        self.createdAt = now
        self.updatedAt = now

    @before_event(Replace, Save)
    def _on_update(self):
        self.updatedAt = datetime.utcnow()
