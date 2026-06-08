"""Tests for DevicesProvider — _build_device_item, _async_evaluate_device, noise suppression."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from custom_components.sentinel.const import PROVIDER_DEVICES
from custom_components.sentinel.providers import HealthItem
from custom_components.sentinel.providers.devices import DevicesProvider

from homeassistant.util import dt as dt_util


def _make_hass():
    """Create a minimal mock hass."""
    return MagicMock()


def _make_device(device_id="device_123", name="Bandeau", identifiers=None):
    """Create a mock device registry entry."""
    device = MagicMock()
    device.name = name
    device.name_by_user = None
    device.identifiers = identifiers or {("hue", "abc")}
    return device


def _make_entity(entity_id="light.bandeau", device_id="device_123"):
    """Create a mock entity registry entry."""
    entity = MagicMock()
    entity.entity_id = entity_id
    entity.device_id = device_id
    return entity


def _make_state(entity_id="light.bandeau", state="off", attributes=None):
    """Create a mock HA state."""
    s = MagicMock()
    s.state = state
    s.attributes = attributes or {}
    return s


def _make_provider(hass=None, watched_ids=None):
    """Create a DevicesProvider with a mock hass."""
    if hass is None:
        hass = _make_hass()
    return DevicesProvider(hass, watched_device_ids=set(watched_ids or []))


def _patch_registries(provider, device, entities):
    """Patch dr and er for a provider test."""
    dr_mock = MagicMock()
    dr_mock.async_get.return_value = device

    er_mock = MagicMock()
    er_mock.entities.values.return_value = entities

    return (
        patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock),
        patch("custom_components.sentinel.providers.devices.er.async_get", return_value=er_mock),
    )


# ---------------------------------------------------------------------------
# _build_device_item — health determination
# ---------------------------------------------------------------------------

class TestBuildDeviceItem:
    """Test DevicesProvider._build_device_item."""

    def test_all_entities_ok_produces_healthy_item(self):
        hass = _make_hass()
        provider = _make_provider(hass)
        device = _make_device()
        entity = _make_entity()

        hass.states.get.return_value = _make_state(state="off")

        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device

        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            item = provider._build_device_item("device_123", [entity])

        assert item.healthy is True
        assert item.state == "ok"
        assert item.severity == "ok"
        assert item.extra["unavailable_entities"] == []

    def test_unavailable_entity_produces_unhealthy_item(self):
        hass = _make_hass()
        provider = _make_provider(hass)
        device = _make_device()
        entity = _make_entity()

        hass.states.get.return_value = _make_state(state="unavailable")

        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device

        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            item = provider._build_device_item("device_123", [entity])

        assert item.healthy is False
        assert item.state == "unavailable"
        assert item.severity == "error"
        assert "light.bandeau" in item.extra["unavailable_entities"]

    def test_partial_unavailability_makes_device_unhealthy(self):
        """Even one unavailable entity makes the device unhealthy."""
        hass = _make_hass()
        provider = _make_provider(hass)
        device = _make_device()
        entity_ok = _make_entity(entity_id="light.bandeau_1")
        entity_unavail = _make_entity(entity_id="light.bandeau_2")

        def get_state(entity_id):
            if entity_id == "light.bandeau_2":
                return _make_state(state="unavailable")
            return _make_state(state="off")

        hass.states.get.side_effect = get_state

        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device

        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            item = provider._build_device_item("device_123", [entity_ok, entity_unavail])

        assert item.healthy is False
        assert "light.bandeau_2" in item.extra["unavailable_entities"]
        assert "light.bandeau_1" not in item.extra["unavailable_entities"]

    def test_restored_state_is_skipped(self):
        """Entities with restored=True are transient — not counted as unavailable."""
        hass = _make_hass()
        provider = _make_provider(hass)
        device = _make_device()
        entity = _make_entity()

        hass.states.get.return_value = _make_state(
            state="unavailable",
            attributes={"restored": True},
        )

        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device

        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            item = provider._build_device_item("device_123", [entity])

        assert item.healthy is True
        assert item.extra["unavailable_entities"] == []

    def test_missing_state_is_counted_as_unavailable(self):
        """If HA has no state for an entity, treat as unavailable."""
        hass = _make_hass()
        provider = _make_provider(hass)
        device = _make_device()
        entity = _make_entity()

        hass.states.get.return_value = None  # no state

        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device

        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            item = provider._build_device_item("device_123", [entity])

        assert item.healthy is False
        assert "light.bandeau" in item.extra["unavailable_entities"]

    def test_force_healthy_returns_healthy_regardless(self):
        """force_healthy=True skips state checks."""
        hass = _make_hass()
        provider = _make_provider(hass)
        device = _make_device()
        entity = _make_entity()

        hass.states.get.return_value = _make_state(state="unavailable")

        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device

        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            item = provider._build_device_item("device_123", [entity], force_healthy=True)

        assert item.healthy is True
        assert item.extra["unavailable_entities"] == []

    def test_device_url_in_extra(self):
        hass = _make_hass()
        provider = _make_provider(hass)
        device = _make_device()
        entity = _make_entity()

        hass.states.get.return_value = _make_state(state="off")

        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device

        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            item = provider._build_device_item("device_123", [entity])

        assert item.extra["device_url"] == "/config/devices/device/device_123"

    def test_returns_none_when_device_not_found(self):
        hass = _make_hass()
        provider = _make_provider(hass)

        dr_mock = MagicMock()
        dr_mock.async_get.return_value = None

        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            item = provider._build_device_item("missing_device", [])

        assert item is None


# ---------------------------------------------------------------------------
# _async_evaluate_device — state transitions and failure_count
# ---------------------------------------------------------------------------

class TestAsyncEvaluateDevice:
    """Test DevicesProvider._async_evaluate_device."""

    def _setup_provider_with_device(self, hass, state_value="off"):
        """Helper: provider with one device tracking one entity."""
        provider = _make_provider(hass)
        provider._entity_to_device["light.bandeau"] = "device_123"
        provider._previous_healthy["device_123"] = True

        device = _make_device()
        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device

        er_mock = MagicMock()
        entity = _make_entity()
        er_mock.entities.values.return_value = [entity]

        hass.states.get.return_value = _make_state(state=state_value)

        return provider, dr_mock, er_mock

    def test_healthy_to_unhealthy_increments_failure_count(self):
        hass = _make_hass()
        provider, dr_mock, er_mock = self._setup_provider_with_device(hass, "unavailable")
        on_change = MagicMock()
        provider._on_change = on_change
        provider._integration_problem_checker = lambda _: False

        with (
            patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock),
            patch("custom_components.sentinel.providers.devices.er.async_get", return_value=er_mock),
        ):
            provider._async_evaluate_device("device_123")

        assert provider._items["device_123"].failure_count == 1
        on_change.assert_called_once()

    def test_unhealthy_to_healthy_calls_on_change(self):
        hass = _make_hass()
        provider, dr_mock, er_mock = self._setup_provider_with_device(hass, "off")
        provider._previous_healthy["device_123"] = False  # was unhealthy

        provider._items["device_123"] = HealthItem(
            id="device_123", name="Bandeau", provider=PROVIDER_DEVICES,
            healthy=False, state="unavailable", severity="error",
            failure_count=1, since=dt_util.utcnow(),
        )

        on_change = MagicMock()
        provider._on_change = on_change
        provider._integration_problem_checker = lambda _: False

        with (
            patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock),
            patch("custom_components.sentinel.providers.devices.er.async_get", return_value=er_mock),
        ):
            provider._async_evaluate_device("device_123")

        on_change.assert_called_once()
        assert on_change.call_args[0][0].healthy is True

    def test_noise_suppression_when_integration_has_problem(self):
        """When owning integration is unhealthy, device problem is suppressed."""
        hass = _make_hass()
        provider, dr_mock, er_mock = self._setup_provider_with_device(hass, "unavailable")
        provider._integration_problem_checker = lambda _: True  # integration has problem

        provider._items["device_123"] = HealthItem(
            id="device_123", name="Bandeau", provider=PROVIDER_DEVICES,
            healthy=False, state="unavailable", severity="error",
            failure_count=1, since=dt_util.utcnow(),
        )

        on_change = MagicMock()
        provider._on_change = on_change

        with (
            patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock),
            patch("custom_components.sentinel.providers.devices.er.async_get", return_value=er_mock),
        ):
            provider._async_evaluate_device("device_123")

        # Device suppressed — on_change not called, item forced healthy
        on_change.assert_not_called()
        assert provider._items["device_123"].state == "suppressed"
        assert provider._items["device_123"].healthy is True

    def test_no_change_when_already_healthy(self):
        """If already healthy and stays healthy, on_change is not called."""
        hass = _make_hass()
        provider, dr_mock, er_mock = self._setup_provider_with_device(hass, "off")
        provider._previous_healthy["device_123"] = True

        provider._items["device_123"] = HealthItem(
            id="device_123", name="Bandeau", provider=PROVIDER_DEVICES,
            healthy=True, state="ok", severity="ok",
            failure_count=0, since=dt_util.utcnow(),
        )

        on_change = MagicMock()
        provider._on_change = on_change
        provider._integration_problem_checker = lambda _: False

        with (
            patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock),
            patch("custom_components.sentinel.providers.devices.er.async_get", return_value=er_mock),
        ):
            provider._async_evaluate_device("device_123")

        on_change.assert_not_called()
