"""Binary sensor platform for HA Sentinel.

Creates one binary_sensor per monitored item.
device_class=PROBLEM: on=problem detected, off=OK.
"""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NAME, SIGNAL_SENTINEL_UPDATE
from .coordinator import SentinelCoordinator
from .providers import HealthItem

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors for all monitored items."""
    coordinator: SentinelCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Create entities for all currently known items
    entities = [
        SentinelBinarySensor(coordinator, item)
        for item in coordinator.get_all_items()
    ]
    async_add_entities(entities)

    # Listen for new items being added dynamically
    known_ids: set[str] = {e.unique_id for e in entities}

    @callback
    def _handle_update(item: HealthItem) -> None:
        """Add entity for newly discovered items."""
        uid = f"{DOMAIN}_{item.id}"
        if uid not in known_ids:
            known_ids.add(uid)
            async_add_entities([SentinelBinarySensor(coordinator, item)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_SENTINEL_UPDATE, _handle_update)
    )


class SentinelBinarySensor(BinarySensorEntity):
    """Binary sensor representing the health of one monitored item.

    is_on=True  → problem detected
    is_on=False → healthy / OK
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: SentinelCoordinator, item: HealthItem) -> None:
        """Initialize the binary sensor."""
        self._coordinator = coordinator
        self._item = item
        self._attr_unique_id = f"{DOMAIN}_{item.id}"
        self._attr_name = item.name

    @property
    def device_info(self) -> DeviceInfo:
        """Group all entities under a single HA Sentinel device."""
        return DeviceInfo(
            identifiers={(DOMAIN, "ha_sentinel_main")},
            name=NAME,
            manufacturer="GuiPoM",
            model="HA Sentinel",
        )

    @property
    def is_on(self) -> bool:
        """Return True if a problem is detected."""
        return not self._item.healthy

    @property
    def extra_state_attributes(self) -> dict:
        """Return detailed attributes."""
        attrs = {
            "provider": self._item.provider,
            "state": self._item.state,
            "since": self._item.since.isoformat(),
            "failure_count": self._item.failure_count,
            "can_reload": self._item.can_reload,
        }
        if self._item.reason:
            attrs["reason"] = self._item.reason
        attrs.update(self._item.extra)
        return attrs

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates when entity is added."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SENTINEL_UPDATE,
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self, item: HealthItem) -> None:
        """Handle update signal — only react to our own item."""
        if item.id == self._item.id:
            self._item = item
            self.async_write_ha_state()
