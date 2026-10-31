from datetime import datetime
from typing import Optional

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def js_date_string(dt: datetime) -> str:
    """Replicates JavaScript's Date.prototype.toDateString(), e.g. "Wed Jul 3 2026".
    Uses fixed lookup tables instead of strftime to stay locale-independent."""
    return f"{_WEEKDAYS[dt.weekday()]} {_MONTHS[dt.month - 1]} {dt.day} {dt.year}"


_WEEKDAYS_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTHS_LONG = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def friendly_date(dt: Optional[datetime]) -> Optional[str]:
    """Customer-facing wording of a date, e.g. "Monday, 12 October 2026" (date only: the time-of-day on an
    estimated delivery is an artefact of when the shipment was created, so quoting it would be false precision).
    Locale-independent. None -> None. Used for tool results so the assistant never has to do date arithmetic."""
    if dt is None:
        return None
    return f"{_WEEKDAYS_LONG[dt.weekday()]}, {dt.day} {_MONTHS_LONG[dt.month - 1]} {dt.year}"


def today_string() -> str:
    return js_date_string(datetime.now())
