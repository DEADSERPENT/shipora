import os
import re
from typing import Mapping, Optional
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    """Raised at startup when the environment is missing or insecure. Messages
    name the offending variable but never include its value."""


# ─── Server ──────────────────────────────────────────────────────────────────
PORT = int(os.getenv("PORT", "5001"))
CLIENT_URL = os.getenv("CLIENT_URL", "http://localhost:3000")

# JWT_SECRET deliberately has NO default: the app refuses to start without a strong one
# (see check_environment). Changing it invalidates every token issued with the old
# value — users simply sign in again.
JWT_SECRET = os.getenv("JWT_SECRET")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/shipora")

# Same-day bike delivery pricing + limits (see services/pricing.py). The base fare covers the first FARE_INCLUDED_KM;
# every further km costs FARE_PER_KM_INR. Tune per deployment — these are starting values, not a published tariff.
FARE_BASE_INR = float(os.getenv("FARE_BASE_INR", "48"))
FARE_INCLUDED_KM = float(os.getenv("FARE_INCLUDED_KM", "1"))
FARE_PER_KM_INR = float(os.getenv("FARE_PER_KM_INR", "12"))
FARE_FREE_WEIGHT_KG = float(os.getenv("FARE_FREE_WEIGHT_KG", "5"))  # parcels up to this weight add nothing
FARE_PER_EXTRA_KG_INR = float(os.getenv("FARE_PER_EXTRA_KG_INR", "4"))  # each kg above it
MAX_PARCEL_KG = float(os.getenv("MAX_PARCEL_KG", "20"))  # a two-wheeler's carrying limit
ETA_BASE_MINUTES = float(os.getenv("ETA_BASE_MINUTES", "30"))  # rider assignment + pickup
ETA_MINUTES_PER_KM = float(os.getenv("ETA_MINUTES_PER_KM", "4"))

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")  # "gemini" (default) or "ollama" (local) — classification, tool-calling and services/llm.py's fallback tier
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # STT/TTS only (see services/stt.py/tts.py) — not used for any LLM/chat path
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# STT/TTS reuse OPENAI_API_KEY above — no separate key needed.
STT_PROVIDER = os.getenv("STT_PROVIDER", "openai")
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "openai")
TTS_VOICE = os.getenv("TTS_VOICE", "nova")  # nova/shimmer read as female; alloy/echo/onyx/fable read male or neutral
# Local LLM via Ollama (LLM_PROVIDER=ollama): runs on the GPU, nothing leaves the machine. Needs a model with tool support.
CLASSIFIER_MODE = os.getenv("CLASSIFIER_MODE", "llm").strip().lower()   # llm | hybrid (keyword fast-path when decisive, else LLM)
VOICE_WARMUP = os.getenv("VOICE_WARMUP", "true").strip().lower() not in ("0", "false", "no", "off")   # load STT/TTS/LLM at startup
VOICE_MAX_SPOKEN_CHARS = int(os.getenv("VOICE_MAX_SPOKEN_CHARS", "420"))   # spoken replies stop at a sentence boundary; the chat bubble keeps the full text
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_CLASSIFIER_MODEL = os.getenv("OLLAMA_CLASSIFIER_MODEL", "")   # empty = same as OLLAMA_MODEL
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30"))
# Context window. Ollama defaults to the model's maximum (131k for phi4-mini!), whose KV cache pushes the model off a 6 GB GPU onto the CPU
# (measured: 13 s per turn instead of 1.7 s). Our prompts are a few hundred tokens.
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")             # keep the model resident on the GPU between turns
GEMINI_VOICE_TIMEOUT_SECONDS = float(os.getenv("GEMINI_VOICE_TIMEOUT_SECONDS", "8"))  # tighter per-call budget on the voice channel: a caller will not wait 20 s
GEMINI_TIMEOUT_SECONDS = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "20"))  # hard budget per Gemini call (retries happen inside it) - see services/gemini_client.py
GEMINI_COOLDOWN_SECONDS = float(os.getenv("GEMINI_COOLDOWN_SECONDS", "30"))  # after an outage-type failure, skip Gemini for this long and use the fallbacks
VOICE_MAX_UPLOAD_BYTES = int(os.getenv("VOICE_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))

# Local, open-source voice providers (STT_PROVIDER=faster_whisper / TTS_PROVIDER=piper). Optional:
# nothing here is read unless one of those providers is selected. Model files are NOT in the repo —
# see docs/LOCAL_VOICE.md. Relative paths resolve against backend-fastapi/.
LOCAL_MODELS_DIR = os.getenv("LOCAL_MODELS_DIR", "local_models")
FASTER_WHISPER_MODEL = os.getenv("FASTER_WHISPER_MODEL", "small")  # size name (downloaded on first use) or a local model directory
FASTER_WHISPER_DEVICE = os.getenv("FASTER_WHISPER_DEVICE", "auto")  # auto | cpu | cuda
FASTER_WHISPER_COMPUTE_TYPE = os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "default")  # e.g. float16 on GPU, int8 on CPU
FASTER_WHISPER_LANGUAGE = os.getenv("FASTER_WHISPER_LANGUAGE") or None  # None = auto-detect per recording
PIPER_VOICE = os.getenv("PIPER_VOICE", "en_US-lessac-medium.onnx")  # file name inside LOCAL_MODELS_DIR/piper/, or an absolute path
# STT_PROVIDER=onnx_local: Whisper on ONNX Runtime via the pure-Python onnx-asr package — for machines where the
# faster-whisper/CTranslate2 native library can't load (e.g. blocked by a Windows application-control policy).
ONNX_STT_MODEL = os.getenv("ONNX_STT_MODEL", "whisper-base")  # an onnx-asr model name; only whisper-base is auto-downloaded
ONNX_STT_QUANTIZATION = os.getenv("ONNX_STT_QUANTIZATION", "int8") or None  # int8 ≈ 107 MB; empty = full precision ≈ 398 MB
ONNX_STT_DEVICE = os.getenv("ONNX_STT_DEVICE", "cpu")  # cpu | cuda (cuda needs onnxruntime-gpu instead of onnxruntime)
ONNX_STT_LANGUAGE = os.getenv("ONNX_STT_LANGUAGE") or None  # Whisper language code, e.g. en, hi, kn; None = auto-detect
ONNX_STT_MAX_SECONDS = int(os.getenv("ONNX_STT_MAX_SECONDS", "30"))  # Whisper handles 30 s windows; longer recordings are truncated

PLACEHOLDER_VALUES = {None, "", "your_api_key_here"}

# ─── Environment-dependent settings (read lazily so tests/processes can change them) ─
VALID_APP_ENVS = ("development", "test", "production")
MIN_JWT_SECRET_LENGTH = 32
_INSECURE_SECRETS = {"shipora_secret", "your_jwt_secret_here", "secret", "changeme", "change-me", "password", "jwt_secret", "test-secret"}
_PLACEHOLDER_PREFIXES = ("your_", "your-", "change", "shipora", "example", "replace", "test", "default", "secret", "<")


def app_env(env: Optional[Mapping[str, str]] = None) -> str:
    return ((env if env is not None else os.environ).get("APP_ENV") or "development").strip().lower()


def is_production(env: Optional[Mapping[str, str]] = None) -> bool:
    return app_env(env) == "production"


def _jwt_secret_problem(secret: Optional[str]) -> Optional[str]:
    if not secret or not secret.strip():
        return "JWT_SECRET is not set. Generate one with:  python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    s = secret.strip()
    low = s.lower()
    if low in _INSECURE_SECRETS or low.startswith(_PLACEHOLDER_PREFIXES):
        return "JWT_SECRET is a placeholder/known-insecure value."
    if len(s) < MIN_JWT_SECRET_LENGTH:
        return f"JWT_SECRET is too short (minimum {MIN_JWT_SECRET_LENGTH} characters)."
    if len(set(s)) < 8:
        return "JWT_SECRET has too little variety to be a random secret."
    return None


def _origin_problems(origins, production: bool, var: str):
    problems = []
    for o in origins:
        u = urlsplit(o)
        if o == "*" or "*" in o:
            problems.append(f"{var}: wildcard origins are not allowed (credentials are enabled).")
        elif u.scheme not in ("http", "https") or not u.netloc or u.path not in ("", "/") or u.query or u.fragment:
            problems.append(f"{var}: '{o}' must look like https://host[:port] (no path).")
        elif production and (u.scheme != "https" or u.hostname in ("localhost", "127.0.0.1", "::1")):
            problems.append(f"{var}: '{o}' is not allowed in production (needs a public https origin).")
    return problems


def cors_origins(env: Optional[Mapping[str, str]] = None) -> list:
    """Allowed browser origins: CORS_ORIGINS (comma separated) if set, else CLIENT_URL."""
    e = env if env is not None else os.environ
    raw = e.get("CORS_ORIGINS") or e.get("CLIENT_URL") or "http://localhost:3000"
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


def check_environment(env: Optional[Mapping[str, str]] = None) -> list:
    """Returns human-readable problems with the configuration (empty list = OK).
    Pure function of `env` (defaults to os.environ) so it can be unit-tested."""
    e = env if env is not None else os.environ
    problems = []

    if app_env(e) not in VALID_APP_ENVS:
        problems.append(f"APP_ENV must be one of {', '.join(VALID_APP_ENVS)}.")
    prod = is_production(e)

    secret_problem = _jwt_secret_problem(e.get("JWT_SECRET"))
    if secret_problem:
        problems.append(secret_problem)

    var = "CORS_ORIGINS" if e.get("CORS_ORIGINS") else "CLIENT_URL"
    if prod and not (e.get("CORS_ORIGINS") or e.get("CLIENT_URL")):
        problems.append("CLIENT_URL (or CORS_ORIGINS) must be set explicitly in production.")
    else:
        problems += _origin_problems(cors_origins(e), prod, var)
    return problems


def admin_signup_code() -> Optional[str]:
    """Invite code required to create an operations (admin) account. None = not configured."""
    return (os.environ.get("ADMIN_SIGNUP_CODE") or "").strip() or None


def bcrypt_rounds() -> int:
    """Password hashing cost. 12 in real deployments; tests lower it for speed. Floor of 4 is bcrypt's minimum."""
    try:
        return max(4, min(int(os.environ.get("BCRYPT_ROUNDS", "12")), 15))
    except ValueError:
        return 12


def gps_stale_after_seconds() -> int:
    """A vehicle with no GPS report for this long is no longer 'live' (default 90 s; agents send a heartbeat every 30 s)."""
    try:
        v = int(os.environ.get("GPS_STALE_AFTER_SECONDS", "90"))
    except ValueError:
        return 90
    return v if v > 0 else 90


def socket_ping_interval() -> int:
    """Seconds between Socket.IO heartbeats; dead connections are dropped after PING_INTERVAL + PING_TIMEOUT."""
    try:
        v = int(os.environ.get("SOCKET_PING_INTERVAL", "25"))
    except ValueError:
        return 25
    return v if v > 0 else 25


def socket_ping_timeout() -> int:
    try:
        v = int(os.environ.get("SOCKET_PING_TIMEOUT", "20"))
    except ValueError:
        return 20
    return v if v > 0 else 20


def gps_min_interval_seconds() -> float:
    """Minimum spacing between accepted location reports from one agent (flood control). 0 disables."""
    try:
        v = float(os.environ.get("GPS_MIN_INTERVAL_SECONDS", "0.5"))
    except ValueError:
        return 0.5
    return v if v >= 0 else 0.5


def gps_sweep_interval_seconds() -> float:
    try:
        v = float(os.environ.get("GPS_SWEEP_INTERVAL_SECONDS", "15"))
    except ValueError:
        return 15.0
    return v if v > 0 else 15.0


def duplicate_window_seconds() -> int:
    """How long an identical shipment-create request (sent WITHOUT an Idempotency-Key) is treated as a duplicate. 0 disables."""
    try:
        return max(0, min(int(os.environ.get("DUPLICATE_WINDOW_SECONDS", "5")), 3600))
    except ValueError:
        return 5


def complaint_draft_ttl_seconds() -> int:
    """How long a customer has to confirm a drafted delivery issue before it expires unfiled."""
    try:
        return max(30, min(int(os.environ.get("COMPLAINT_DRAFT_TTL_SECONDS", "600")), 3600))
    except ValueError:
        return 600


def idempotency_ttl_hours() -> int:
    try:
        return max(1, min(int(os.environ.get("IDEMPOTENCY_TTL_HOURS", "24")), 24 * 14))
    except ValueError:
        return 24


def validate() -> None:
    """Called once at application startup — raises ConfigError (no secret values in the message)."""
    problems = check_environment()
    if problems:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(problems))


def redact_uri(uri: str) -> str:
    """Strips credentials from a connection string so it is safe to log."""
    if not uri:
        return uri
    return re.sub(r"(://)[^/@\s]*@", r"\1", uri)
