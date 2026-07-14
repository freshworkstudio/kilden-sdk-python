"""The frozen wire timestamp: YYYY-MM-DDTHH:MM:SS.mmmZ (SPEC §4.4)."""

from datetime import datetime, timezone
from typing import Optional, Union


def format_instant(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond // 1000:03d}Z"


def now_wire() -> str:
    return format_instant(datetime.now(timezone.utc))


def coerce_timestamp(value: Union[str, datetime, None]) -> Optional[str]:
    """Convert a caller-supplied timestamp to the wire form; None when the
    value cannot be interpreted (the caller drops the event, contract 1)."""
    if value is None:
        return now_wire()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return format_instant(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return format_instant(parsed)
    return None
