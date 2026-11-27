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
from homeassistant.util import slugify

from .const import DOMAIN, PROVIDER_APPS, PROVIDER_DEVICES, PROVIDER_INTEGRATIONS, SIGNAL_SENTINEL_UPDATE
from .coordinator import SentinelCoordinator
from .entity_base import sentinel_device_info
from .event_payload import public_item_name
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
        if label_reg.async_get_label(label_id) is not None:
            continue
        name = _LABEL_DEFINITIONS.get(label_id, label_id)
        existing = label_reg.async_get_label_by_name(name)
        if existing is not None:
            continue
        with contextlib.suppress(Exception):
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
    if not coordinator.expose_details:
        registry = er.async_get(hass)
        for entity in entities:
            _neutralize_generated_entity_id(registry, entity)
    async_add_entities(entities)

    # Listen for new items being added dynamically
    known_ids: set[str] = {e.unique_id for e in entities}

    @callback
    def _handle_update(item: HealthItem) -> None:
        """Add entity for newly discovered items."""
        uid = f"{DOMAIN}_{item.id}"
        if uid not in known_ids:
            known_ids.add(uid)
            entity = SentinelBinarySensor(coordinator, item)
            if not coordinator.expose_details:
                _neutralize_generated_entity_id(er.async_get(hass), entity)
            async_add_entities([entity])

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_SENTINEL_UPDATE, _handle_update)
    )


@callback
def _neutralize_generated_entity_id(
    registry: er.EntityRegistry, entity: SentinelBinarySensor,
) -> None:
    """Neutralize old generated IDs without rewriting user-customized IDs."""
    entity_id = registry.async_get_entity_id("binary_sensor", DOMAIN, entity.unique_id)
    if entity_id is None or (entry := registry.async_get(entity_id)) is None:
        return
    if entry.name is not None or not entry.original_name:
        return
    generated_id = f"binary_sensor.{slugify(f'Sentinel {entry.original_name}')}"
    suffix = entity_id.removeprefix(f"{generated_id}_")
    if entity_id != generated_id and not (
        entity_id.startswith(f"{generated_id}_") and suffix.isdigit()
    ):
        return
    neutral_id = f"binary_sensor.sentinel_{entity._item.provider}_{slugify(entity._item.id)}"
    candidate = neutral_id
    index = 2
    while registry.async_get(candidate) is not None and candidate != entity_id:
        candidate = f"{neutral_id}_{index}"
        index += 1
    if candidate != entity_id:
        registry.async_update_entity(entity_id, new_entity_id=candidate)


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
        name = public_item_name(item, expose_details=coordinator.expose_details)
        self._attr_name = f"{name} ({domain})" if domain else name

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
        if self._coordinator.expose_details and self._item.reason:
            attrs["reason"] = self._item.reason
        if self._coordinator.expose_details:
            attrs.update(self._item.extra)
        else:
            # Do not publish entity IDs derived from user-provided names.
            attrs.update({
                key: value for key, value in self._item.extra.items()
                if key in {"domain", "entry_id", "source", "disabled_by",
                           "device_id", "device_url", "slug"}
            })
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
