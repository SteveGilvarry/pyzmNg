"""Turn the time strings ``ZMClient.events()`` accepts into ZM timestamps."""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta

_ZM_FORMAT = "%Y-%m-%d %H:%M:%S"
_AGO_RE = re.compile(
    r"^(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago$", re.IGNORECASE,
)


def parse_human_time(time_str: str) -> str:
    """Return *time_str* as a local ``YYYY-MM-DD HH:MM:SS``, or unchanged.

    Uses dateparser when it's installed (``pyzm[dates]``).  Without it,
    handles ``"N <unit>s ago"`` (seconds to years), ``"now"``, ``"today"``,
    ``"yesterday"`` and ISO timestamps, with dateparser's meaning for each.
    Anything else goes to ZM unchanged.
    """
    try:
        import dateparser
    except ImportError:
        dt = _parse_common(time_str.strip())
    else:
        dt = dateparser.parse(time_str)
    return dt.strftime(_ZM_FORMAT) if dt else time_str


def _parse_common(text: str) -> datetime | None:
    now = datetime.now()
    word = text.lower()
    if word in ("now", "today"):
        return now
    if word == "yesterday":
        return now - timedelta(days=1)
    m = _AGO_RE.match(text)
    if m:
        count, unit = int(m.group(1)), m.group(2).lower()
        if unit in ("month", "year"):
            return _months_back(now, count * 12 if unit == "year" else count)
        return now - timedelta(**{unit + "s": count})
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _months_back(dt: datetime, months: int) -> datetime:
    """Step back whole calendar months, clamping the day (Mar 31 -> Feb 28)."""
    year, month = divmod(dt.year * 12 + dt.month - 1 - months, 12)
    month += 1
    return dt.replace(year=year, month=month, day=min(dt.day, calendar.monthrange(year, month)[1]))
