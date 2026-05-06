"""Coordinator for HA Sentinel.

Central orchestrator that manages all providers, dispatches updates
to entities, fires bus events, and exposes the reload action.
"""
from __future__ import annotations

import logging
from typing import Callable

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_EXCLUDED_ENTRIES,
    CONF_EXTRA_ENTRIES,
    CONF_FIRE_EVENTS,
    CONF_GRACE_PERIOD,
    DEFAULT_FIRE_EVENTS,
    DEFAULT_GRACE_PERIOD,
    EVENT_ITEM_CHANGED,
    PROVIDER_INTEGRATIONS,
    SIGNAL_SENTINEL_UPDATE,
)
from .providers import HealthItem, HealthProvider
from .providers.integrations import IntegrationsProvider

_LOGGER = logging.getLogger(__name__)


class SentinelCoordinator:
    """Orchestrates all Sentinel providers."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self._config = config
        self._providers: dict[str, HealthProvider] = {}
        self._listeners: list[Callable] = []

    async def async_setup(self) -> None:
        """Set up all providers."""
        grace_period: int = self._config.get(CONF_GRACE_PERIOD, DEFAULT_GRACE_PERIOD)
        excluded: list[str] = self._config.get(CONF_EXCLUDED_ENTRIES, [])
        extra: list[str] = self._config.get(CONF_EXTRA_ENTRIES, [])

        # v1: integrations provider
        integrations_provider = IntegrationsProvider(
            self.hass,
            excluded_entry_ids=set(excluded),
            extra_entry_ids=set(extra),
            grace_period=grace_period,
        )
        self._providers[PROVIDER_INTEGRATIONS] = integrations_provider
        await integrations_provider.async_setup(self._on_item_changed)

        _LOGGER.debug("Sentinel coordinator set up with providers: %s", list(self._providers))

    async def async_unload(self) -> None:
        """Unload all providers."""
        for provider in self._providers.values():
            await provider.async_unload()
        self._providers.clear()

    @callback
    def _on_item_changed(self, item: HealthItem) -> None:
        """Called by a provider when an item's state changes."""
        fire_events: bool = self._config.get(CONF_FIRE_EVENTS, DEFAULT_FIRE_EVENTS)

        # Fire HA bus event (for user automations)
        if fire_events:
            self.hass.bus.async_fire(
                EVENT_ITEM_CHANGED,
                {
                    "item_id": item.id,
                    "provider": item.provider,
                    "name": item.name,
                    "domain": item.extra.get("domain", ""),
                    "healthy": item.healthy,
                    "state": item.state,
                    "severity": item.severity,
                    "reason": item.reason,
                    "failure_count": item.failure_count,
                    "since": item.since.isoformat(),
                },
            )

        # Dispatch internal signal so entities can update themselves
        async_dispatcher_send(self.hass, SIGNAL_SENTINEL_UPDATE, item)

    @callback
    def async_recheck(self) -> None:
        """Re-fire events for all currently unhealthy items.

        Useful to trigger automations on demand without waiting for a state change.
        """
        for item in self.get_all_items():
            if not item.healthy:
                self._on_item_changed(item)

    def get_all_items(self) -> list[HealthItem]:
        """Return all monitored items across all providers."""
        items = []
        for provider in self._providers.values():
            items.extend(provider.get_items().values())
        return items

    def get_items_by_provider(self, provider_id: str) -> list[HealthItem]:
        """Return all items for a specific provider."""
        provider = self._providers.get(provider_id)
        if provider is None:
            return []
        return list(provider.get_items().values())

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

    def update_config(self, new_config: dict) -> None:
        """Update coordinator configuration (called on options update)."""
        self._config = new_config
        # Update provider-specific config
        if PROVIDER_INTEGRATIONS in self._providers:
            provider = self._providers[PROVIDER_INTEGRATIONS]
            if isinstance(provider, IntegrationsProvider):
                excluded = set(new_config.get(CONF_EXCLUDED_ENTRIES, []))
                extra = set(new_config.get(CONF_EXTRA_ENTRIES, []))
                provider.update_excluded(excluded)
                provider.update_extra(extra)
