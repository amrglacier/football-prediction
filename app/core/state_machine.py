"""State machine utilities for match lifecycle management."""

from datetime import datetime, date, time
from typing import Optional

import pytz

from app.core.constants import (
    MatchStatus,
    STATE_TRANSITIONS,
    WEEKDAY_CUTOFF_HOUR,
    WEEKEND_CUTOFF_HOUR,
)


def is_valid_transition(current: MatchStatus, target: MatchStatus) -> bool:
    """Check whether a state transition is valid."""
    allowed = STATE_TRANSITIONS.get(current, [])
    return target in allowed


def get_cutoff_time(match_date: date, tz_name: str = "Asia/Shanghai") -> datetime:
    """
    Calculate the cutoff (封盘) time based on match date.

    - Weekday (Mon-Fri): 22:00
    - Weekend (Sat-Sun) / holidays: 23:00
    """
    tz = pytz.timezone(tz_name)
    weekday = match_date.weekday()  # Mon=0 ... Sun=6

    if weekday >= 5:  # Saturday or Sunday
        hour = WEEKEND_CUTOFF_HOUR
    else:
        hour = WEEKDAY_CUTOFF_HOUR

    # Handle holiday logic: treat as weekend (23:00)
    # For simplicity, holidays can be configured externally; default to weekend rules
    # TODO: integrate a holiday calendar if needed

    cutoff = datetime.combine(match_date, time(hour=hour, minute=0, second=0))
    return tz.localize(cutoff)


def is_locked(match_date: date, now: Optional[datetime] = None,
              tz_name: str = "Asia/Shanghai") -> bool:
    """Check if a match is past its cutoff time (locked)."""
    if now is None:
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)

    cutoff = get_cutoff_time(match_date, tz_name)
    return now >= cutoff


def can_predict(match_date: date, now: Optional[datetime] = None,
                tz_name: str = "Asia/Shanghai") -> bool:
    """Check if predictions can still be generated for a match."""
    return not is_locked(match_date, now, tz_name)
