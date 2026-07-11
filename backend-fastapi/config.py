import os

from dotenv import load_dotenv

load_dotenv()

PORT = int(os.getenv("PORT", "5001"))
CLIENT_URL = os.getenv("CLIENT_URL", "http://localhost:3000")
JWT_SECRET = os.getenv("JWT_SECRET", "ecotrack_secret")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/waste-disposal")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# STT/TTS reuse OPENAI_API_KEY above — no separate key needed.
STT_PROVIDER = os.getenv("STT_PROVIDER", "openai")
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "openai")
TTS_VOICE = os.getenv("TTS_VOICE", "nova")  # nova/shimmer read as female; alloy/echo/onyx/fable read male or neutral
VOICE_MAX_UPLOAD_BYTES = int(os.getenv("VOICE_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))

PLACEHOLDER_VALUES = {None, "", "your_api_key_here"}
