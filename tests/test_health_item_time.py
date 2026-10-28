"""Tests for the common Sentinel timestamp convention."""
from __future__ import annotations

from datetime import timedelta
import importlib.util
from pathlib import Path


_MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "sentinel" / "time.py"
_SPEC = importlib.util.spec_from_file_location("sentinel_time", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_sentinel_now_is_timezone_aware_utc() -> None:
    """Sentinel's common timestamp helper returns timezone-aware UTC."""
    timestamp = _MODULE.sentinel_now()

    assert timestamp.tzinfo is not None
    assert timestamp.utcoffset() == timedelta(0)
