"""Presentation-only data age. No network calls or vehicle-state inference."""

from datetime import datetime, timedelta


def data_age(timestamp: datetime | None, now: datetime) -> float | None:
    """Return age of a trustworthy timestamp, not time since a value changed.

    Missing, naive, pre-2000 sentinel and future timestamps are unknown. Do not
    guess a timezone or interpret an invalid timestamp as fresh vehicle data.
    """
    if not isinstance(timestamp, datetime):
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    if timestamp.year < 2000 or now.tzinfo is None:
        return None
    seconds = (now - timestamp).total_seconds()
    return seconds if seconds >= 0 else None


def freshness_state(
    age: float | None, polling_enabled: bool, interval: timedelta
) -> str | None:
    """Describe age against two effective intervals, with a five-minute floor.

    Stale means old data, NOT an offline/faulty vehicle. Paused is intentional;
    neither paused nor unknown should be treated as confirmed fresh in automations.
    """
    if not polling_enabled:
        return "paused"
    if age is None:
        return None
    return "fresh" if age <= max(300, 2 * interval.total_seconds()) else "stale"
