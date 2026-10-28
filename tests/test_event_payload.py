"""Pure tests for Sentinel's public event payload."""
from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
from pathlib import Path
from types import SimpleNamespace


_MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "sentinel" / "event_payload.py"
_SPEC = importlib.util.spec_from_file_location("event_payload", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_public_payload_contract_remains_stable() -> None:
    """Keep event field names, types, meanings, and serialization stable."""
    item = SimpleNamespace(
        id="item-1",
        provider="devices",
        name="Lamp",
        healthy=False,
        state="unavailable",
        severity="error",
        reason="Offline",
        failure_count=2,
        since=datetime(2026, 10, 28, tzinfo=UTC),
        extra={"domain": "light", "source": "hue"},
    )

    payload = _MODULE.build_item_changed_payload(item)

    assert set(payload) == {
        "item_id", "provider", "name", "domain", "source", "item_type",
        "healthy", "state", "severity", "reason", "failure_count", "since",
    }
    assert payload == {
        "item_id": "item-1",
        "provider": "devices",
        "name": "Lamp",
        "domain": "light",
        "source": "hue",
        "item_type": "device",
        "healthy": False,
        "state": "unavailable",
        "severity": "error",
        "reason": "Offline",
        "failure_count": 2,
        "since": "2026-10-28T00:00:00+00:00",
    }
