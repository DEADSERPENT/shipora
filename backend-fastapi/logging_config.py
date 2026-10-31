"""Structured logging for Shipora.

* One JSON object per line in production (`LOG_FORMAT=json`, the default when APP_ENV=production), a readable
  one-liner in development (`LOG_FORMAT=text`). `LOG_LEVEL` controls verbosity.
* Every record carries a `request_id` (also returned to clients as `X-Request-ID`) so one request can be followed
  across the HTTP access line and the business events it caused.
* Secrets can't be logged by accident: every message, extra field and traceback goes through `redact()`, which
  masks bearer tokens/JWTs, credentials inside connection strings, API keys and `password=`/`token=`-style pairs.
  Beyond that, the code simply never logs request bodies, passwords, tokens, e-mail addresses or chat text.
"""
import contextvars
import json
import logging
import os
import re
import sys
import traceback
from datetime import datetime, timezone

request_id_var: contextvars.ContextVar = contextvars.ContextVar("request_id", default=None)

_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}

_REDACTIONS = [
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]+"), "Bearer [REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}"), "[REDACTED-JWT]"),
    (re.compile(r"(mongodb(?:\+srv)?://)[^/@\s]+@"), r"\1[REDACTED]@"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "[REDACTED-API-KEY]"),
    # key=value / key: value / "key": "value" for sensitive key names
    (re.compile(r"(?i)([\"']?(?:password|passwd|pwd|secret|token|api[_\-]?key|authorization)[\"']?\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&}]+)"),
     r"\1[REDACTED]"),
]


def redact(text: str) -> str:
    if not isinstance(text, str):
        return text
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


def log_format() -> str:
    explicit = (os.environ.get("LOG_FORMAT") or "").strip().lower()
    if explicit in ("json", "text"):
        return explicit
    return "json" if (os.environ.get("APP_ENV") or "").strip().lower() == "production" else "text"


def log_level() -> int:
    name = (os.environ.get("LOG_LEVEL") or "INFO").strip().upper()
    level = logging.getLevelName(name)
    return level if isinstance(level, int) else logging.INFO


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            rid = request_id_var.get()
            if rid:
                record.request_id = rid
        return True


def _extras(record: logging.LogRecord) -> dict:
    out = {}
    for k, v in record.__dict__.items():
        if k in _STANDARD_ATTRS or k.startswith("_"):
            continue
        out[k] = redact(v) if isinstance(v, str) else (v if isinstance(v, (int, float, bool)) or v is None else redact(str(v)))
    return out


def _exception(record: logging.LogRecord) -> dict:
    if not record.exc_info or not record.exc_info[0]:
        return {}
    return {"error_type": record.exc_info[0].__name__,
            "exception": redact("".join(traceback.format_exception(*record.exc_info)))}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        data.update(_extras(record))
        data.update(_exception(record))
        return json.dumps(data, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        extras = " ".join(f"{k}={v}" for k, v in _extras(record).items())
        line = f"{ts} {record.levelname:<7} {record.name}: {redact(record.getMessage())}" + (f"  [{extras}]" if extras else "")
        exc = _exception(record)
        return line + (("\n" + exc["exception"]) if exc else "")


_HANDLER_FLAG = "_shipora_handler"


def setup_logging() -> None:
    """Idempotent: installs (or refreshes) a single stdout handler on the root logger."""
    root = logging.getLogger()
    handler = next((h for h in root.handlers if getattr(h, _HANDLER_FLAG, False)), None)
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        setattr(handler, _HANDLER_FLAG, True)
        handler.addFilter(RequestContextFilter())
        root.addHandler(handler)
    handler.setFormatter(JsonFormatter() if log_format() == "json" else TextFormatter())
    root.setLevel(log_level())
    for noisy in ("pymongo", "engineio", "socketio", "httpx", "httpcore", "asyncio", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
