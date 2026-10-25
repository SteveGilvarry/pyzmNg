"""Turn the time strings ``ZMClient.events()`` accepts into ZM timestamps."""

from __future__ import annotations

import calendar
import logging
import re
from datetime import datetime, timedelta

logger = logging.getLogger("pyzm")

_ZM_FORMAT = "%Y-%m-%d %H:%M:%S"
# Unit spellings dateparser accepts in "N <unit> ago", mapped to one name.
_UNITS = {
    **dict.fromkeys(("s", "sec", "secs", "second", "seconds"), "seconds"),
    **dict.fromkeys(("min", "mins", "minute", "minutes"), "minutes"),
    **dict.fromkeys(("h", "hr", "hrs", "hour", "hours"), "hours"),
    **dict.fromkeys(("d", "day", "days"), "days"),
    **dict.fromkeys(("w", "wk", "wks", "week", "weeks"), "weeks"),
    **dict.fromkeys(("month", "months"), "months"),
    **dict.fromkeys(("y", "yr", "yrs", "year", "years"), "years"),
}
_AGO_RE = re.compile(r"^(\d+|an?)\s*([a-z]+)\s+ago$", re.IGNORECASE)
_LAST_RE = re.compile(r"^last\s+(week|month|year)$", re.IGNORECASE)


def parse_human_time(time_str: str) -> str:
    """Return *time_str* as a local ``YYYY-MM-DD HH:MM:SS``, or unchanged.

    Uses dateparser when it's installed (``pyzm[dates]``).  Without it,
    handles ``"N <unit> ago"`` (seconds to years, with dateparser's
    abbreviations such as ``min``, ``hrs``, ``d``, and ``a``/``an`` for 1),
    ``"last week/month/year"``, ``"now"``, ``"today"``, ``"yesterday"`` and
    ISO timestamps, with dateparser's meaning for each.

    A string neither can parse is returned unchanged, with a warning: ZM
    ignores a filter it can't read, so the query isn't limited by it.
    """
    try:
        import dateparser
    except ImportError:
        dt = _parse_common(time_str.strip())
    else:
        dt = dateparser.parse(time_str)
    if dt:
        return dt.strftime(_ZM_FORMAT)
    logger.warning(
        "Can't parse time %r; ZoneMinder ignores the filter, so events from any "
        "time are returned", time_str,
    )
    return time_str


def _parse_common(text: str) -> datetime | None:
    now = datetime.now()
    word = text.lower()
    if word in ("now", "today"):
        return now
    if word == "yesterday":
        return now - timedelta(days=1)
    if m := _LAST_RE.match(text):
        return _back(now, 1, m.group(1).lower() + "s")
    if (m := _AGO_RE.match(text)) and m.group(2).lower() in _UNITS:
        count = 1 if m.group(1).lower() in ("a", "an") else int(m.group(1))
        return _back(now, count, _UNITS[m.group(2).lower()])
    try:
        # Python 3.10's fromisoformat doesn't accept a trailing Z
        return datetime.fromisoformat(re.sub(r"Z$", "+00:00", text))
    except ValueError:
        return None


def _back(now: datetime, count: int, unit: str) -> datetime:
    if unit in ("months", "years"):
        return _months_back(now, count * 12 if unit == "years" else count)
    return now - timedelta(**{unit: count})


def _months_back(dt: datetime, months: int) -> datetime:
    """Step back whole calendar months, clamping the day (Mar 31 -> Feb 28)."""
    year, month = divmod(dt.year * 12 + dt.month - 1 - months, 12)
    month += 1
    return dt.replace(year=year, month=month, day=min(dt.day, calendar.monthrange(year, month)[1]))
