import logging

from beanie import init_beanie

import config
from models.admin import Admin
from models.chat_analytics import ChatAnalytics
from models.complaint_draft import ComplaintDraft
from models.conversation_turn import ConversationTurn
from models.customer import Customer
from models.delivery_agent import DeliveryAgent
from models.delivery_issue import DeliveryIssue
from models.shipment import Shipment
from models.support_config import SupportConfig
from models.tracking_log import TrackingLog
from services.idempotency import ensure_indexes

log = logging.getLogger("shipora.db")

REAL_DB = False  # True once connected to an actual MongoDB (Atlas/local): see routes/auth.py admin sign-up policy
IN_MEMORY = False  # True only when the throw-away mock DB is in use; main.py seeds demo data solely in that case

DOCUMENT_MODELS = [Customer, DeliveryAgent, Admin, TrackingLog, DeliveryIssue, Shipment, SupportConfig, ChatAnalytics, ConversationTurn, ComplaintDraft]


async def connect_db():
    """Connect to MongoDB (Atlas or local). In development/test, an unreachable
    database falls back to an in-memory mock so the app still boots; in production
    that fallback is forbidden — silently serving from a throw-away database would
    lose data, so startup fails instead. Connection strings are always redacted in logs."""
    global IN_MEMORY, REAL_DB
    IN_MEMORY = False
    REAL_DB = False
    safe_uri = config.redact_uri(config.MONGO_URI)
    try:
        from motor.motor_asyncio import AsyncIOMotorClient

        client = AsyncIOMotorClient(config.MONGO_URI, serverSelectionTimeoutMS=3000)
        await client.admin.command("ping")
        db = client.get_default_database()
        await init_beanie(database=db, document_models=DOCUMENT_MODELS)
        await ensure_indexes(db)
        REAL_DB = True
        log.info("MongoDB connected", extra={"event": "db_connected", "uri": safe_uri})
    except Exception as err:
        if config.is_production():
            log.critical("MongoDB unreachable and in-memory fallback is disabled in production",
                         extra={"event": "db_unreachable", "uri": safe_uri, "error_type": type(err).__name__})
            raise
        log.warning("MongoDB not reachable — starting in-memory MongoDB (data resets on restart)",
                    extra={"event": "db_fallback_inmemory", "uri": safe_uri, "error_type": type(err).__name__})
        from mongomock_motor import AsyncMongoMockClient

        IN_MEMORY = True

        client = AsyncMongoMockClient()
        db = client["shipora"]
        await init_beanie(database=db, document_models=DOCUMENT_MODELS)
        await ensure_indexes(db)
        log.info("In-memory MongoDB started", extra={"event": "db_inmemory_ready"})
