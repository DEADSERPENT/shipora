"""Shared input-validation types so every endpoint applies the same bounds."""
import re
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

SHIPMENT_REF_RE = re.compile(r"^SHP(?:[0-9]{8}|[0-9A-F]{10})$")   # current: SHP + 8 digits; legacy: SHP + 10 hex
OBJECT_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
PHONE_PATTERN = r"^\+?[0-9][0-9\s\-]{6,18}$"


def _email(v: str) -> str:
    v = v.strip()
    if len(v) > 254 or not EMAIL_RE.match(v):
        raise ValueError("must be a valid email address")
    return v


def _password(v: str) -> str:
    if len(v) < 6:
        raise ValueError("must be at least 6 characters")
    if len(v.encode("utf-8")) > 72:  # bcrypt only uses the first 72 bytes
        raise ValueError("must be at most 72 bytes")
    return v


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Address = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
OptionalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, pattern=PHONE_PATTERN)]
Email = Annotated[str, AfterValidator(_email)]
Password = Annotated[str, AfterValidator(_password)]
TrackingRef = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=SHIPMENT_REF_RE.pattern)]


def is_object_id(value: str) -> bool:
    return bool(value) and bool(OBJECT_ID_RE.match(value))
