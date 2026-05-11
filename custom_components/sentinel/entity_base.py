"""Shared helpers for HA Sentinel entities."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, NAME


def sentinel_device_info() -> DeviceInfo:
    """Return DeviceInfo grouping all Sentinel entities under a single device."""
    return DeviceInfo(
        identifiers={(DOMAIN, "sentinel_main")},
        name=NAME,
        manufacturer="GuiPoM",
        model="Sentinel",
    )
