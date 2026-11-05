import hashlib
import logging
import math
import os
import time
from collections import deque
from typing import Callable, Dict, Optional, Tuple

from fastapi import HTTPException, Request

log = logging.getLogger("shipora.ratelimit")

# bucket -> (max requests, window seconds)
DEFAULT_LIMITS: Dict[str, Tuple[int, float]] = {
    "login": (20, 60.0),            # per client address
    "login_account": (8, 300.0),    # failed attempts against one account, from anywhere
    "register": (10, 3600.0),
    "password_reset": (5, 900.0),
    "track": (120, 60.0),           # public tracking lookups
    "chat": (30, 60.0),             # AI assistant (per user, or per address when anonymous)
    "speak": (30, 60.0),            # read-aloud of a reply (text-to-speech only)
    "voice": (12, 60.0),            # STT + LLM + TTS is the most expensive call we have
    "shipment_create": (30, 60.0),
}


def parse_spec(spec: Optional[str]) -> Optional[Tuple[int, float]]:
    try:
        count, seconds = (spec or "").split("/")
        count, seconds = int(count.strip()), float(seconds.strip())
    except (ValueError, AttributeError):
        return None
    return (count, seconds) if count > 0 and seconds > 0 else None


def enabled() -> bool:
    return os.environ.get("RATE_LIMIT_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def limit_for(bucket: str) -> Tuple[int, float]:
    return parse_spec(os.environ.get(f"RATE_LIMIT_{bucket.upper()}")) or DEFAULT_LIMITS[bucket]


class SlidingWindowLimiter:
    def __init__(self):
        self.clock: Callable[[], float] = time.monotonic
        self._hits: Dict[Tuple[str, str], Tuple[deque, float]] = {}
        self._ops = 0

    @staticmethod
    def _key(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()[:20]   # raw emails/addresses are never kept in memory

    def _window(self, bucket: str, key: str, window: float) -> deque:
        now = self.clock()
        entry = self._hits.get((bucket, key))
        if entry is None:
            dq = deque()
            self._hits[(bucket, key)] = (dq, window)
        else:
            dq = entry[0]
        while dq and dq[0] <= now - window:
            dq.popleft()
        return dq

    def peek(self, bucket: str, key: str, limit: int, window: float) -> Tuple[bool, float]:
        """Is another request allowed right now? Does not record anything."""
        k = self._key(key)
        dq = self._window(bucket, k, window)
        if len(dq) < limit:
            return True, 0.0
        return False, max(dq[0] + window - self.clock(), 0.0)

    def record(self, bucket: str, key: str, window: float) -> None:
        k = self._key(key)
        self._window(bucket, k, window).append(self.clock())

    def hit(self, bucket: str, key: str, limit: int, window: float) -> Tuple[bool, float]:
        allowed, retry = self.peek(bucket, key, limit, window)
        if allowed:
            self.record(bucket, key, window)
        self._ops += 1
        if self._ops % 500 == 0:
            self.purge()
        return allowed, retry

    def purge(self) -> None:
        now = self.clock()
        for k in [k for k, (dq, w) in self._hits.items() if not dq or dq[-1] <= now - w]:
            del self._hits[k]

    def size(self) -> int:
        return len(self._hits)

    def reset(self) -> None:
        self._hits.clear()
        self._ops = 0


limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    if os.environ.get("TRUST_PROXY_HEADERS", "").strip().lower() in ("1", "true", "yes"):
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def actor_key(request: Request) -> str:
    """Signed-in users are limited as themselves; everyone else by address."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            from auth_utils import verify_token
            uid = verify_token(auth.split(" ", 1)[1]).get("id")
            if uid:
                return f"user:{uid}"
        except Exception:
            pass
    return f"ip:{client_ip(request)}"


def _too_many(bucket: str, retry_after: float, limit: int, window: float, who: str) -> HTTPException:
    secs = max(1, math.ceil(retry_after))
    # the key may be an e-mail address: log only which bucket tripped and what kind of actor it was
    log.warning("rate limit exceeded", extra={"event": "rate_limited", "bucket": bucket, "actor": who.split(":", 1)[0], "retry_after": secs})
    return HTTPException(status_code=429, detail=f"Too many requests — please wait {secs} seconds and try again.",
                         headers={"Retry-After": str(secs), "X-RateLimit-Limit": str(limit)})


def enforce(request: Request, bucket: str, key: Optional[str] = None, by: str = "ip") -> None:
    if not enabled():
        return
    who = key or (actor_key(request) if by == "actor" else f"ip:{client_ip(request)}")
    limit, window = limit_for(bucket)
    allowed, retry = limiter.hit(bucket, who, limit, window)
    if not allowed:
        raise _too_many(bucket, retry, limit, window, who)


def check_account(request: Request, email: str) -> None:
    """Refuses a login attempt if the account has had too many recent FAILED attempts (from any address)."""
    if not enabled():
        return
    limit, window = limit_for("login_account")
    allowed, retry = limiter.peek("login_account", email.lower(), limit, window)
    if not allowed:
        raise _too_many("login_account", retry, limit, window, "account")


def record_failed_login(email: str) -> None:
    if enabled():
        limiter.record("login_account", email.lower(), limit_for("login_account")[1])


def limited(bucket: str, by: str = "ip"):
    """FastAPI dependency: `dependencies=[Depends(limited("track"))]`."""
    async def dependency(request: Request) -> None:
        enforce(request, bucket, by=by)
    return dependency
