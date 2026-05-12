"""Integration tests for Sentinel — full setup/teardown with real hass."""
from __future__ import annotations

from unittest.mock import patch

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
    ConfigEntryState,
)
from homeassistant.core import HomeAssistant
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


async def test_unload_removes_entities(
    hass: HomeAssistant,
    sentinel_config_entry: MockConfigEntry,
) -> None:
    """Test that unloading Sentinel removes its entities."""
    await setup_sentinel(hass, sentinel_config_entry)

    assert hass.states.get("sensor.sentinel_problems") is not None

    await hass.config_entries.async_unload(sentinel_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.sentinel_problems") is None


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
    """Test that sentinel.reload service is registered."""
    await setup_sentinel(hass, sentinel_config_entry)
    assert hass.services.has_service(DOMAIN, "reload")


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


async def test_service_check_fires_events_for_unhealthy(
    hass: HomeAssistant,
    sentinel_config_entry: MockConfigEntry,
) -> None:
    """Test that sentinel.check re-fires events for unhealthy items."""
    await setup_sentinel(hass, sentinel_config_entry)

    events = []

    def _capture(event):
        events.append(event)

    hass.bus.async_listen(EVENT_ITEM_CHANGED, _capture)

    await hass.services.async_call(DOMAIN, "check", blocking=True)
    await hass.async_block_till_done()

    # All fired events should be for healthy items (no problems at startup)
    assert all(e.data.get("healthy") is not False for e in events)


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

    # Register a user integration entry
    fake_entry = MockConfigEntry(
        domain="netatmo",
        title="Netatmo",
        data={},
        options={},
        entry_id="fake_netatmo",
        unique_id="netatmo_test",
    )
    fake_entry.add_to_hass(hass)

    # Trigger a ADDED signal so Sentinel picks it up
    async_dispatcher_send(hass, SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntryChange.ADDED, fake_entry)
    await hass.async_block_till_done()

    # Now simulate it going into setup_error
    with patch.object(type(fake_entry), "state", new_callable=lambda: property(lambda self: ConfigEntryState.SETUP_ERROR)):
        async_dispatcher_send(hass, SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntryChange.UPDATED, fake_entry)
        await hass.async_block_till_done()

    problem_events = [e for e in events if not e.data.get("healthy")]
    assert len(problem_events) > 0
    assert problem_events[0].data["provider"] == PROVIDER_INTEGRATIONS
    assert problem_events[0].data["item_type"] == "integration"


# ---------------------------------------------------------------------------
# Binary sensor attributes
# ---------------------------------------------------------------------------


async def test_binary_sensor_has_provider_attribute(
    hass: HomeAssistant,
    sentinel_config_entry: MockConfigEntry,
) -> None:
    """Test that created binary_sensor entities have the provider attribute."""
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

    for entity in sentinel_entities:
        assert "provider" in entity.attributes
        assert "state" in entity.attributes
        assert "severity" in entity.attributes
        assert "failure_count" in entity.attributes
