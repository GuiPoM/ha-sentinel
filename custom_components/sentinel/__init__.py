"""HA Sentinel — proactive health monitoring for Home Assistant."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import (
    CONF_ENABLE_DEVICE_DISCOVERY,
    CONF_IGNORED_DEVICE_IDS,
    CONF_IGNORED_DEVICE_SOURCES,
    DEFAULT_ENABLE_DEVICE_DISCOVERY,
    DOMAIN,
)
from .coordinator import SentinelCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "sensor"]

# Service schemas
SERVICE_RELOAD = "reload_item"
SERVICE_RELOAD_SCHEMA = vol.Schema(
    {vol.Required("item_id"): cv.string}
)

SERVICE_RESET_FAILURE_COUNT = "reset_failure_count"
SERVICE_RESET_FAILURE_COUNT_SCHEMA = vol.Schema(
    {vol.Required("item_id"): cv.string}
)

SERVICE_CHECK = "check"
SERVICE_CHECK_SCHEMA = vol.Schema({})

SERVICE_PURGE = "purge"
SERVICE_PURGE_SCHEMA = vol.Schema({})


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entry to the current version.

    v1 → v2: Remove ignored_device_sources and ignored_device_ids (replaced by
    device subentries). Add enable_device_discovery option. Breaking change:
    previously ignored/monitored devices must be re-added via subentries.
    """
    _LOGGER.debug(
        "Migrating Sentinel config entry from version %s", config_entry.version
    )

    if config_entry.version == 1:
        # Remove deprecated device-exclusion options — no longer supported.
        # Users must re-add their devices via subentries (opt-in discovery).
        new_options = {
            k: v
            for k, v in config_entry.options.items()
            if k not in (CONF_IGNORED_DEVICE_SOURCES, CONF_IGNORED_DEVICE_IDS)
        }
        new_options.setdefault(CONF_ENABLE_DEVICE_DISCOVERY, DEFAULT_ENABLE_DEVICE_DISCOVERY)

        hass.config_entries.async_update_entry(
            config_entry,
            options=new_options,
            version=2,
        )
        _LOGGER.info(
            "Sentinel: migrated config entry to v2 — device subentries architecture. "
            "Previously monitored devices must be re-added via the integration page."
        )
        return True

    _LOGGER.error(
        "Sentinel: cannot migrate from version %s — downgrade not supported",
        config_entry.version,
    )
    return False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA Sentinel from a config entry."""
    config = {**entry.data, **entry.options}
    subentries = list(entry.subentries.values())

    coordinator = SentinelCoordinator(hass, config, subentries=subentries)
    await coordinator.async_setup()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Clean up orphaned entities BEFORE setting up platforms
    _cleanup_orphaned_entities(hass, entry, coordinator)

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def handle_reload(call: ServiceCall) -> None:
        item_id = call.data["item_id"]
        await coordinator.async_reload_item(item_id)

    async def handle_reset_failure_count(call: ServiceCall) -> None:
        item_id = call.data["item_id"]
        await coordinator.async_reset_failure_count(item_id)

    async def handle_check(call: ServiceCall) -> None:
        """Re-fire events for all currently unhealthy items."""
        coordinator.async_recheck()

    async def handle_purge(call: ServiceCall) -> None:
        """Remove ALL Sentinel entities from the registry — no reload."""
        registry = er.async_get(hass)

        to_remove = [
            e.entity_id
            for e in list(registry.entities.values())
            if e.platform == DOMAIN
        ]

        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

        for eid in to_remove:
            if eid in registry.entities:
                registry.async_remove(eid)
                _LOGGER.info("Sentinel purge: removed %s", eid)

        _LOGGER.info("Sentinel purge: %d entities removed — restart HA", len(to_remove))

    hass.services.async_register(
        DOMAIN, SERVICE_RELOAD, handle_reload, schema=SERVICE_RELOAD_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_FAILURE_COUNT,
        handle_reset_failure_count,
        schema=SERVICE_RESET_FAILURE_COUNT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CHECK, handle_check, schema=SERVICE_CHECK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_PURGE, handle_purge, schema=SERVICE_PURGE_SCHEMA
    )

    # Reload the entry whenever subentries are added/removed or options change.
    # This is the standard pattern (Battery Notes, etc.) — no partial reload.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info("Sentinel set up successfully.")
    return True


@callback
def _cleanup_orphaned_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: SentinelCoordinator,
) -> None:
    """Remove entities in the registry that are no longer monitored."""
    registry = er.async_get(hass)
    known_ids = {f"{DOMAIN}_{item.id}" for item in coordinator.get_all_items()}
    # Also keep the global problems sensor
    known_ids.add(f"{DOMAIN}_{entry.entry_id}_problem_count")

    _LOGGER.debug("Sentinel cleanup: known_ids=%s", known_ids)

    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity_entry.unique_id not in known_ids:
            _LOGGER.debug(
                "Sentinel: removing orphaned entity %s (unique_id=%s)",
                entity_entry.entity_id,
                entity_entry.unique_id,
            )
            registry.async_remove(entity_entry.entity_id)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update or subentry change — reload the config entry."""
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
            hass.services.async_remove(DOMAIN, SERVICE_CHECK)
            hass.services.async_remove(DOMAIN, SERVICE_PURGE)

    return unload_ok
