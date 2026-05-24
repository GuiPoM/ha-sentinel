"""Tests for SentinelCoordinator — event firing, noise suppression."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from custom_components.sentinel.const import (
    CONF_FIRE_EVENTS,
    EVENT_ITEM_CHANGED,
    PROVIDER_DEVICES,
    PROVIDER_INTEGRATIONS,
)
from custom_components.sentinel.coordinator import SentinelCoordinator
from custom_components.sentinel.providers.integrations import IntegrationsProvider


class TestDeviceIntegrationHasProblem:
    """Test coordinator._device_integration_has_problem noise suppression."""

    def _make_coordinator(self, integration_items=None):
        items = integration_items or {}
        hass = MagicMock()
        coordinator = SentinelCoordinator(hass, {})

        # Use a real IntegrationsProvider instance so isinstance() check passes
        int_provider = IntegrationsProvider(hass)
        int_provider._items = items
        coordinator._providers[PROVIDER_INTEGRATIONS] = int_provider

        return coordinator, hass

    def test_no_problem_when_no_providers(self):
        hass = MagicMock()
        coordinator = SentinelCoordinator(hass, {})
        device = MagicMock()
        device.config_entries = ["entry1"]
        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device
        with patch("custom_components.sentinel.coordinator.dr.async_get", return_value=dr_mock):
            assert coordinator._device_integration_has_problem("device_123") is False

    def test_no_problem_when_device_not_found(self):
        coordinator, _ = self._make_coordinator()
        dr_mock = MagicMock()
        dr_mock.async_get.return_value = None
        with patch("custom_components.sentinel.coordinator.dr.async_get", return_value=dr_mock):
            assert coordinator._device_integration_has_problem("missing") is False

    def test_no_problem_when_integration_healthy(self):
        healthy_item = MagicMock()
        healthy_item.healthy = True

        coordinator, _ = self._make_coordinator({"entry1": healthy_item})
        device = MagicMock()
        device.config_entries = ["entry1"]
        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device
        with patch("custom_components.sentinel.coordinator.dr.async_get", return_value=dr_mock):
            assert coordinator._device_integration_has_problem("device_123") is False

    def test_problem_when_integration_unhealthy(self):
        unhealthy_item = MagicMock()
        unhealthy_item.healthy = False

        coordinator, _ = self._make_coordinator({"entry1": unhealthy_item})
        device = MagicMock()
        device.config_entries = ["entry1"]
        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device
        with patch("custom_components.sentinel.coordinator.dr.async_get", return_value=dr_mock):
            assert coordinator._device_integration_has_problem("device_123") is True

    def test_problem_when_any_entry_unhealthy(self):
        """If any config entry is unhealthy, the device is suppressed."""
        healthy_item = MagicMock()
        healthy_item.healthy = True
        unhealthy_item = MagicMock()
        unhealthy_item.healthy = False

        coordinator, _ = self._make_coordinator({
            "entry1": healthy_item,
            "entry2": unhealthy_item,
        })
        device = MagicMock()
        device.config_entries = ["entry1", "entry2"]
        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device
        with patch("custom_components.sentinel.coordinator.dr.async_get", return_value=dr_mock):
            assert coordinator._device_integration_has_problem("device_123") is True


class TestOnItemChanged:
    """Test coordinator._on_item_changed event firing."""

    def _make_item(self, provider=PROVIDER_INTEGRATIONS, healthy=False, state="setup_error"):
        item = MagicMock()
        item.id = "test_item"
        item.provider = provider
        item.name = "Test Item"
        item.healthy = healthy
        item.state = state
        item.severity = "error"
        item.reason = None
        item.failure_count = 1
        item.since = MagicMock()
        item.since.isoformat.return_value = "2026-01-01T00:00:00"
        item.extra = {"domain": "netatmo", "source": "NETATMO"}
        return item

    def test_fires_bus_event_when_fire_events_enabled(self):
        hass = MagicMock()
        coordinator = SentinelCoordinator(hass, {CONF_FIRE_EVENTS: True})
        item = self._make_item()

        coordinator._on_item_changed(item)

        hass.bus.async_fire.assert_called_once()
        call_args = hass.bus.async_fire.call_args
        assert call_args[0][0] == EVENT_ITEM_CHANGED
        data = call_args[0][1]
        assert data["item_id"] == "test_item"
        assert data["healthy"] is False
        assert data["item_type"] == "integration"

    def test_does_not_fire_bus_event_when_disabled(self):
        hass = MagicMock()
        coordinator = SentinelCoordinator(hass, {CONF_FIRE_EVENTS: False})
        item = self._make_item()

        coordinator._on_item_changed(item)

        hass.bus.async_fire.assert_not_called()

    def test_item_type_is_device_for_devices_provider(self):
        hass = MagicMock()
        coordinator = SentinelCoordinator(hass, {CONF_FIRE_EVENTS: True})
        item = self._make_item(provider=PROVIDER_DEVICES)
        item.extra = {"source": "HUE"}

        coordinator._on_item_changed(item)

        data = hass.bus.async_fire.call_args[0][1]
        assert data["item_type"] == "device"

    def test_domain_falls_back_to_source_for_devices(self):
        hass = MagicMock()
        coordinator = SentinelCoordinator(hass, {CONF_FIRE_EVENTS: True})
        item = self._make_item(provider=PROVIDER_DEVICES)
        item.extra = {"domain": "", "source": "HUE"}

        coordinator._on_item_changed(item)

        data = hass.bus.async_fire.call_args[0][1]
        assert data["domain"] == "hue"  # source.lower() as fallback


class TestResetFailureCount:
    """Test fix for issue #24 — reset_failure_count fires bus event."""

    def _make_item(self, item_id="e1", failure_count=3):
        from custom_components.sentinel.providers import HealthItem
        from homeassistant.util import dt as dt_util
        return HealthItem(
            id=item_id,
            name="Netatmo",
            provider=PROVIDER_INTEGRATIONS,
            healthy=False,
            state="setup_error",
            severity="error",
            failure_count=failure_count,
            since=dt_util.utcnow(),
            extra={"domain": "netatmo", "source": "user"},
        )

    def test_reset_failure_count_fires_bus_event(self):
        """After reset, _on_item_changed must be called so bus event is fired."""
        import asyncio
        hass = MagicMock()
        coordinator = SentinelCoordinator(hass, {CONF_FIRE_EVENTS: True})

        item = self._make_item(failure_count=3)
        mock_provider = MagicMock()
        mock_provider.get_item.return_value = item
        coordinator._providers[PROVIDER_INTEGRATIONS] = mock_provider

        asyncio.get_event_loop().run_until_complete(
            coordinator.async_reset_failure_count("e1")
        )

        assert item.failure_count == 0
        hass.bus.async_fire.assert_called_once()
        event_data = hass.bus.async_fire.call_args[0][1]
        assert event_data["item_id"] == "e1"
        assert event_data["failure_count"] == 0
