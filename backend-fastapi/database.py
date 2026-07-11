from beanie import init_beanie

import config
from models.admin import Admin
from models.chat_analytics import ChatAnalytics
from models.complaint import Complaint
from models.conversation_turn import ConversationTurn
from models.driver import Driver
from models.support_config import SupportConfig
from models.user import User
from models.vehicle_log import VehicleLog

DOCUMENT_MODELS = [User, Driver, Admin, VehicleLog, Complaint, SupportConfig, ChatAnalytics, ConversationTurn]


async def connect_db():
    """Connect to MongoDB, mirroring server.js's connectDB(): try a real
    Mongo instance first, fall back to an in-memory mock if unreachable."""
    try:
        from motor.motor_asyncio import AsyncIOMotorClient

        client = AsyncIOMotorClient(config.MONGO_URI, serverSelectionTimeoutMS=3000)
        await client.admin.command("ping")
        db = client.get_default_database()
        await init_beanie(database=db, document_models=DOCUMENT_MODELS)
        print(f"✅ MongoDB Connected: {config.MONGO_URI}")
    except Exception:
        print("⚠️  Local MongoDB not found — starting in-memory MongoDB...")
        from mongomock_motor import AsyncMongoMockClient

        client = AsyncMongoMockClient()
        db = client["waste-disposal"]
        await init_beanie(database=db, document_models=DOCUMENT_MODELS)
        print("✅ In-memory MongoDB started (data resets on restart)")
