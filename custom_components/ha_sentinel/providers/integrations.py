"""Integrations provider for HA Sentinel.

Monitors all config entries (integrations) in Home Assistant and
reports their health state in real time using the dispatcher signal.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Callable

from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntry,
    ConfigEntryChange,
    ConfigEntryState,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from ..const import (
    DEFAULT_GRACE_PERIOD,
    ERROR_STATES,
    EXCLUDED_DOMAINS,
    EXCLUDED_SOURCES,
    HEALTHY_STATES,
    INACTIVE_STATES,
    PROBLEM_STATES,
    PROVIDER_INTEGRATIONS,
    TRANSIENT_STATES,
    WARNING_STATES,
)
from . import HealthItem, HealthProvider

_LOGGER = logging.getLogger(__name__)

# Exhaustive map of all known ConfigEntryState values
_STATE_MAP: dict[ConfigEntryState, str] = {
    ConfigEntryState.LOADED: "loaded",
    ConfigEntryState.SETUP_ERROR: "setup_error",
    ConfigEntryState.SETUP_RETRY: "setup_retry",
    ConfigEntryState.MIGRATION_ERROR: "migration_error",
    ConfigEntryState.FAILED_UNLOAD: "failed_unload",
    ConfigEntryState.NOT_LOADED: "not_loaded",
    ConfigEntryState.SETUP_IN_PROGRESS: "setup_in_progress",
    ConfigEntryState.UNLOAD_IN_PROGRESS: "unload_in_progress",
}


def _entry_state_str(entry: ConfigEntry) -> str:
    """Return a string representation of the entry state.

    Falls back to the raw enum value for any unknown future states,
    and logs a warning so we know to update the map.
    """
    mapped = _STATE_MAP.get(entry.state)
    if mapped is None:
        _LOGGER.warning(
            "Sentinel: unknown ConfigEntryState %r for entry %r — treating as warning",
            entry.state,
            entry.title,
        )
        return entry.state.value  # unknown → treated as warning by _is_problem
    return mapped


def _is_healthy(state_str: str) -> bool:
    return state_str in HEALTHY_STATES


def _is_problem(state_str: str) -> bool:
    """Return True for any non-healthy, non-transient, non-inactive state.

    Unknown future states (not in any known set) are treated as warnings.
    """
    return state_str not in HEALTHY_STATES and state_str not in TRANSIENT_STATES and state_str not in INACTIVE_STATES


def _get_severity(state_str: str) -> str:
    """Return 'error', 'warning', or 'ok'."""
    if state_str in ERROR_STATES:
        return "error"
    if state_str in WARNING_STATES:
        return "warning"
    if state_str in HEALTHY_STATES:
        return "ok"
    if state_str in TRANSIENT_STATES or state_str in INACTIVE_STATES:
        return "ok"
    # Unknown future state → warning
    return "warning"


class IntegrationsProvider(HealthProvider):
    """Health provider for Home Assistant config entries (integrations)."""

    def __init__(
        self,
        hass: HomeAssistant,
        excluded_entry_ids: set[str] | None = None,
        extra_entry_ids: set[str] | None = None,
        grace_period: int = DEFAULT_GRACE_PERIOD,
    ) -> None:
        """Initialize the integrations provider."""
        super().__init__(hass)
        self._excluded: set[str] = excluded_entry_ids or set()
        self._extra: set[str] = extra_entry_ids or set()
        self._grace_period = grace_period
        self._on_change: Callable[[HealthItem], None] | None = None
        self._unsubscribe: Callable | None = None
        # Pending timers: entry_id -> asyncio.TimerHandle
        self._pending_timers: dict[str, asyncio.TimerHandle] = {}
        # Track previous healthy state to detect transitions
        self._previous_healthy: dict[str, bool] = {}

    @property
    def provider_id(self) -> str:
        return PROVIDER_INTEGRATIONS

    @property
    def name(self) -> str:
        return "Integrations"

    def _should_watch(self, entry: ConfigEntry) -> bool:
        """Return True if this entry should be monitored."""
        # Never watch ourselves
        if entry.domain == "ha_sentinel":
            return False
        # Explicit opt-out always wins
        if entry.entry_id in self._excluded:
            return False
        # Explicit opt-in always wins
        if entry.entry_id in self._extra:
            return True
        # Skip system internals and user-ignored discoveries
        if entry.source in EXCLUDED_SOURCES:
            return False
        # Skip HA helper/utility domains
        if entry.domain in EXCLUDED_DOMAINS:
            return False
        return True

    async def async_setup(self, on_change_callback: Callable[[HealthItem], None]) -> None:
        """Set up the provider: snapshot all current entries and subscribe to changes."""
        self._on_change = on_change_callback

        # Snapshot all existing config entries
        for entry in self.hass.config_entries.async_entries():
            if not self._should_watch(entry):
                continue
            item = self._build_item(entry)
            self._items[entry.entry_id] = item
            self._previous_healthy[entry.entry_id] = item.healthy

        # Subscribe to all future config entry changes
        self._unsubscribe = async_dispatcher_connect(
            self.hass,
            SIGNAL_CONFIG_ENTRY_CHANGED,
            self._on_entry_changed,
        )

        _LOGGER.debug(
            "IntegrationsProvider set up: monitoring %d entries", len(self._items)
        )

    async def async_unload(self) -> None:
        """Unload provider and cancel pending timers."""
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

        for handle in self._pending_timers.values():
            handle.cancel()
        self._pending_timers.clear()

    async def async_reload_item(self, item_id: str) -> bool:
        """Reload the config entry with the given entry_id."""
        try:
            await self.hass.config_entries.async_reload(item_id)
            return True
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to reload entry %s: %s", item_id, err)
            return False

    @callback
    def _on_entry_changed(
        self, change: ConfigEntryChange, entry: ConfigEntry
    ) -> None:
        """Handle a config entry change signal."""
        entry_id = entry.entry_id

        if entry_id in self._excluded:
            return

        if change == ConfigEntryChange.REMOVED:
            # Clean up removed entry
            self._items.pop(entry_id, None)
            self._previous_healthy.pop(entry_id, None)
            if entry_id in self._pending_timers:
                self._pending_timers.pop(entry_id).cancel()
            return

        state_str = _entry_state_str(entry)

        # Ignore purely transient states (in-progress transitions)
        if state_str in TRANSIENT_STATES and state_str != "not_loaded":
            return

        # If newly added entry, create item immediately
        if change == ConfigEntryChange.ADDED or entry_id not in self._items:
            item = self._build_item(entry)
            self._items[entry_id] = item
            self._previous_healthy[entry_id] = item.healthy
            if self._on_change:
                self._on_change(item)
            return

        # For UPDATED changes: apply grace period before signalling a problem
        if _is_problem(state_str):
            self._schedule_problem(entry, state_str)
        else:
            # Healthy or not_loaded (intentionally disabled) — apply immediately
            self._cancel_pending(entry_id)
            self._apply_state(entry, state_str)

    def _schedule_problem(self, entry: ConfigEntry, state_str: str) -> None:
        """Schedule a problem notification after the grace period."""
        entry_id = entry.entry_id

        # Cancel any existing timer for this entry
        self._cancel_pending(entry_id)

        @callback
        def _fire() -> None:
            self._pending_timers.pop(entry_id, None)
            # Re-check: state may have recovered during grace period
            current_entry = self.hass.config_entries.async_get_entry(entry_id)
            if current_entry is None:
                return
            current_state = _entry_state_str(current_entry)
            if _is_problem(current_state):
                self._apply_state(current_entry, current_state)

        handle = self.hass.loop.call_later(self._grace_period, _fire)
        self._pending_timers[entry_id] = handle

    def _cancel_pending(self, entry_id: str) -> None:
        """Cancel a pending grace-period timer."""
        if entry_id in self._pending_timers:
            self._pending_timers.pop(entry_id).cancel()

    def _apply_state(self, entry: ConfigEntry, state_str: str) -> None:
        """Apply a new state to an item and notify if changed."""
        entry_id = entry.entry_id
        existing = self._items.get(entry_id)
        was_healthy = self._previous_healthy.get(entry_id, True)
        is_healthy = _is_healthy(state_str)

        failure_count = existing.failure_count if existing else 0
        if was_healthy and not is_healthy:
            failure_count += 1

        item = self._build_item(entry, failure_count=failure_count)
        self._items[entry_id] = item
        self._previous_healthy[entry_id] = is_healthy

        # Only notify if health state actually changed
        if is_healthy != was_healthy or existing is None:
            _LOGGER.debug(
                "Entry %r (%s) changed: healthy=%s state=%s reason=%s",
                entry.title,
                entry.domain,
                is_healthy,
                state_str,
                item.reason,
            )
            if self._on_change:
                self._on_change(item)

    def _build_item(
        self, entry: ConfigEntry, failure_count: int = 0
    ) -> HealthItem:
        """Build a HealthItem from a ConfigEntry."""
        state_str = _entry_state_str(entry)
        healthy = _is_healthy(state_str)
        existing = self._items.get(entry.entry_id)

        return HealthItem(
            id=entry.entry_id,
            name=entry.title,
            provider=PROVIDER_INTEGRATIONS,
            healthy=healthy,
            state=state_str,
            severity=_get_severity(state_str),
            reason=getattr(entry, "reason", None),
            since=existing.since if existing and existing.healthy == healthy else datetime.now(),
            failure_count=existing.failure_count if existing else failure_count,
            can_reload=entry.state.recoverable,
            extra={
                "domain": entry.domain,
                "entry_id": entry.entry_id,
                "source": entry.source,
                "disabled_by": str(entry.disabled_by) if entry.disabled_by else None,
            },
        )

    def update_excluded(self, excluded_entry_ids: set[str]) -> None:
        """Update the set of excluded entry IDs."""
        self._excluded = excluded_entry_ids

    def update_extra(self, extra_entry_ids: set[str]) -> None:
        """Update the set of extra (opt-in) entry IDs."""
        self._extra = extra_entry_ids
