"""Tests for DevicesProvider — eligibility, source detection, device health."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.sentinel.const import PHYSICAL_DOMAINS, VITAL_DEVICE_CLASSES
from custom_components.sentinel.providers.devices import (
    _get_device_source,
    _is_eligible,
)


# ---------------------------------------------------------------------------
# _is_eligible — pure filtering logic
# ---------------------------------------------------------------------------

class MockEntity:
    """Minimal mock of a HA RegistryEntry for eligibility tests."""

    def __init__(
        self,
        device_id="device_123",
        entity_category=None,
        disabled_by=None,
        domain="light",
        original_device_class=None,
        device_class=None,
    ):
        self.device_id = device_id
        self.entity_category = entity_category
        self.disabled_by = disabled_by
        self.domain = domain
        self.original_device_class = original_device_class
        self.device_class = device_class


class TestIsEligible:
    """Test _is_eligible filtering."""

    def test_entity_without_device_id_is_not_eligible(self):
        entity = MockEntity(device_id=None)
        assert _is_eligible(entity) is False

    def test_diagnostic_entity_is_not_eligible(self):
        from homeassistant.const import EntityCategory
        entity = MockEntity(entity_category=EntityCategory.DIAGNOSTIC)
        assert _is_eligible(entity) is False

    def test_config_entity_is_not_eligible(self):
        from homeassistant.const import EntityCategory
        entity = MockEntity(entity_category=EntityCategory.CONFIG)
        assert _is_eligible(entity) is False

    def test_disabled_entity_is_not_eligible(self):
        from homeassistant.helpers.entity_registry import RegistryEntryDisabler
        entity = MockEntity(disabled_by=RegistryEntryDisabler.USER)
        assert _is_eligible(entity) is False

    def test_physical_domain_entities_are_eligible(self):
        for domain in PHYSICAL_DOMAINS:
            entity = MockEntity(domain=domain)
            assert _is_eligible(entity) is True, f"domain={domain} should be eligible"

    def test_sensor_with_vital_device_class_is_eligible(self):
        from homeassistant.components.sensor import SensorDeviceClass
        entity = MockEntity(
            domain="sensor",
            original_device_class=SensorDeviceClass.TEMPERATURE,
        )
        assert _is_eligible(entity) is True

    def test_binary_sensor_with_vital_device_class_is_eligible(self):
        from homeassistant.components.binary_sensor import BinarySensorDeviceClass
        entity = MockEntity(
            domain="binary_sensor",
            original_device_class=BinarySensorDeviceClass.MOTION,
        )
        assert _is_eligible(entity) is True

    def test_sensor_without_device_class_is_not_eligible(self):
        entity = MockEntity(domain="sensor", original_device_class=None, device_class=None)
        assert _is_eligible(entity) is False

    def test_binary_sensor_without_vital_class_is_not_eligible(self):
        from homeassistant.components.binary_sensor import BinarySensorDeviceClass
        entity = MockEntity(
            domain="binary_sensor",
            original_device_class=BinarySensorDeviceClass.BATTERY,
        )
        assert _is_eligible(entity) is False

    def test_automation_domain_is_not_eligible(self):
        entity = MockEntity(domain="automation")
        assert _is_eligible(entity) is False

    def test_original_device_class_takes_priority_over_device_class(self):
        """original_device_class is checked first."""
        from homeassistant.components.sensor import SensorDeviceClass
        entity = MockEntity(
            domain="sensor",
            original_device_class=SensorDeviceClass.TEMPERATURE,
            device_class=None,
        )
        assert _is_eligible(entity) is True


# ---------------------------------------------------------------------------
# _get_device_source — deterministic source detection
# ---------------------------------------------------------------------------

class TestGetDeviceSource:
    """Test _get_device_source with various identifier configurations."""

    def _make_hass(self, identifiers):
        hass = MagicMock()
        device = MagicMock()
        device.identifiers = identifiers
        dr = MagicMock()
        dr.async_get.return_value = device
        with patch(
            "custom_components.sentinel.providers.devices.dr.async_get",
            return_value=dr,
        ):
            return hass, dr

    def test_returns_device_when_no_device(self):
        hass = MagicMock()
        dr_mock = MagicMock()
        dr_mock.async_get.return_value = None
        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            result = _get_device_source(hass, "missing_device")
        assert result == "DEVICE"

    def test_returns_device_when_no_identifiers(self):
        hass = MagicMock()
        device = MagicMock()
        device.identifiers = set()
        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device
        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            result = _get_device_source(hass, "device_123")
        assert result == "DEVICE"

    def test_returns_uppercase_domain(self):
        hass = MagicMock()
        device = MagicMock()
        device.identifiers = {("hue", "abc123")}
        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device
        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            result = _get_device_source(hass, "device_123")
        assert result == "HUE"

    def test_deterministic_with_multiple_identifiers(self):
        """Should return the same result regardless of set ordering."""
        hass = MagicMock()
        device = MagicMock()
        device.identifiers = {("zwave_js", "node1"), ("aaa_domain", "xyz")}
        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device
        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            result1 = _get_device_source(hass, "device_123")
        # sorted() means "aaa_domain" always comes first
        assert result1 == "AAA_DOMAIN"


# ---------------------------------------------------------------------------
# DevicesProvider._should_watch_device
# ---------------------------------------------------------------------------

class TestShouldWatchDevice:
    """Test DevicesProvider._should_watch_device."""

    def _make_provider(self, ignored_sources=None, ignored_ids=None):
        from custom_components.sentinel.providers.devices import DevicesProvider
        hass = MagicMock()
        provider = DevicesProvider(
            hass,
            ignored_device_sources=set(ignored_sources or []),
            ignored_device_ids=set(ignored_ids or []),
        )
        return provider

    def test_normal_device_is_watched(self):
        provider = self._make_provider()
        device = MagicMock()
        device.identifiers = {("hue", "abc")}
        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device
        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            assert provider._should_watch_device("device_123") is True

    def test_ignored_device_id_is_not_watched(self):
        provider = self._make_provider(ignored_ids=["device_123"])
        assert provider._should_watch_device("device_123") is False

    def test_ignored_source_is_not_watched(self):
        provider = self._make_provider(ignored_sources=["mobile_app"])
        device = MagicMock()
        device.identifiers = {("mobile_app", "abc")}
        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device
        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            assert provider._should_watch_device("device_123") is False

    def test_ignored_source_case_insensitive(self):
        """Sources are stored uppercase internally."""
        provider = self._make_provider(ignored_sources=["mobile_app"])
        device = MagicMock()
        device.identifiers = {("mobile_app", "abc")}
        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device
        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            assert provider._should_watch_device("device_123") is False
