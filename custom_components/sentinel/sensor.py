"""Sensor platform for HA Sentinel.

Provides a global sensor counting unhealthy items.
"""
from __future__ import annotations

import json

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MAX_PROBLEMS,
    DEFAULT_MAX_PROBLEMS,
    DOMAIN,
    MAX_PROBLEMS_ATTRIBUTE_BYTES,
    SIGNAL_SENTINEL_UPDATE,
)
from .coordinator import SentinelCoordinator
from .entity_base import sentinel_device_info
from .providers import HealthItem


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up global sentinel sensors."""
    coordinator: SentinelCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        SentinelProblemCountSensor(
            coordinator,
            entry.entry_id,
            max_problems=entry.options.get(CONF_MAX_PROBLEMS, DEFAULT_MAX_PROBLEMS),
        ),
    ])


class SentinelProblemCountSensor(SensorEntity):
    """Sensor showing the total number of unhealthy items."""

    _attr_has_entity_name = True
    _attr_name = "Problems"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "problems"
    _attr_icon = "mdi:shield-alert"
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: SentinelCoordinator,
        entry_id: str,
        max_problems: int = DEFAULT_MAX_PROBLEMS,
    ) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._max_problems = max_problems
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_problem_count"

    @property
    def device_info(self) -> DeviceInfo:
        """Group under the Sentinel device."""
        return sentinel_device_info()

    @property
    def native_value(self) -> int:
        """Return the number of problems."""
        return self._coordinator.get_problem_count()

    @property
    def extra_state_attributes(self) -> dict:
        """Return a bounded problem list with the full count and truncation flag."""
        problems = []
        problems_total = 0
        problems_bytes = 2  # JSON list brackets
        size_limit_reached = False
        for item in self._coordinator.get_all_items():
            if item.healthy:
                continue
            problems_total += 1
            if len(problems) >= self._max_problems or size_limit_reached:
                continue
            problem = {
                "id": item.id,
                "name": item.name,
                "provider": item.provider,
                "state": item.state,
                "reason": item.reason,
            }
            # ASCII escaping conservatively bounds UTF-8 JSON, including Unicode.
            problem_bytes = len(json.dumps(problem).encode("utf-8"))
            separator_bytes = 2 if problems else 0
            if problems_bytes + separator_bytes + problem_bytes > MAX_PROBLEMS_ATTRIBUTE_BYTES:
                size_limit_reached = True
                continue
            problems.append(problem)
            problems_bytes += separator_bytes + problem_bytes

        return {
            "problems": problems,
            "problems_total": problems_total,
            "problems_truncated": len(problems) < problems_total,
        }

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
