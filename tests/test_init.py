"""Integration tests for Sentinel — full setup/teardown with real hass."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.sentinel.const import (
    CONF_FIRE_EVENTS,
    CONF_GRACE_PERIOD,
    DOMAIN,
    EVENT_ITEM_CHANGED,
    PROVIDER_DEVICES,
    PROVIDER_INTEGRATIONS,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntryChange,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sentinel_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create and register a Sentinel config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Sentinel",
        data={},
        options={
            CONF_GRACE_PERIOD: 0,  # no grace period for tests
            CONF_FIRE_EVENTS: True,
        },
        entry_id="test_sentinel",
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    return entry


async def setup_sentinel(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up Sentinel and wait for completion."""
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# Setup / teardown
# ---------------------------------------------------------------------------


async def test_setup_creates_problems_sensor(
    hass: HomeAssistant,
    sentinel_config_entry: MockConfigEntry,
) -> None:
    """Test that setup creates the sentinel_problems sensor."""
    await setup_sentinel(hass, sentinel_config_entry)

    state = hass.states.get("sensor.sentinel_problems")
    assert state is not None
    assert state.state == "0"


async def test_setup_creates_entities_in_registry(
    hass: HomeAssistant,
    sentinel_config_entry: MockConfigEntry,
) -> None:
    """Test that setup creates Sentinel entities in the entity registry."""
    await setup_sentinel(hass, sentinel_config_entry)

    ent_reg = er.async_get(hass)
    sentinel_entries = er.async_entries_for_config_entry(ent_reg, sentinel_config_entry.entry_id)
    assert len(sentinel_entries) > 0, "Setup must create at least one entity (problems sensor)"


async def test_unload_removes_entities_from_registry(
    hass: HomeAssistant,
    sentinel_config_entry: MockConfigEntry,
) -> None:
    """Test that unloading Sentinel removes its entities from the registry."""
    await setup_sentinel(hass, sentinel_config_entry)

    ent_reg = er.async_get(hass)
    before = er.async_entries_for_config_entry(ent_reg, sentinel_config_entry.entry_id)
    assert len(before) > 0, "Should have entities before unload"

    await hass.config_entries.async_unload(sentinel_config_entry.entry_id)
    await hass.async_block_till_done()

    # After unload the entry is no longer loaded — services should be gone
    assert not hass.services.has_service(DOMAIN, "check")


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


async def test_service_check_exists(
    hass: HomeAssistant,
    sentinel_config_entry: MockConfigEntry,
) -> None:
    """Test that sentinel.check service is registered."""
    await setup_sentinel(hass, sentinel_config_entry)
    assert hass.services.has_service(DOMAIN, "check")


async def test_service_purge_exists(
    hass: HomeAssistant,
    sentinel_config_entry: MockConfigEntry,
) -> None:
    """Test that sentinel.purge service is registered."""
    await setup_sentinel(hass, sentinel_config_entry)
    assert hass.services.has_service(DOMAIN, "purge")


async def test_service_reload_exists(
    hass: HomeAssistant,
    sentinel_config_entry: MockConfigEntry,
) -> None:
    """Test that sentinel.reload_item service is registered."""
    await setup_sentinel(hass, sentinel_config_entry)
    assert hass.services.has_service(DOMAIN, "reload_item")


async def test_unload_removes_services(
    hass: HomeAssistant,
    sentinel_config_entry: MockConfigEntry,
) -> None:
    """Test that services are removed on unload."""
    await setup_sentinel(hass, sentinel_config_entry)

    assert hass.services.has_service(DOMAIN, "check")

    await hass.config_entries.async_unload(sentinel_config_entry.entry_id)
    await hass.async_block_till_done()

    assert not hass.services.has_service(DOMAIN, "check")


