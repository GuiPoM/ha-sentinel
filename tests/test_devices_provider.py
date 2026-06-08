"""Tests for DevicesProvider — eligibility, source detection, device health."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from custom_components.sentinel.const import PHYSICAL_DOMAINS
from custom_components.sentinel.providers.devices import (
    DevicesProvider,
    _get_device_source,
    _is_eligible,
)

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_registry import RegistryEntryDisabler

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
        entity = MockEntity(entity_category=EntityCategory.DIAGNOSTIC)
        assert _is_eligible(entity) is False

    def test_config_entity_is_not_eligible(self):
        entity = MockEntity(entity_category=EntityCategory.CONFIG)
        assert _is_eligible(entity) is False

    def test_disabled_entity_is_not_eligible(self):
        entity = MockEntity(disabled_by=RegistryEntryDisabler.USER)
        assert _is_eligible(entity) is False

    def test_physical_domain_entities_are_eligible(self):
        for domain in PHYSICAL_DOMAINS:
            entity = MockEntity(domain=domain)
            assert _is_eligible(entity) is True, f"domain={domain} should be eligible"

    def test_sensor_with_vital_device_class_is_eligible(self):
        entity = MockEntity(
            domain="sensor",
            original_device_class=SensorDeviceClass.TEMPERATURE,
        )
        assert _is_eligible(entity) is True

    def test_binary_sensor_with_vital_device_class_is_eligible(self):
        entity = MockEntity(
            domain="binary_sensor",
            original_device_class=BinarySensorDeviceClass.MOTION,
        )
        assert _is_eligible(entity) is True

    def test_sensor_without_device_class_is_not_eligible(self):
        entity = MockEntity(domain="sensor", original_device_class=None, device_class=None)
        assert _is_eligible(entity) is False

    def test_binary_sensor_without_vital_class_is_not_eligible(self):
        entity = MockEntity(
            domain="binary_sensor",
            original_device_class=BinarySensorDeviceClass.BATTERY,
        )
        assert _is_eligible(entity) is False

    def test_automation_domain_is_not_eligible(self):
        entity = MockEntity(domain="automation")
        assert _is_eligible(entity) is False

    def test_original_device_class_takes_priority_over_device_class(self):
        """original_device_class is checked before device_class.

        Set original_device_class to a vital class and device_class to a
        non-vital class. The entity must be eligible — proving that
        original_device_class wins when both are present.
        """
        entity = MockEntity(
            domain="sensor",
            original_device_class=SensorDeviceClass.TEMPERATURE,  # vital
            device_class=SensorDeviceClass.BATTERY,               # not vital
        )
        assert _is_eligible(entity) is True

    def test_non_vital_original_device_class_is_not_eligible_even_if_device_class_is_vital(self):
        """If original_device_class is non-vital, device_class is not consulted."""
        entity = MockEntity(
            domain="sensor",
            original_device_class=SensorDeviceClass.BATTERY,      # not vital
            device_class=SensorDeviceClass.TEMPERATURE,           # vital — but ignored
        )
        assert _is_eligible(entity) is False


# ---------------------------------------------------------------------------
# _get_device_source — deterministic source detection
# ---------------------------------------------------------------------------

class TestGetDeviceSource:
    """Test _get_device_source with various identifier configurations."""

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
        """sorted() ensures aaa_domain always comes first."""
        hass = MagicMock()
        device = MagicMock()
        device.identifiers = {("zwave_js", "node1"), ("aaa_domain", "xyz")}
        dr_mock = MagicMock()
        dr_mock.async_get.return_value = device
        with patch("custom_components.sentinel.providers.devices.dr.async_get", return_value=dr_mock):
            result = _get_device_source(hass, "device_123")
        assert result == "AAA_DOMAIN"


# ---------------------------------------------------------------------------
# DevicesProvider._should_watch_device
# ---------------------------------------------------------------------------

class TestShouldWatchDevice:
    """Test DevicesProvider._should_watch_device.

    In v0.8.0, _should_watch_device is a simple membership check against
    the watched_device_ids set passed at construction (populated from subentries).
    """

    def _make_provider(self, watched_ids=None):
        hass = MagicMock()
        return DevicesProvider(
            hass,
            watched_device_ids=set(watched_ids or []),
        )

    def test_device_in_watched_set_is_watched(self):
        provider = self._make_provider(watched_ids=["device_123"])
        assert provider._should_watch_device("device_123") is True

    def test_device_not_in_watched_set_is_not_watched(self):
        provider = self._make_provider(watched_ids=[])
        assert provider._should_watch_device("device_123") is False

    def test_different_device_is_not_watched(self):
        provider = self._make_provider(watched_ids=["device_456"])
        assert provider._should_watch_device("device_123") is False

    def test_multiple_watched_devices(self):
        provider = self._make_provider(watched_ids=["device_123", "device_456"])
        assert provider._should_watch_device("device_123") is True
        assert provider._should_watch_device("device_456") is True
        assert provider._should_watch_device("device_789") is False
