"""Shared helpers for HA Sentinel entities."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
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


def device_subentry_device_info(hass: HomeAssistant, device_id: str) -> DeviceInfo:
    """Return DeviceInfo linking a Sentinel entity to its source HA device.

    The entity appears directly in the device page of the monitored physical
    device, rather than under the "Sentinel" virtual device.
    """
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get(device_id)
    # Use the source device's own identifiers so HA links us to the same device entry.
    # Fall back to a Sentinel-namespaced identifier if the device is unknown.
    identifiers = device.identifiers if device else {(DOMAIN, device_id)}
    return DeviceInfo(identifiers=identifiers)
