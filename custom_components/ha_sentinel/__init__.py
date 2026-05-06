"""HA Sentinel — proactive health monitoring for Home Assistant."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import SentinelCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "sensor"]

# Service schemas
SERVICE_RELOAD = "reload"
SERVICE_RELOAD_SCHEMA = vol.Schema(
    {vol.Required("item_id"): cv.string}
)

SERVICE_RESET_FAILURE_COUNT = "reset_failure_count"
SERVICE_RESET_FAILURE_COUNT_SCHEMA = vol.Schema(
    {vol.Required("item_id"): cv.string}
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA Sentinel from a config entry."""
    config = {**entry.data, **entry.options}

    coordinator = SentinelCoordinator(hass, config)
    await coordinator.async_setup()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def handle_reload(call: ServiceCall) -> None:
        item_id = call.data["item_id"]
        await coordinator.async_reload_item(item_id)

    async def handle_reset_failure_count(call: ServiceCall) -> None:
        item_id = call.data["item_id"]
        await coordinator.async_reset_failure_count(item_id)

    hass.services.async_register(
        DOMAIN, SERVICE_RELOAD, handle_reload, schema=SERVICE_RELOAD_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_FAILURE_COUNT,
        handle_reset_failure_count,
        schema=SERVICE_RESET_FAILURE_COUNT_SCHEMA,
    )

    # Re-apply config when options are updated
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    _LOGGER.info("HA Sentinel set up successfully.")
    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — reload the config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: SentinelCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_unload()

        # Remove services if no more entries
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_RELOAD)
            hass.services.async_remove(DOMAIN, SERVICE_RESET_FAILURE_COUNT)

    return unload_ok
