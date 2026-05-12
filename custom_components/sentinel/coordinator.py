"""Coordinator for HA Sentinel.

Central orchestrator that manages all providers, dispatches updates
to entities, fires bus events, and exposes the reload action.
"""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_APPS_POLL_INTERVAL,
    CONF_EXCLUDED_ENTRIES,
    CONF_FIRE_EVENTS,
    CONF_GRACE_PERIOD,
    CONF_IGNORED_DEVICE_IDS,
    CONF_IGNORED_DEVICE_SOURCES,
    CONF_WATCH_STOPPED_ADDONS,
    DEFAULT_APPS_POLL_INTERVAL,
    DEFAULT_FIRE_EVENTS,
    DEFAULT_GRACE_PERIOD,
    DEFAULT_WATCH_STOPPED_ADDONS,
    EVENT_ITEM_CHANGED,
    PROVIDER_APPS,
    PROVIDER_DEVICES,
    PROVIDER_INTEGRATIONS,
    SIGNAL_SENTINEL_UPDATE,
)
from .providers import HealthItem, HealthProvider
from .providers.apps import AppsProvider
from .providers.devices import DevicesProvider
from .providers.integrations import IntegrationsProvider

_LOGGER = logging.getLogger(__name__)


class SentinelCoordinator:
    """Orchestrates all Sentinel providers."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self._config = config
        self._providers: dict[str, HealthProvider] = {}

    async def async_setup(self) -> None:
        """Set up all providers."""
        grace_period: int = self._config.get(CONF_GRACE_PERIOD, DEFAULT_GRACE_PERIOD)
        excluded: list[str] = self._config.get(CONF_EXCLUDED_ENTRIES, [])

        # v1: integrations provider
        integrations_provider = IntegrationsProvider(
            self.hass,
            excluded_entry_ids=set(excluded),
            grace_period=grace_period,
        )
        self._providers[PROVIDER_INTEGRATIONS] = integrations_provider
        await integrations_provider.async_setup(self._on_item_changed)

        # v2: devices provider
        devices_provider = DevicesProvider(
            self.hass,
            ignored_device_sources=set(self._config.get(CONF_IGNORED_DEVICE_SOURCES, [])),
            ignored_device_ids=set(self._config.get(CONF_IGNORED_DEVICE_IDS, [])),
            integration_problem_checker=self._device_integration_has_problem,
        )
        self._providers[PROVIDER_DEVICES] = devices_provider
        await devices_provider.async_setup(self._on_item_changed)

        # v3: apps (add-ons) provider — only active on HA OS
        apps_provider = AppsProvider(
            self.hass,
            watch_stopped=self._config.get(CONF_WATCH_STOPPED_ADDONS, DEFAULT_WATCH_STOPPED_ADDONS),
            poll_interval=self._config.get(CONF_APPS_POLL_INTERVAL, DEFAULT_APPS_POLL_INTERVAL),
        )
        self._providers[PROVIDER_APPS] = apps_provider
        await apps_provider.async_setup(self._on_item_changed)

        _LOGGER.debug("Sentinel coordinator set up with providers: %s", list(self._providers))

    async def async_unload(self) -> None:
        """Unload all providers."""
        for provider in self._providers.values():
            await provider.async_unload()
        self._providers.clear()

    @callback
    def _device_integration_has_problem(self, device_id: str) -> bool:
        """Return True if the integration owning this device has a known problem."""
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get(device_id)
        if device is None:
            return False

        integrations_provider = self._providers.get(PROVIDER_INTEGRATIONS)
        if not isinstance(integrations_provider, IntegrationsProvider):
            return False

        for entry_id in device.config_entries:
            item = integrations_provider.get_item(entry_id)
            if item is not None and not item.healthy:
                return True
        return False

    @callback
    def _on_item_changed(self, item: HealthItem) -> None:
        """Called by a provider when an item's state changes."""
        fire_events: bool = self._config.get(CONF_FIRE_EVENTS, DEFAULT_FIRE_EVENTS)

        if fire_events:
            source = item.extra.get("source", "")
            domain = item.extra.get("domain", "") or source.lower()
            if item.provider == PROVIDER_DEVICES:
                item_type = "device"
            elif item.provider == PROVIDER_APPS:
                item_type = "addon"
            else:
                item_type = "integration"
            self.hass.bus.async_fire(
                EVENT_ITEM_CHANGED,
                {
                    "item_id": item.id,
                    "provider": item.provider,
                    "name": item.name,
                    "domain": domain,
                    "source": source,
                    "item_type": item_type,
                    "healthy": item.healthy,
                    "state": item.state,
                    "severity": item.severity,
                    "reason": item.reason,
                    "failure_count": item.failure_count,
                    "since": item.since.isoformat(),
                },
            )

        async_dispatcher_send(self.hass, SIGNAL_SENTINEL_UPDATE, item)

    @callback
    def async_recheck(self) -> None:
        """Re-fire events for all currently unhealthy items."""
        for item in self.get_all_items():
            if not item.healthy:
                self._on_item_changed(item)

    def get_all_items(self) -> list[HealthItem]:
        """Return all monitored items across all providers."""
        items = []
        for provider in self._providers.values():
            items.extend(provider.get_items().values())
        return items

    def get_problem_count(self) -> int:
        """Return the total number of unhealthy items."""
        return sum(1 for item in self.get_all_items() if not item.healthy)

    async def async_reload_item(self, item_id: str) -> bool:
        """Reload an item by ID, trying all providers."""
        for provider in self._providers.values():
            if provider.get_item(item_id) is not None:
                return await provider.async_reload_item(item_id)
        _LOGGER.warning("Sentinel: Cannot reload unknown item %s", item_id)
        return False

    async def async_reset_failure_count(self, item_id: str) -> None:
        """Reset the failure count for an item."""
        for provider in self._providers.values():
            item = provider.get_item(item_id)
            if item is not None:
                item.failure_count = 0
                async_dispatcher_send(self.hass, SIGNAL_SENTINEL_UPDATE, item)
                return

