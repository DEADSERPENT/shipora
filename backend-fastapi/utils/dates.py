from datetime import datetime

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def js_date_string(dt: datetime) -> str:
    """Replicates JavaScript's Date.prototype.toDateString(), e.g. "Wed Jul 3 2026".
    Uses fixed lookup tables instead of strftime to stay locale-independent."""
    return f"{_WEEKDAYS[dt.weekday()]} {_MONTHS[dt.month - 1]} {dt.day} {dt.year}"


def today_string() -> str:
    return js_date_string(datetime.now())
