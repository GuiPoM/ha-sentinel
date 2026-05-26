"""Binary sensor platform for HA Sentinel.

Creates one binary_sensor per monitored item.
device_class=PROBLEM: on=problem detected, off=OK.
"""
from __future__ import annotations

import contextlib
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, label_registry as lr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PROVIDER_APPS, PROVIDER_DEVICES, PROVIDER_INTEGRATIONS, SIGNAL_SENTINEL_UPDATE
from .coordinator import SentinelCoordinator
from .entity_base import sentinel_device_info
from .providers import HealthItem

_LOGGER = logging.getLogger(__name__)

# Label IDs assigned to Sentinel binary_sensor entities
LABEL_SENTINEL = "sentinel"
LABEL_INTEGRATION = "sentinel_integration"
LABEL_DEVICE = "sentinel_device"
LABEL_APP = "sentinel_app"

# Map provider → specific label
_PROVIDER_LABEL: dict[str, str] = {
    PROVIDER_INTEGRATIONS: LABEL_INTEGRATION,
    PROVIDER_DEVICES: LABEL_DEVICE,
    PROVIDER_APPS: LABEL_APP,
}

# Label definitions: label_id → display name
_LABEL_DEFINITIONS: dict[str, str] = {
    LABEL_SENTINEL: "Sentinel",
    LABEL_INTEGRATION: "Sentinel Integration",
    LABEL_DEVICE: "Sentinel Device",
    LABEL_APP: "Sentinel App",
}


@callback
def _ensure_labels(hass: HomeAssistant, label_ids: set[str]) -> None:
    """Create Sentinel labels in the label registry if they don't exist yet."""
    label_reg = lr.async_get(hass)
    for label_id in label_ids:
        if label_reg.async_get_label(label_id) is None:
            name = _LABEL_DEFINITIONS.get(label_id, label_id)
            with contextlib.suppress(ValueError):
                label_reg.async_create(name)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors for all monitored items."""
    coordinator: SentinelCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Create entities for all currently known items
    entities = [
        SentinelBinarySensor(coordinator, item)
        for item in coordinator.get_all_items()
    ]
    async_add_entities(entities)

    # Listen for new items being added dynamically
    known_ids: set[str] = {e.unique_id for e in entities}

    @callback
    def _handle_update(item: HealthItem) -> None:
        """Add entity for newly discovered items."""
        uid = f"{DOMAIN}_{item.id}"
        if uid not in known_ids:
            known_ids.add(uid)
            async_add_entities([SentinelBinarySensor(coordinator, item)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_SENTINEL_UPDATE, _handle_update)
    )


class SentinelBinarySensor(BinarySensorEntity):
    """Binary sensor representing the health of one monitored item.

    is_on=True  → problem detected
    is_on=False → healthy / OK
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: SentinelCoordinator, item: HealthItem) -> None:
        """Initialize the binary sensor."""
        self._coordinator = coordinator
        self._item = item
        self._attr_unique_id = f"{DOMAIN}_{item.id}"
        domain = item.extra.get("domain", "") or item.extra.get("source", "").lower()
        self._attr_name = f"{item.name} ({domain})" if domain else item.name

    @property
    def device_info(self) -> DeviceInfo:
        """Group all entities under a single Sentinel device."""
        return sentinel_device_info()

    @property
    def is_on(self) -> bool:
        """Return True if a problem is detected."""
        return not self._item.healthy

    @property
    def extra_state_attributes(self) -> dict:
        """Return detailed attributes."""
        attrs = {
            "provider": self._item.provider,
            "state": self._item.state,
            "severity": self._item.severity,
            "since": self._item.since.isoformat(),
            "failure_count": self._item.failure_count,
            "can_reload": self._item.can_reload,
        }
        if self._item.reason:
            attrs["reason"] = self._item.reason
        attrs.update(self._item.extra)
        return attrs

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates and assign HA labels when entity is added."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SENTINEL_UPDATE,
                self._handle_update,
            )
        )
        await self._async_assign_labels()

    async def _async_assign_labels(self) -> None:
        """Create and assign sentinel labels to this entity in the registry."""
        provider_label = _PROVIDER_LABEL.get(self._item.provider)
        labels_to_assign = {LABEL_SENTINEL}
        if provider_label:
            labels_to_assign.add(provider_label)

        # Ensure all required labels exist in the label registry
        _ensure_labels(self.hass, labels_to_assign)

        # Assign labels to this entity in the entity registry
        ent_reg = er.async_get(self.hass)
        entity_id = self.entity_id
        if entity_id and (entry := ent_reg.async_get(entity_id)):
            current_labels = entry.labels or set()
            if not labels_to_assign.issubset(current_labels):
                ent_reg.async_update_entity(
                    entity_id,
                    labels=current_labels | labels_to_assign,
                )

    @callback
    def _handle_update(self, item: HealthItem) -> None:
        """Handle update signal — only react to our own item."""
        if item.id == self._item.id:
            self._item = item
            self.async_write_ha_state()
