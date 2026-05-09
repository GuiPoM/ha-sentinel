"""Sensor platform for HA Sentinel.

Provides a global sensor counting unhealthy items.
"""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity, SensorStateClass
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
    """Set up global sentinel sensors."""
    coordinator: SentinelCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        SentinelProblemCountSensor(coordinator, entry.entry_id),
    ])


class SentinelProblemCountSensor(SensorEntity):
    """Sensor showing the total number of unhealthy items."""

    _attr_has_entity_name = True
    _attr_name = "Problems"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "problems"
    _attr_icon = "mdi:shield-alert"
    _attr_should_poll = False

    def __init__(self, coordinator: SentinelCoordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_problem_count"

    @property
    def device_info(self) -> DeviceInfo:
        """Group under the Sentinel device."""
        return DeviceInfo(
            identifiers={(DOMAIN, "sentinel_main")},
            name=NAME,
            manufacturer="GuiPoM",
            model="Sentinel",
        )

    @property
    def native_value(self) -> int:
        """Return the number of problems."""
        return self._coordinator.get_problem_count()

    @property
    def extra_state_attributes(self) -> dict:
        """Return list of unhealthy items."""
        problems = [
            {
                "id": item.id,
                "name": item.name,
                "provider": item.provider,
                "state": item.state,
                "reason": item.reason,
            }
            for item in self._coordinator.get_all_items()
            if not item.healthy
        ]
        return {"problems": problems}

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SENTINEL_UPDATE,
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self, item: HealthItem) -> None:
        """Any change can affect the count — always refresh."""
        self.async_write_ha_state()
