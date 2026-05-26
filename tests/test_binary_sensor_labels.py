"""Tests for automatic HA label assignment on Sentinel binary_sensor entities."""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, label_registry as lr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sentinel.binary_sensor import (
    LABEL_APP,
    LABEL_DEVICE,
    LABEL_INTEGRATION,
    LABEL_SENTINEL,
    _PROVIDER_LABEL,
    _ensure_labels,
)
from custom_components.sentinel.const import (
    CONF_FIRE_EVENTS,
    CONF_GRACE_PERIOD,
    DOMAIN,
    PROVIDER_APPS,
    PROVIDER_DEVICES,
    PROVIDER_INTEGRATIONS,
)


# ---------------------------------------------------------------------------
# Unit tests — _ensure_labels
# ---------------------------------------------------------------------------

class TestEnsureLabels:
    """Test _ensure_labels creates labels that don't exist."""

    async def test_creates_missing_labels(self, hass: HomeAssistant) -> None:
        """Labels not yet in the registry must be created."""
        label_reg = lr.async_get(hass)
        assert label_reg.async_get_label(LABEL_SENTINEL) is None

        _ensure_labels(hass, {LABEL_SENTINEL})

        assert label_reg.async_get_label(LABEL_SENTINEL) is not None

    async def test_does_not_duplicate_existing_labels(self, hass: HomeAssistant) -> None:
        """If label already exists, _ensure_labels must not raise or duplicate it."""
        label_reg = lr.async_get(hass)
        label_reg.async_create("Sentinel")

        # Should not raise
        _ensure_labels(hass, {LABEL_SENTINEL})

        labels = list(label_reg.async_list_labels())
        sentinel_labels = [entry for entry in labels if entry.label_id == LABEL_SENTINEL]
        assert len(sentinel_labels) == 1

    async def test_creates_all_four_labels(self, hass: HomeAssistant) -> None:
        """All four sentinel labels must be creatable."""
        all_labels = {LABEL_SENTINEL, LABEL_INTEGRATION, LABEL_DEVICE, LABEL_APP}
        _ensure_labels(hass, all_labels)

        label_reg = lr.async_get(hass)
        for label_id in all_labels:
            assert label_reg.async_get_label(label_id) is not None


# ---------------------------------------------------------------------------
# Unit tests — provider → label mapping
# ---------------------------------------------------------------------------

class TestProviderLabelMapping:
    """Test that the provider → label mapping is correct."""

    def test_integrations_maps_to_sentinel_integration(self) -> None:
        assert _PROVIDER_LABEL[PROVIDER_INTEGRATIONS] == LABEL_INTEGRATION

    def test_devices_maps_to_sentinel_device(self) -> None:
        assert _PROVIDER_LABEL[PROVIDER_DEVICES] == LABEL_DEVICE

    def test_apps_maps_to_sentinel_app(self) -> None:
        assert _PROVIDER_LABEL[PROVIDER_APPS] == LABEL_APP


# ---------------------------------------------------------------------------
# Integration tests — label assignment on entity setup
# ---------------------------------------------------------------------------

@pytest.fixture
def sentinel_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create and register a Sentinel config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Sentinel",
        data={},
        options={CONF_GRACE_PERIOD: 0, CONF_FIRE_EVENTS: True},
        entry_id="test_sentinel",
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    return entry


async def _setup_sentinel(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


class TestEntityLabelsAssigned:
    """Test that labels are assigned to binary_sensor entities after setup."""

    async def test_sentinel_label_assigned_to_all_entities(
        self, hass: HomeAssistant, sentinel_config_entry: MockConfigEntry
    ) -> None:
        """Every Sentinel binary_sensor must have the 'sentinel' label."""
        await _setup_sentinel(hass, sentinel_config_entry)

        ent_reg = er.async_get(hass)
        sentinel_entities = [
            e for e in er.async_entries_for_config_entry(ent_reg, sentinel_config_entry.entry_id)
            if e.domain == "binary_sensor"
        ]

        for entry in sentinel_entities:
            assert LABEL_SENTINEL in entry.labels, (
                f"Entity {entry.entity_id} missing label '{LABEL_SENTINEL}'"
            )

    async def test_provider_specific_label_assigned(
        self, hass: HomeAssistant, sentinel_config_entry: MockConfigEntry
    ) -> None:
        """Each binary_sensor must have the provider-specific label."""
        await _setup_sentinel(hass, sentinel_config_entry)

        ent_reg = er.async_get(hass)
        sentinel_entities = [
            e for e in er.async_entries_for_config_entry(ent_reg, sentinel_config_entry.entry_id)
            if e.domain == "binary_sensor"
        ]

        for entry in sentinel_entities:
            provider_labels = {LABEL_INTEGRATION, LABEL_DEVICE, LABEL_APP}
            has_provider_label = bool(entry.labels & provider_labels)
            assert has_provider_label, (
                f"Entity {entry.entity_id} missing a provider-specific label. "
                f"Labels: {entry.labels}"
            )

    async def test_label_registry_populated(
        self, hass: HomeAssistant, sentinel_config_entry: MockConfigEntry
    ) -> None:
        """After setup, sentinel labels must exist in the label registry."""
        await _setup_sentinel(hass, sentinel_config_entry)

        label_reg = lr.async_get(hass)
        assert label_reg.async_get_label(LABEL_SENTINEL) is not None
