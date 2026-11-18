"""Human-readable dates: `24 Nov '26, 19:30` plus a relative hint such as `in 5 days`."""

from __future__ import annotations

import time
from datetime import datetime

MINUTE, HOUR, DAY = 60, 3600, 86400


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def date_label(moment: datetime) -> str:
    """`24 Nov '26, 19:30` in local time."""
    local = moment.astimezone()
    return f"{local.day:02d} {local:%b} '{local:%y}, {local:%H:%M}"


def relative(seconds: float) -> str:
    """`in 5 days`, `in 3 h 12 min`, `in 4 min`, `now`, `2 h ago` ..."""
    future, span = seconds >= 0, abs(seconds)
    if span < MINUTE:
        return "now"
    if span < HOUR:
        text = f"{int(span // MINUTE)} min"
    elif span < DAY:
        hours, minutes = int(span // HOUR), int(span % HOUR // MINUTE)
        text = f"{hours} h {minutes} min" if minutes else f"{hours} h"
    elif span < 2 * DAY:
        text = f"1 day {int(span % DAY // HOUR)} h"
    else:
        text = f"{round(span / DAY)} days"
    return f"in {text}" if future else f"{text} ago"


def when(value: str | None, now: float | None = None) -> str:
    """`24 Nov '26, 19:30 (in 5 days)`; `-` when unknown."""
    moment = _parse(value)
    if moment is None:
        return "-"
    delta = moment.timestamp() - (time.time() if now is None else now)
    return f"{date_label(moment)} ({relative(delta)})"


def ago(value: str | None, now: float | None = None) -> str:
    """Just the relative part, for recent events: `2 min ago`."""
    moment = _parse(value)
    if moment is None:
        return "never"
    return relative(moment.timestamp() - (time.time() if now is None else now))
