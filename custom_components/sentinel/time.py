"""Time helpers used by Sentinel's provider model."""
from __future__ import annotations

from datetime import UTC, datetime


def sentinel_now() -> datetime:
    """Return the current timezone-aware UTC timestamp used by Sentinel."""
    return datetime.now(UTC)
