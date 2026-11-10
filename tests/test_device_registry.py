"""Tests for device registry API compatibility."""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.sentinel.device_registry import get_device_config_entry_id


def test_uses_current_config_entry_id() -> None:
    """Prefer the current single-owner property when available."""
    device = SimpleNamespace(config_entry_id="current", config_entries={"legacy"})

    assert get_device_config_entry_id(device) == "current"


def test_falls_back_to_legacy_config_entries() -> None:
    """Support HA versions before config_entry_id was introduced."""
    device = SimpleNamespace(config_entries={"legacy"})

    assert get_device_config_entry_id(device) == "legacy"


def test_returns_none_without_config_entry() -> None:
    """Devices without an owning config entry remain supported."""
    device = SimpleNamespace(config_entry_id=None, config_entries=set())

    assert get_device_config_entry_id(device) is None
