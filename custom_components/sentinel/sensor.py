"""Sensor platform for HA Sentinel.

Provides a global sensor counting unhealthy items,
and a sensor listing intentionally ignored/excluded items.
"""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.hassio import is_hassio

from .const import (
    CONF_EXCLUDED_ENTRIES,
    CONF_IGNORED_ADDON_SLUGS,
    CONF_IGNORED_DEVICE_IDS,
    CONF_IGNORED_DEVICE_SOURCES,
    DOMAIN,
    SIGNAL_SENTINEL_UPDATE,
)
from .coordinator import SentinelCoordinator
from .entity_base import sentinel_device_info
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
        SentinelIgnoredItemsSensor(hass, entry),
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
        return sentinel_device_info()

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


class SentinelIgnoredItemsSensor(SensorEntity):
    """Sensor listing intentionally ignored/excluded items across all providers.

    Exposes the sentinel_data_type="ignored_items" attribute so the Lovelace
    card can locate this entity without relying on a hardcoded entity_id.
    """

    _attr_has_entity_name = True
    _attr_name = "Ignored Items"
    _attr_icon = "mdi:eye-off"
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "items"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_ignored_items"
        self._addon_names: dict[str, str] = {}

    @property
    def device_info(self) -> DeviceInfo:
        return sentinel_device_info()

    @property
    def native_value(self) -> int:
        opts = self._entry.options
        return (
            len(opts.get(CONF_EXCLUDED_ENTRIES, []))
            + len(opts.get(CONF_IGNORED_DEVICE_SOURCES, []))
            + len(opts.get(CONF_IGNORED_DEVICE_IDS, []))
            + len(opts.get(CONF_IGNORED_ADDON_SLUGS, []))
        )

    @property
    def extra_state_attributes(self) -> dict:
        opts = self._entry.options

        excluded_integrations = []
        for entry_id in opts.get(CONF_EXCLUDED_ENTRIES, []):
            ce = self.hass.config_entries.async_get_entry(entry_id)
            if ce:
                excluded_integrations.append({"name": ce.title, "domain": ce.domain})
            else:
                excluded_integrations.append({"name": entry_id, "domain": "?"})

        dev_reg = dr.async_get(self.hass)
        ignored_devices = []
        for device_id in opts.get(CONF_IGNORED_DEVICE_IDS, []):
            device = dev_reg.async_get(device_id)
            name = (device.name_by_user or device.name or device_id) if device else device_id
            ignored_devices.append({"name": name})

        ignored_addons = [
            {"slug": slug, "name": self._addon_names.get(slug, slug)}
            for slug in opts.get(CONF_IGNORED_ADDON_SLUGS, [])
        ]

        return {
            "sentinel_data_type": "ignored_items",
            "excluded_integrations": excluded_integrations,
            "ignored_device_sources": list(opts.get(CONF_IGNORED_DEVICE_SOURCES, [])),
            "ignored_devices": ignored_devices,
            "ignored_addons": ignored_addons,
        }

    async def async_added_to_hass(self) -> None:
        await self._async_fetch_addon_names()
        self.async_on_remove(
            self._entry.add_update_listener(self._handle_options_update)
        )

    async def _handle_options_update(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        await self._async_fetch_addon_names()
        self.async_write_ha_state()

    async def _async_fetch_addon_names(self) -> None:
        """Cache add-on names from the Supervisor so the property can resolve slugs synchronously."""
        if not is_hassio(self.hass):
            return
        try:
            from homeassistant.components.hassio import get_supervisor_client  # noqa: PLC0415
            client = get_supervisor_client(self.hass)
            addons = await client.addons.list()
            for addon in addons:
                slug = addon.slug if hasattr(addon, "slug") else addon.get("slug", "")
                name = addon.name if hasattr(addon, "name") else addon.get("name", slug)
                if slug:
                    self._addon_names[slug] = name or slug
        except Exception:
            pass
