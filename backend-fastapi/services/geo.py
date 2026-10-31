"""Shipora only serves Bengaluru. One bounding box (BBMP limits plus the airport and the Electronic City / Whitefield
edges) is the single source of truth; the frontend maps are locked to the same box (frontend/src/lib/shipora.js)."""

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
