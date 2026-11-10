"""Compatibility helpers for Home Assistant device registry entries."""
from __future__ import annotations

from typing import Any


def get_device_config_entry_id(device: Any) -> str | None:
    """Return the owning config entry ID across HA API generations.

    Home Assistant introduced ``config_entry_id`` after the integration's
    current minimum version, while older supported versions still expose
    ``config_entries``. The deprecated fallback is only used when the new
    property is unavailable.
    """
    config_entry_id = getattr(device, "config_entry_id", None)
    if isinstance(config_entry_id, str):
        return config_entry_id

    config_entries = getattr(device, "config_entries", None)
    if config_entries:
        return next(iter(config_entries), None)
    return None
