"""Tests for the bounded global problem sensor attributes."""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.json import json_bytes
from homeassistant.util import dt as dt_util

from custom_components.sentinel.const import (
    CONF_MAX_PROBLEMS,
    DEFAULT_MAX_PROBLEMS,
    DOMAIN,
    MAX_PROBLEMS_ATTRIBUTE_BYTES,
    PROVIDER_APPS,
    PROVIDER_DEVICES,
    PROVIDER_INTEGRATIONS,
    SIGNAL_SENTINEL_UPDATE,
)
from custom_components.sentinel.coordinator import SentinelCoordinator
from custom_components.sentinel.providers import HealthItem, HealthProvider
from custom_components.sentinel.sensor import SentinelProblemCountSensor


def make_item(index: int, *, healthy: bool = False, **kwargs) -> HealthItem:
    """Create a monitored item with realistic identifying fields."""
    return HealthItem(
        id=f"device_{index}",
        name=f"Device {index}",
        provider=PROVIDER_DEVICES,
        healthy=healthy,
        state="ok" if healthy else "unavailable",
        reason=None if healthy else "Device unavailable",
        since=dt_util.utcnow(),
        **kwargs,
    )


@pytest.fixture
def coordinator(hass: HomeAssistant) -> SentinelCoordinator:
    """Use the real coordinator's count and item aggregation."""
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


@pytest.mark.parametrize("count", [0, 3, 50, 51, 173])
def test_problem_list_default_limit(coordinator: SentinelCoordinator, count: int) -> None:
    """Cap only unhealthy items and keep the true count at either side of the limit."""
    items = [make_item(i) for i in range(count)]
    set_items(coordinator, [make_item(-1, healthy=True), *items, make_item(-2, healthy=True)])
    sensor = SentinelProblemCountSensor(coordinator, "sentinel_entry")

    attrs = sensor.extra_state_attributes
    expected = items[:DEFAULT_MAX_PROBLEMS]
    assert sensor.native_value == count
    assert attrs["problems_total"] == count
    assert attrs["problems_truncated"] is (count > DEFAULT_MAX_PROBLEMS)
    assert attrs["problems"] == [
        {
            "id": item.id,
            "name": item.name,
            "provider": item.provider,
            "state": item.state,
            "reason": item.reason,
        }
        for item in expected
    ]


@pytest.mark.parametrize("provider", [PROVIDER_INTEGRATIONS, PROVIDER_DEVICES, PROVIDER_APPS])
def test_problem_attributes_preserve_fields(coordinator: SentinelCoordinator, provider: str) -> None:
    """All providers keep their existing problem fields, including a null reason."""
    item = make_item(0)
    item.provider = provider
    item.reason = None
    set_items(coordinator, [item])
    sensor = SentinelProblemCountSensor(coordinator, "sentinel_entry")

    assert sensor.extra_state_attributes == {
        "problems": [{
            "id": item.id,
            "name": item.name,
            "provider": provider,
            "state": item.state,
            "reason": None,
        }],
        "problems_total": 1,
        "problems_truncated": False,
    }


@pytest.mark.parametrize("text", ["x" * 1000, "é🔌" * 200, '\\"\n\t' * 200])
def test_problem_list_byte_limit(coordinator: SentinelCoordinator, text: str) -> None:
    """Long fields, Unicode and JSON escaping cannot overflow Recorder attributes."""
    items = [make_item(i) for i in range(173)]
    for item in items:
        item.name = text
        item.reason = text
    set_items(coordinator, items)
    sensor = SentinelProblemCountSensor(coordinator, "sentinel_entry", max_problems=1000)

    attrs = sensor.extra_state_attributes
    assert 0 < len(attrs["problems"]) < DEFAULT_MAX_PROBLEMS
    assert attrs["problems_total"] == sensor.native_value == len(items)
    assert attrs["problems_truncated"] is True
    assert len(json.dumps(attrs["problems"]).encode("utf-8")) <= MAX_PROBLEMS_ATTRIBUTE_BYTES
    assert len(json_bytes(attrs)) < 16384
    # The list remains a prefix and fields are never silently shortened.
    assert attrs["problems"][-1]["id"] == items[len(attrs["problems"]) - 1].id
    assert attrs["problems"][0]["name"] == text
    assert attrs["problems"][0]["reason"] == text


def test_single_oversized_problem(coordinator: SentinelCoordinator) -> None:
    """Even one huge error message is safely omitted while preserving the count."""
    item = make_item(0)
    item.reason = "x" * 16384
    set_items(coordinator, [item, make_item(1)])
    sensor = SentinelProblemCountSensor(coordinator, "sentinel_entry")

    assert sensor.native_value == 2
    assert sensor.extra_state_attributes == {
        "problems": [],
        "problems_total": 2,
        "problems_truncated": True,
    }


@pytest.mark.parametrize(
    ("options", "expected_count"),
    [({}, 50), ({CONF_MAX_PROBLEMS: 2}, 2), ({CONF_MAX_PROBLEMS: 75}, 75), ({CONF_MAX_PROBLEMS: 0}, 0)],
)
async def test_published_sensor_updates(
    hass: HomeAssistant, options: dict, expected_count: int
) -> None:
    """Platform setup uses saved options and refreshes totals and flags on recovery."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    items = [make_item(i) for i in range(173)]
    coordinator._providers[PROVIDER_DEVICES]._items = {item.id: item for item in items}
    async_dispatcher_send(hass, SIGNAL_SENTINEL_UPDATE, items[-1])
    await hass.async_block_till_done()

    state = hass.states.get("sensor.sentinel_problems")
    assert state is not None
    assert state.state == "173"
    assert state.attributes["problems_total"] == 173
    assert len(state.attributes["problems"]) == expected_count
    assert state.attributes["problems_truncated"] is True
    assert len(json_bytes(dict(state.attributes))) < 16384

    for item in items:
        item.healthy = True
    async_dispatcher_send(hass, SIGNAL_SENTINEL_UPDATE, items[-1])
    await hass.async_block_till_done()

    state = hass.states.get("sensor.sentinel_problems")
    assert state.state == "0"
    assert state.attributes["problems"] == []
    assert state.attributes["problems_total"] == 0
    assert state.attributes["problems_truncated"] is False
