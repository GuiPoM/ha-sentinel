"""Devices provider for HA Sentinel.

Monitors physical devices (entities in physical domains or with vital device
classes) and reports them as unhealthy when they become unavailable.

One HealthItem is created per device (device_id), not per entity.
A device is considered unhealthy when at least one of its monitored entities
is in the 'unavailable' state — which is the reliable signal that the device
is no longer reachable by its hub (Hue, Z-Wave JS, Zigbee2MQTT, Matter, etc.).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import logging
from typing import TYPE_CHECKING

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_registry import EVENT_ENTITY_REGISTRY_UPDATED
from homeassistant.helpers.event import (
    async_track_state_added_domain,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

from ..const import (
    PHYSICAL_DOMAINS,
    PROVIDER_DEVICES,
    VITAL_DEVICE_CLASSES,
)
from . import HealthItem, HealthProvider

if TYPE_CHECKING:
    from homeassistant.core import Event

_LOGGER = logging.getLogger(__name__)


def _get_device_source(hass: HomeAssistant, device_id: str) -> str:
    """Return the integration source string for a device (uppercase).

    Uses the first element of the first identifier tuple, sorted for
    deterministic output when a device has multiple integrations.
    """
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get(device_id)
    if device is None:
        return "DEVICE"
    identifiers = sorted(device.identifiers)
    if not identifiers:
        return "DEVICE"
    # Each identifier is a (domain, unique_id) tuple — domain is first element
    return str(identifiers[0][0]).upper()


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
    return domain in ("sensor", "binary_sensor") and device_class in VITAL_DEVICE_CLASSES


class DevicesProvider(HealthProvider):
    """Health provider for physical HA devices.

    A device is unhealthy when at least one of its monitored entities is
    unavailable. No silence detection — unavailable is the only reliable
    signal that a device has lost connectivity with its hub.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        ignored_device_sources: set[str] | None = None,
        ignored_device_ids: set[str] | None = None,
        integration_problem_checker: Callable[[str], bool] | None = None,
    ) -> None:
        """Initialize the devices provider."""
        super().__init__(hass)
        self._ignored_sources: set[str] = {
            s.upper() for s in (ignored_device_sources or set())
        }
        self._ignored_device_ids: set[str] = ignored_device_ids or set()
        self._integration_problem_checker = integration_problem_checker
        self._on_change: Callable[[HealthItem], None] | None = None
        self._unsub_state: Callable | None = None
        self._unsub_added: Callable | None = None
        self._unsub_registry: Callable | None = None
        # Map entity_id -> device_id for quick lookup in state change handler
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
        # Skip devices whose config entries are all disabled in HA
        # (e.g. integration disabled by user — its devices are intentionally off)
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get(device_id)
        if device and device.config_entries:
            entries = self.hass.config_entries
            if all(
                (e := entries.async_get_entry(eid)) is not None and e.disabled_by is not None
                for eid in device.config_entries
            ):
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

        # Build entity->device map and initial device set
        device_entities: dict[str, list[er.RegistryEntry]] = {}
        for entity in ent_reg.entities.values():
            if not _is_eligible(entity):
                continue
            if not self._should_watch_device(entity.device_id):
                continue
            self._entity_to_device[entity.entity_id] = entity.device_id
            device_entities.setdefault(entity.device_id, []).append(entity)

        # Build initial HealthItem per device — always healthy at startup.
        # Transient unavailable states during boot would cause false positives.
        # Real problems are detected via STATE_CHANGED events or the startup recheck.
        for device_id, entities in device_entities.items():
            item = self._build_device_item(device_id, entities, force_healthy=True)
            if item is not None:
                self._items[device_id] = item
                self._previous_healthy[device_id] = True

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

        # Watch for new entities appearing after setup (new devices paired, entities re-enabled).
        # watched_domains is derived from PHYSICAL_DOMAINS so it stays in sync automatically.
        watched_domains = frozenset({*PHYSICAL_DOMAINS, "sensor", "binary_sensor"})
        self._unsub_added = async_track_state_added_domain(
            self.hass, watched_domains, self._on_entity_added
        )

        # Watch for entity registry removals to clean up _entity_to_device
        self._unsub_registry = self.hass.bus.async_listen(
            EVENT_ENTITY_REGISTRY_UPDATED, self._on_entity_registry_updated
        )

        # Re-evaluate all devices once HA is fully started to clear
        # transient unavailable states captured during boot snapshot
        @callback
        def _async_startup_recheck(_event=None) -> None:
            _LOGGER.debug("DevicesProvider: HA started — running startup recheck")
            for device_id in list(self._items.keys()):
                self._async_evaluate_device(device_id)

        if self.hass.is_running:
            _async_startup_recheck()
        else:
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _async_startup_recheck
            )

    async def async_unload(self) -> None:
        """Unload provider and cancel subscriptions."""
        for unsub in (self._unsub_state, self._unsub_added, self._unsub_registry):
            if unsub:
                unsub()
        self._unsub_state = None
        self._unsub_added = None
        self._unsub_registry = None

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
    def _on_entity_added(self, event: Event) -> None:
        """Handle a new entity appearing in the state machine.

        Fired by async_track_state_added_domain when old_state is None.
        Covers both newly paired devices and re-enabled entities.
        """
        entity_id = event.data.get("entity_id")
        if not entity_id or entity_id in self._entity_to_device:
            return
        ent_reg = er.async_get(self.hass)
        entity = ent_reg.async_get(entity_id)
        if entity is None or not _is_eligible(entity):
            return
        if not self._should_watch_device(entity.device_id):
            return
        # Register the new entity
        self._entity_to_device[entity_id] = entity.device_id
        self._resubscribe_state()
        _LOGGER.debug("DevicesProvider: tracking new entity %s (device %s)", entity_id, entity.device_id)
        # Create a healthy HealthItem for the device if not already tracked
        if entity.device_id not in self._items:
            item = self._build_device_item_from_registry(entity.device_id)
            if item is not None:
                self._items[entity.device_id] = item
                self._previous_healthy[entity.device_id] = True
                if self._on_change:
                    self._on_change(item)

    @callback
    def _on_entity_registry_updated(self, event: Event) -> None:
        """Handle entity registry changes."""
        action = event.data.get("action")
        entity_id = event.data.get("entity_id")

        if action == "remove":
            if entity_id in self._entity_to_device:
                self._entity_to_device.pop(entity_id)
                self._resubscribe_state()
                _LOGGER.debug("DevicesProvider: removed entity %s from tracking", entity_id)

        elif action == "update":
            changes = event.data.get("changes", {})
            if "disabled_by" not in changes:
                return

            ent_reg = er.async_get(self.hass)
            entity = ent_reg.async_get(entity_id)

            if entity is not None and entity.disabled_by is None:
                # Entity re-enabled — treat as new entity added
                self._on_entity_added(event)
            elif entity_id in self._entity_to_device:
                # Entity disabled — remove from tracking
                device_id = self._entity_to_device.pop(entity_id)
                self._resubscribe_state()
                _LOGGER.debug(
                    "DevicesProvider: entity %s disabled, removed from tracking", entity_id
                )
                # If device has no more tracked entities, remove it
                if not any(d == device_id for d in self._entity_to_device.values()):
                    self._items.pop(device_id, None)
                    self._previous_healthy.pop(device_id, None)
                    _LOGGER.debug(
                        "DevicesProvider: device %s has no more tracked entities, removed",
                        device_id,
                    )

    @callback
    def _resubscribe_state(self) -> None:
        """Re-subscribe to state changes for the current entity set.

        Called whenever _entity_to_device changes (entity added or removed).
        async_track_state_change_event uses a shared internal dict so this is O(n)
        but does not create a new bus listener.
        """
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        if self._entity_to_device:
            self._unsub_state = async_track_state_change_event(
                self.hass,
                list(self._entity_to_device.keys()),
                self._on_state_changed,
            )

    @callback
    def _async_evaluate_device(self, device_id: str) -> None:
        """Re-evaluate a device's health and notify if changed."""
        # Suppress if owning integration already has a problem (noise reduction)
        if self._integration_has_problem(device_id):
            if device_id in self._items:
                existing = self._items[device_id]
                if not existing.healthy:
                    item = self._build_device_item_from_registry(device_id)
                    if item is not None:
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
        force_healthy: bool = False,
    ) -> HealthItem | None:
        """Build a HealthItem for a device from its entities' current states.

        If force_healthy is True, always return a healthy item regardless of
        current entity states (used at startup to avoid false positives).
        """
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get(device_id)
        if device is None:
            return None

        device_name = device.name_by_user or device.name or device_id
        source = _get_device_source(self.hass, device_id)
        now = dt_util.utcnow()

        # If force_healthy, skip all state checks and return a healthy item
        if force_healthy:
            existing = self._items.get(device_id)
            return HealthItem(
                id=device_id,
                name=device_name,
                provider=PROVIDER_DEVICES,
                healthy=True,
                state="ok",
                severity="ok",
                reason=None,
                since=existing.since if existing else now,
                failure_count=existing.failure_count if existing else 0,
                can_reload=False,
                extra={
                    "device_id": device_id,
                    "source": source,
                    "unavailable_entities": [],
                    "device_url": f"/config/devices/device/{device_id}",
                },
            )

        # Determine health — a device is unhealthy when any entity is unavailable
        unavailable_entities: list[str] = []

        for entity in entities:
            state = self.hass.states.get(entity.entity_id)
            if state is None:
                unavailable_entities.append(entity.entity_id)
                continue
            # Skip restored states — entity not yet updated since last restart
            if state.attributes.get("restored"):
                continue
            if state.state == STATE_UNAVAILABLE:
                unavailable_entities.append(entity.entity_id)

        is_healthy = len(unavailable_entities) == 0

        existing = self._items.get(device_id)

        return HealthItem(
            id=device_id,
            name=device_name,
            provider=PROVIDER_DEVICES,
            healthy=is_healthy,
            state="unavailable" if not is_healthy else "ok",
            severity="error" if not is_healthy else "ok",
            reason=None,
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
                "device_url": f"/config/devices/device/{device_id}",
            },
        )
