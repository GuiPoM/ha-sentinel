"""Devices provider for HA Sentinel.

Monitors physical devices (entities in physical domains or with vital device
classes) and reports them as unhealthy when they become unavailable or silent
for too long.

One HealthItem is created per device (device_id), not per entity.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from ..const import (
    DEFAULT_DETECT_SILENCE,
    DEFAULT_SILENCE_THRESHOLD_HOURS,
    PHYSICAL_DOMAINS,
    PROVIDER_DEVICES,
    VITAL_DEVICE_CLASSES,
)
from . import HealthItem, HealthProvider

if TYPE_CHECKING:
    from homeassistant.core import Event

_LOGGER = logging.getLogger(__name__)

# How often to run the silence scan
_SILENCE_SCAN_INTERVAL = timedelta(hours=1)


def _get_device_source(hass: HomeAssistant, device_id: str) -> str:
    """Return the integration source string for a device (uppercase)."""
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get(device_id)
    if device is None:
        return "DEVICE"
    identifiers = list(device.identifiers)
    if not identifiers:
        return "DEVICE"
    # identifiers is a set of tuples: {(domain, unique_id), ...}
    first = list(identifiers[0])
    if first:
        return str(first[0]).upper()
    return "DEVICE"


def _is_eligible(entity) -> bool:
    """Return True if the entity should be monitored by the devices provider."""
    # Must be backed by a device
    if not entity.device_id:
        return False
    # Skip diagnostic / config entities
    if entity.entity_category is not None:
        return False
    # Skip disabled entities — their state is always unavailable, not a real problem
    if entity.disabled_by is not None:
        return False
    domain = entity.domain
    device_class = entity.original_device_class or entity.device_class
    if domain in PHYSICAL_DOMAINS:
        return True
    if domain in ("sensor", "binary_sensor") and device_class in VITAL_DEVICE_CLASSES:
        return True
    return False


class DevicesProvider(HealthProvider):
    """Health provider for physical HA devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        ignored_device_sources: set[str] | None = None,
        ignored_device_ids: set[str] | None = None,
        detect_silence: bool = DEFAULT_DETECT_SILENCE,
        silence_threshold_hours: int = DEFAULT_SILENCE_THRESHOLD_HOURS,
        integration_problem_checker: Callable[[str], bool] | None = None,
    ) -> None:
        """Initialize the devices provider."""
        super().__init__(hass)
        self._ignored_sources: set[str] = {
            s.upper() for s in (ignored_device_sources or set())
        }
        self._ignored_device_ids: set[str] = ignored_device_ids or set()
        self._detect_silence = detect_silence
        self._silence_threshold = timedelta(hours=silence_threshold_hours)
        self._integration_problem_checker = integration_problem_checker
        self._on_change: Callable[[HealthItem], None] | None = None
        self._unsub_state: Callable | None = None
        self._unsub_silence: Callable | None = None
        # Map entity_id -> device_id for quick lookup
        self._entity_to_device: dict[str, str] = {}
        # Track previous healthy state per device
        self._previous_healthy: dict[str, bool] = {}

    @property
    def provider_id(self) -> str:
        return PROVIDER_DEVICES

    @property
    def name(self) -> str:
        return "Devices"

    def _should_watch_device(self, device_id: str) -> bool:
        """Return True if this device should be monitored."""
        if device_id in self._ignored_device_ids:
            return False
        source = _get_device_source(self.hass, device_id)
        if source in self._ignored_sources:
            return False
        return True

    def _integration_has_problem(self, device_id: str) -> bool:
        """Return True if the integration owning this device already has a problem."""
        if self._integration_problem_checker is None:
            return False
        return self._integration_problem_checker(device_id)

    async def async_setup(self, on_change_callback: Callable[[HealthItem], None]) -> None:
        """Set up the provider: snapshot eligible devices and subscribe to changes."""
        self._on_change = on_change_callback

        ent_reg = er.async_get(self.hass)

        # Build entity->device map and initial device states
        device_entities: dict[str, list[er.RegistryEntry]] = {}
        for entity in ent_reg.entities.values():
            if not _is_eligible(entity):
                continue
            if not self._should_watch_device(entity.device_id):
                continue
            self._entity_to_device[entity.entity_id] = entity.device_id
            device_entities.setdefault(entity.device_id, []).append(entity)

        # Build initial HealthItem per device
        for device_id, entities in device_entities.items():
            item = self._build_device_item(device_id, entities)
            if item is not None:
                self._items[device_id] = item
                self._previous_healthy[device_id] = item.healthy

        _LOGGER.debug(
            "DevicesProvider set up: monitoring %d devices (%d entities mapped)",
            len(self._items),
            len(self._entity_to_device),
        )

        # Subscribe to state changes for all eligible entity_ids
        if self._entity_to_device:
            self._unsub_state = async_track_state_change_event(
                self.hass,
                list(self._entity_to_device.keys()),
                self._on_state_changed,
            )

        # Schedule periodic silence scan
        if self._detect_silence:
            self._unsub_silence = async_track_time_interval(
                self.hass,
                self._async_scan_silence,
                _SILENCE_SCAN_INTERVAL,
            )

    async def async_unload(self) -> None:
        """Unload provider and cancel subscriptions."""
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        if self._unsub_silence:
            self._unsub_silence()
            self._unsub_silence = None

    async def async_reload_item(self, item_id: str) -> bool:
        """Devices cannot be reloaded — always returns False."""
        return False

    @callback
    def _on_state_changed(self, event: Event) -> None:
        """Handle entity state change — re-evaluate the owning device."""
        entity_id = event.data.get("entity_id")
        if not entity_id:
            return
        device_id = self._entity_to_device.get(entity_id)
        if not device_id:
            return
        self._async_evaluate_device(device_id)

    @callback
    def _async_scan_silence(self, _now=None) -> None:
        """Periodic scan to detect silent devices (no update for >threshold)."""
        if not self._detect_silence:
            return
        for device_id in list(self._items.keys()):
            self._async_evaluate_device(device_id)

    @callback
    def _async_evaluate_device(self, device_id: str) -> None:
        """Re-evaluate a device's health and notify if changed."""
        # Suppress if owning integration already has a problem (noise reduction)
        if self._integration_has_problem(device_id):
            # If we had an item, mark it healthy silently (integration is the source)
            if device_id in self._items:
                existing = self._items[device_id]
                if not existing.healthy:
                    item = self._build_device_item_from_registry(device_id)
                    if item is not None:
                        # Force healthy to suppress noise
                        from dataclasses import replace
                        item = replace(item, healthy=True, state="suppressed", severity="ok")
                        self._items[device_id] = item
                        self._previous_healthy[device_id] = True
            return

        item = self._build_device_item_from_registry(device_id)
        if item is None:
            return

        was_healthy = self._previous_healthy.get(device_id, True)
        existing = self._items.get(device_id)

        # Update failure count on transition to unhealthy
        if was_healthy and not item.healthy:
            failure_count = (existing.failure_count if existing else 0) + 1
            from dataclasses import replace
            item = replace(item, failure_count=failure_count)

        self._items[device_id] = item
        self._previous_healthy[device_id] = item.healthy

        if item.healthy != was_healthy or existing is None:
            if self._on_change:
                self._on_change(item)

    def _build_device_item_from_registry(self, device_id: str) -> HealthItem | None:
        """Build a HealthItem for a device using its current entity states."""
        ent_reg = er.async_get(self.hass)
        entities = [
            e for e in ent_reg.entities.values()
            if e.device_id == device_id and e.entity_id in self._entity_to_device
        ]
        return self._build_device_item(device_id, entities)

    def _build_device_item(
        self,
        device_id: str,
        entities: list,
    ) -> HealthItem | None:
        """Build a HealthItem for a device from its entities' current states."""
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get(device_id)
        if device is None:
            return None

        device_name = device.name_by_user or device.name or device_id
        source = _get_device_source(self.hass, device_id)

        # Determine health by checking all entity states
        unavailable_entities: list[str] = []
        silent_entities: list[str] = []
        now = datetime.now()

        for entity in entities:
            state = self.hass.states.get(entity.entity_id)
            if state is None:
                unavailable_entities.append(entity.entity_id)
                continue
            if state.state == STATE_UNAVAILABLE:
                unavailable_entities.append(entity.entity_id)
            elif self._detect_silence and state.last_reported:
                age = now - state.last_reported.replace(tzinfo=None)
                if age > self._silence_threshold:
                    silent_entities.append(entity.entity_id)

        is_unavailable = len(unavailable_entities) > 0
        is_silent = not is_unavailable and len(silent_entities) > 0
        is_healthy = not is_unavailable and not is_silent

        if is_unavailable:
            state_str = "unavailable"
            severity = "error"
            reason = f"{len(unavailable_entities)} entité(s) indisponible(s)"
        elif is_silent:
            state_str = "silent"
            severity = "warning"
            reason = f"Aucune mise à jour depuis >{self._silence_threshold.seconds // 3600}h"
        else:
            state_str = "ok"
            severity = "ok"
            reason = None

        existing = self._items.get(device_id)

        return HealthItem(
            id=device_id,
            name=device_name,
            provider=PROVIDER_DEVICES,
            healthy=is_healthy,
            state=state_str,
            severity=severity,
            reason=reason,
            since=(
                existing.since
                if existing and existing.healthy == is_healthy
                else now
            ),
            failure_count=existing.failure_count if existing else 0,
            can_reload=False,
            extra={
                "device_id": device_id,
                "source": source,
                "unavailable_entities": unavailable_entities,
                "silent_entities": silent_entities,
            },
        )

    def update_config(
        self,
        ignored_device_sources: set[str],
        ignored_device_ids: set[str],
        detect_silence: bool,
        silence_threshold_hours: int,
    ) -> None:
        """Update provider configuration."""
        self._ignored_sources = {s.upper() for s in ignored_device_sources}
        self._ignored_device_ids = ignored_device_ids
        self._detect_silence = detect_silence
        self._silence_threshold = timedelta(hours=silence_threshold_hours)