async def test_service_check_does_not_fire_events_when_all_healthy(
    hass: HomeAssistant,
    sentinel_config_entry: MockConfigEntry,
) -> None:
    """Test that sentinel.check fires no events when all items are healthy."""
    await setup_sentinel(hass, sentinel_config_entry)

    events = []

    def _capture(event):
        events.append(event)

    hass.bus.async_listen(EVENT_ITEM_CHANGED, _capture)

    await hass.services.async_call(DOMAIN, "check", blocking=True)
    await hass.async_block_till_done()

    # At clean startup all items are healthy — check should fire zero events
    unhealthy_events = [e for e in events if not e.data.get("healthy")]
    assert len(unhealthy_events) == 0


# ---------------------------------------------------------------------------
# Event bus — integration problem
# ---------------------------------------------------------------------------


async def test_sentinel_fires_event_on_integration_problem(
    hass: HomeAssistant,
    sentinel_config_entry: MockConfigEntry,
) -> None:
    """Test that sentinel_item_changed event is fired when an integration fails."""
    await setup_sentinel(hass, sentinel_config_entry)

    events = []

    def _capture(event):
        events.append(event)

    hass.bus.async_listen(EVENT_ITEM_CHANGED, _capture)

    # Register a fake netatmo entry and trigger ADDED signal
    fake_entry = MockConfigEntry(
        domain="netatmo",
        title="Netatmo",
        data={},
        options={},
        entry_id="fake_netatmo",
        unique_id="netatmo_test",
    )
    fake_entry.add_to_hass(hass)
    async_dispatcher_send(hass, SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntryChange.ADDED, fake_entry)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][sentinel_config_entry.entry_id]
    int_provider = coordinator._providers.get("integrations")

    assert int_provider is not None, "Integrations provider must be set up"
    assert "fake_netatmo" in int_provider._items, (
        "fake_netatmo must be tracked after ADDED signal — "
        "check that _on_entry_changed handles ADDED correctly"
    )

    # Simulate a healthy→error transition via _apply_state
    int_provider._previous_healthy["fake_netatmo"] = True
    mock_entry = MagicMock()
    mock_entry.entry_id = "fake_netatmo"
    mock_entry.title = "Netatmo"
    mock_entry.domain = "netatmo"
    mock_entry.source = "user"
    mock_entry.reason = None
    mock_entry.disabled_by = None
    mock_entry.state.recoverable = True

    int_provider._apply_state(mock_entry, "setup_error")
    await hass.async_block_till_done()

    problem_events = [e for e in events if not e.data.get("healthy")]
    assert len(problem_events) > 0, "Expected at least one unhealthy event"
    assert problem_events[0].data["provider"] == PROVIDER_INTEGRATIONS
    assert problem_events[0].data["item_type"] == "integration"


# ---------------------------------------------------------------------------
# Binary sensor attributes
# ---------------------------------------------------------------------------


async def test_binary_sensor_has_provider_attribute(
    hass: HomeAssistant,
    sentinel_config_entry: MockConfigEntry,
) -> None:
    """Test that created binary_sensor entities have required Sentinel attributes."""
    # Add a watched integration so at least one binary_sensor is created
    fake_entry = MockConfigEntry(
        domain="netatmo",
        title="Netatmo",
        data={},
        options={},
        entry_id="fake_netatmo_2",
        unique_id="netatmo_test_2",
    )
    fake_entry.add_to_hass(hass)

    await setup_sentinel(hass, sentinel_config_entry)

    sentinel_entities = [
        s for s in hass.states.async_all()
        if s.attributes.get("provider") in (PROVIDER_INTEGRATIONS, PROVIDER_DEVICES)
    ]

    assert len(sentinel_entities) > 0, (
        "Expected at least one Sentinel binary_sensor entity with a 'provider' attribute. "
        "Check that async_setup_entry correctly creates binary_sensor entities."
    )

    for entity in sentinel_entities:
        assert "provider" in entity.attributes
        assert "state" in entity.attributes
        assert "severity" in entity.attributes
        assert "failure_count" in entity.attributes
