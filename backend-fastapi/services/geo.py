"""Shipora only serves Bengaluru. One bounding box (BBMP limits plus the airport and the Electronic City / Whitefield
edges) is the single source of truth; the frontend maps are locked to the same box (frontend/src/lib/shipora.js)."""

import math
from typing import Optional

SOUTH, NORTH = 12.70, 13.25
WEST, EAST = 77.35, 77.85
CENTER = (12.9716, 77.5946)
OUTSIDE_MESSAGE = "Shipora delivers within Bengaluru only — please choose a {what} inside Bengaluru."


def in_bengaluru(lat: float, lng: float) -> bool:
    return SOUTH <= lat <= NORTH and WEST <= lng <= EAST


def outside_reason(location, what: str) -> Optional[str]:
    """None when `location` (a Location or None) is inside Bengaluru; otherwise the customer-facing error."""
    if location is not None and not in_bengaluru(location.lat, location.lng):
        return OUTSIDE_MESSAGE.format(what=what)
    return None


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))
