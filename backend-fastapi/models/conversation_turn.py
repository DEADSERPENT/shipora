from datetime import datetime
from typing import Literal, Optional

import pymongo
from beanie import Document, Insert, before_event


class ConversationTurn(Document):
    sessionId: str
    role: Literal["user", "assistant"]
    content: str
    agent: Optional[Literal["tracking", "complaints", "schedule", "support", "general"]] = None
    createdAt: Optional[datetime] = None

    class Settings:
        name = "conversation_turns"
        indexes = [
            pymongo.IndexModel([("sessionId", pymongo.ASCENDING), ("createdAt", pymongo.ASCENDING)]),
        ]

    @before_event(Insert)
    def _on_insert(self):
        self.createdAt = datetime.utcnow()
