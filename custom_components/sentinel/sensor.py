"""Sensor platform for HA Sentinel.

Provides a global sensor counting unhealthy items.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.json import json_bytes

from .const import DOMAIN, MAX_PROBLEMS_ATTRIBUTE_BYTES, SIGNAL_SENTINEL_UPDATE
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
        SentinelProblemCountSensor(coordinator, entry.entry_id),
    ])


def _fits(attributes: dict, problem: dict) -> bool:
    """Return whether adding a problem stays within the attribute budget."""
    attributes["problems"].append(problem)
    fits = len(json_bytes(attributes)) <= MAX_PROBLEMS_ATTRIBUTE_BYTES
    attributes["problems"].pop()
    return fits


def _fit_truncated_reason(attributes: dict, problem: dict, reason: str) -> dict | None:
    """Return the longest fitting reason prefix, or None if no entry fits."""
    suffix = "…"
    low = 0
    high = len(reason)
    best: dict | None = None

    while low <= high:
        length = (low + high) // 2
        candidate = {
            **problem,
            "reason": reason[:length] + suffix,
            "reason_truncated": True,
        }
        if _fits(attributes, candidate):
            best = candidate
            low = length + 1
        else:
            high = length - 1

    return best


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
        return sentinel_device_info()

    @property
    def native_value(self) -> int:
        """Return the number of problems."""
        return self._coordinator.get_problem_count()

    @property
    def extra_state_attributes(self) -> dict:
        """Return all problems that fit in the Recorder-safe attribute budget."""
        unhealthy = [
            item for item in self._coordinator.get_all_items() if not item.healthy
        ]
        problems: list[dict] = []
        attributes = {
            "problems": problems,
            "problems_total": len(unhealthy),
            "problems_truncated": False,
        }

        for item in unhealthy:
            problem = {
                "id": item.id,
                "name": item.name,
                "provider": item.provider,
                "state": item.state,
                "reason": item.reason,
            }
            if _fits(attributes, problem):
                problems.append(problem)
                continue

            reason = item.reason
            if reason is not None:
                truncated = _fit_truncated_reason(attributes, problem, reason)
                if truncated is not None:
                    problems.append(truncated)
                    continue

            attributes["problems_truncated"] = True
            break

        attributes["problems_truncated"] = len(problems) < len(unhealthy)
        return attributes

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
