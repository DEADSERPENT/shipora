from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import HTTPException, Request

import config


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=config.bcrypt_rounds())).decode()


def compare_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _secret() -> str:
    # No fallback: a missing secret must never silently become a guessable one.
    if not config.JWT_SECRET:
        raise config.ConfigError("JWT_SECRET is not configured")
    return config.JWT_SECRET


def sign_token(payload: dict) -> str:
    to_encode = {**payload, "exp": datetime.now(timezone.utc) + timedelta(days=7)}
    return jwt.encode(to_encode, _secret(), algorithm="HS256")


def verify_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=["HS256"])


async def get_current_user(request: Request) -> dict:
    """Mirrors middleware/auth.js: reads Bearer token, verifies it, and
    returns the decoded payload (used as req.user in the Node backend)."""
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No token provided")

    token = auth_header.split(" ", 1)[1]
    try:
        return verify_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_optional_user(request: Request) -> Optional[dict]:
    """Non-throwing variant of get_current_user — returns None instead of
    401ing, so public endpoints (chat/voice) can still pick up a Bearer
    token from logged-in visitors without requiring auth for anonymous ones."""
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    try:
        return verify_token(auth_header.split(" ", 1)[1])
    except jwt.PyJWTError:
        return None


def require_role(role: str, message: str = "Access denied"):
    async def _dependency(request: Request) -> dict:
        user = await get_current_user(request)
        if user.get("role") != role:
            raise HTTPException(status_code=403, detail=message)
        return user

    return _dependency
