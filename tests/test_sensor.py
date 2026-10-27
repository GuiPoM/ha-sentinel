"""Tests for the Recorder-safe global problem sensor attributes."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.json import json_bytes
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sentinel.const import (
    DOMAIN,
    MAX_PROBLEMS_ATTRIBUTE_BYTES,
    PROVIDER_DEVICES,
    SIGNAL_SENTINEL_UPDATE,
)
from custom_components.sentinel.coordinator import SentinelCoordinator
from custom_components.sentinel.providers import HealthItem, HealthProvider
from custom_components.sentinel.sensor import SentinelProblemCountSensor


def make_item(index: int, *, healthy: bool = False) -> HealthItem:
    """Create a monitored item with realistic identifying fields."""
    return HealthItem(
        id=f"device_{index}",
        name=f"Device {index}",
        provider=PROVIDER_DEVICES,
        healthy=healthy,
        state="ok" if healthy else "unavailable",
        reason=None if healthy else "Device unavailable",
        since=dt_util.utcnow(),
    )


@pytest.fixture
def coordinator(hass: HomeAssistant) -> SentinelCoordinator:
    """Use the real coordinator's item aggregation."""
    coordinator = SentinelCoordinator(hass, {})
    provider = Mock(spec=HealthProvider)
    provider.get_items.return_value = {}
    coordinator._providers[PROVIDER_DEVICES] = provider
    return coordinator


def set_items(coordinator: SentinelCoordinator, items: list[HealthItem]) -> None:
    """Replace the provider's items for a sensor update."""
    coordinator._providers[PROVIDER_DEVICES].get_items.return_value = {
        item.id: item for item in items
    }


def make_items_until_truncated(coordinator: SentinelCoordinator) -> list[HealthItem]:
    """Create short problems until the serialized payload reaches its budget."""
    items: list[HealthItem] = []
    sensor = SentinelProblemCountSensor(coordinator, "sentinel_entry")
    while not sensor.extra_state_attributes["problems_truncated"]:
        items.append(make_item(len(items)))
        set_items(coordinator, items)
    return items


def test_problem_attributes_use_size_budget_for_short_problems(
    coordinator: SentinelCoordinator,
) -> None:
    """Short problems fill the size budget instead of an arbitrary count limit."""
    items = make_items_until_truncated(coordinator)
    sensor = SentinelProblemCountSensor(coordinator, "sentinel_entry")

    attributes = sensor.extra_state_attributes

    assert sensor.native_value == len(items)
    assert attributes["problems_total"] == len(items)
    assert attributes["problems_truncated"] is True
    assert 0 < len(attributes["problems"]) < len(items)
    assert len(json_bytes(attributes)) <= MAX_PROBLEMS_ATTRIBUTE_BYTES


def test_reason_is_truncated_to_fill_remaining_budget(
    coordinator: SentinelCoordinator,
) -> None:
    """A long reason is shortened and explicitly marked when needed."""
    items = [make_item(0), make_item(1)]
    items[1].reason = "important detail " * 2000
    set_items(coordinator, items)
    sensor = SentinelProblemCountSensor(coordinator, "sentinel_entry")

    attributes = sensor.extra_state_attributes

    assert attributes["problems_total"] == 2
    assert attributes["problems_truncated"] is False
    assert len(attributes["problems"]) == 2
    assert "reason_truncated" not in attributes["problems"][0]
    assert attributes["problems"][1]["reason_truncated"] is True
    assert attributes["problems"][1]["reason"].startswith("important detail")
    assert len(json_bytes(attributes)) <= MAX_PROBLEMS_ATTRIBUTE_BYTES


def test_oversized_reason_does_not_hide_later_problems(
    coordinator: SentinelCoordinator,
) -> None:
    """A large reason is trimmed instead of suppressing later useful entries."""
    items = [make_item(0), make_item(1), make_item(2)]
    items[1].reason = "x" * 100_000
    set_items(coordinator, items)
    sensor = SentinelProblemCountSensor(coordinator, "sentinel_entry")

    attributes = sensor.extra_state_attributes

    assert attributes["problems_total"] == 3
    assert attributes["problems_truncated"] is False
    assert len(attributes["problems"]) == 3
    assert attributes["problems"][1]["reason_truncated"] is True
    assert attributes["problems"][2]["id"] == "device_2"


def test_payload_stops_when_minimum_entry_cannot_fit(
    coordinator: SentinelCoordinator,
) -> None:
    """The list stops safely if fixed fields alone cannot fit."""
    items = [make_item(0)]
    items[0].name = "x" * 20_000
    set_items(coordinator, items)
    sensor = SentinelProblemCountSensor(coordinator, "sentinel_entry")

    attributes = sensor.extra_state_attributes

    assert attributes["problems"] == []
    assert attributes["problems_total"] == 1
    assert attributes["problems_truncated"] is True
    assert len(json_bytes(attributes)) <= MAX_PROBLEMS_ATTRIBUTE_BYTES


@pytest.mark.parametrize("options", [{}, {"fire_events": False}])
async def test_published_sensor_updates(
    hass: HomeAssistant,
    options: dict,
) -> None:
    """The published sensor refreshes its totals and truncation state."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    items: list[HealthItem] = []
    sensor = SentinelProblemCountSensor(coordinator, "sentinel_entry")
    while not sensor.extra_state_attributes["problems_truncated"]:
        item = make_item(len(items))
        items.append(item)
        coordinator._providers[PROVIDER_DEVICES]._items = {
            current.id: current for current in items
        }
    async_dispatcher_send(hass, SIGNAL_SENTINEL_UPDATE, items[-1])
    await hass.async_block_till_done()

    state = hass.states.get("sensor.sentinel_problems")
    assert state is not None
    assert state.state == str(len(items))
    assert state.attributes["problems_total"] == len(items)
    assert state.attributes["problems_truncated"] is True
    assert 0 < len(state.attributes["problems"]) < len(items)
    assert len(json_bytes(dict(state.attributes))) < 16 * 1024

    for item in items:
        item.healthy = True
    async_dispatcher_send(hass, SIGNAL_SENTINEL_UPDATE, items[-1])
    await hass.async_block_till_done()

    state = hass.states.get("sensor.sentinel_problems")
    assert state.state == "0"
    assert state.attributes["problems"] == []
    assert state.attributes["problems_total"] == 0
    assert state.attributes["problems_truncated"] is False
