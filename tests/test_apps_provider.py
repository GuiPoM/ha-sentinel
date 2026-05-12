"""Tests for AppsProvider — state classification, _classify, _update_addon."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from custom_components.sentinel.const import PROVIDER_APPS
from custom_components.sentinel.providers.apps import AppsProvider

# ---------------------------------------------------------------------------
# _classify — pure state → (is_healthy, severity) mapping
# ---------------------------------------------------------------------------


class TestClassify:
    """Test AppsProvider._classify."""

    def _make_provider(self, watch_stopped=False):
        hass = MagicMock()
        return AppsProvider(hass, watch_stopped=watch_stopped)

    def test_started_is_healthy(self):
        provider = self._make_provider()
        healthy, severity = provider._classify("started")
        assert healthy is True
        assert severity == "ok"

    def test_error_is_unhealthy_error(self):
        provider = self._make_provider()
        healthy, severity = provider._classify("error")
        assert healthy is False
        assert severity == "error"

    def test_unknown_is_unhealthy_warning(self):
        provider = self._make_provider()
        healthy, severity = provider._classify("unknown")
        assert healthy is False
        assert severity == "warning"

    def test_stopped_is_healthy_by_default(self):
        """Stopped add-on is ignored by default — intentional stop."""
        provider = self._make_provider(watch_stopped=False)
        healthy, severity = provider._classify("stopped")
        assert healthy is True
        assert severity == "ok"

    def test_stopped_is_warning_when_watch_stopped_enabled(self):
        provider = self._make_provider(watch_stopped=True)
        healthy, severity = provider._classify("stopped")
        assert healthy is False
        assert severity == "warning"

    def test_startup_is_never_a_problem(self):
        """startup is transient — but if somehow passed to _classify it falls through."""
        provider = self._make_provider()
        # startup is filtered before _classify in _async_scan, but
        # _classify should treat it as warning (future-unknown state)
        healthy, severity = provider._classify("startup")
        # startup is not in any known problem set → falls through to warning
        assert healthy is False
        assert severity == "warning"

    def test_unknown_future_state_is_warning(self):
        provider = self._make_provider()
        healthy, severity = provider._classify("some_future_state")
        assert healthy is False
        assert severity == "warning"


# ---------------------------------------------------------------------------
# _get_slug / _get_state / _get_name — dict and object API
# ---------------------------------------------------------------------------


class TestAddonInfoExtraction:
    """Test AppsProvider helper methods for both dict and object addon formats."""

    def _make_provider(self):
        return AppsProvider(MagicMock())

    def test_get_slug_from_dict(self):
        provider = _make_provider()
        assert provider._get_slug({"slug": "mosquitto"}) == "mosquitto"

    def test_get_slug_from_object(self):
        provider = _make_provider()
        addon = MagicMock()
        addon.slug = "zigbee2mqtt"
        assert provider._get_slug(addon) == "zigbee2mqtt"

    def test_get_slug_returns_none_for_missing(self):
        provider = _make_provider()
        assert provider._get_slug({}) is None

    def test_get_state_from_dict(self):
        provider = _make_provider()
        assert provider._get_state({"state": "started"}) == "started"

    def test_get_state_from_object(self):
        provider = _make_provider()
        addon = MagicMock()
        addon.state = "error"
        assert provider._get_state(addon) == "error"

    def test_get_state_normalizes_enum(self):
        """State may be an enum with a .value attribute."""
        provider = _make_provider()
        addon = MagicMock()
        state_enum = MagicMock()
        state_enum.value = "started"
        addon.state = state_enum
        assert provider._get_state(addon) == "started"

    def test_get_name_from_dict(self):
        provider = _make_provider()
        assert provider._get_name({"name": "Mosquitto", "slug": "mosquitto"}) == "Mosquitto"

    def test_get_name_falls_back_to_slug(self):
        provider = _make_provider()
        assert provider._get_name({"slug": "mosquitto"}) == "mosquitto"


def _make_provider():
    return AppsProvider(MagicMock())


# ---------------------------------------------------------------------------
# _update_addon — HealthItem creation and on_change callbacks
# ---------------------------------------------------------------------------


class TestUpdateAddon:
    """Test AppsProvider._update_addon."""

    def _make_provider(self, watch_stopped=False):
        hass = MagicMock()
        provider = AppsProvider(hass, watch_stopped=watch_stopped)
        provider._on_change = MagicMock()
        return provider

    def test_started_addon_creates_healthy_item(self):
        provider = self._make_provider()
        addon = {"slug": "mosquitto", "name": "Mosquitto", "state": "started"}
        provider._update_addon(addon, "mosquitto", "started")

        item = provider._items.get("mosquitto")
        assert item is not None
        assert item.healthy is True
        assert item.state == "started"
        assert item.provider == PROVIDER_APPS
        assert item.can_reload is True
        assert item.extra["slug"] == "mosquitto"

    def test_error_addon_creates_unhealthy_item(self):
        provider = self._make_provider()
        addon = {"slug": "zigbee2mqtt", "name": "Zigbee2MQTT", "state": "error"}
        provider._update_addon(addon, "zigbee2mqtt", "error")

        item = provider._items.get("zigbee2mqtt")
        assert item is not None
        assert item.healthy is False
        assert item.severity == "error"

    def test_on_change_called_on_first_update(self):
        """First time we see an addon, always notify."""
        provider = self._make_provider()
        addon = {"slug": "mosquitto", "name": "Mosquitto", "state": "started"}
        provider._update_addon(addon, "mosquitto", "started")

        provider._on_change.assert_called_once()

    def test_failure_count_increments_on_healthy_to_error(self):
        provider = self._make_provider()
        addon_ok = {"slug": "mosquitto", "name": "Mosquitto", "state": "started"}
        addon_err = {"slug": "mosquitto", "name": "Mosquitto", "state": "error"}

        provider._update_addon(addon_ok, "mosquitto", "started")
        assert provider._items["mosquitto"].failure_count == 0

        provider._on_change.reset_mock()
        provider._update_addon(addon_err, "mosquitto", "error")
        assert provider._items["mosquitto"].failure_count == 1
        provider._on_change.assert_called_once()

    def test_on_change_not_called_when_state_unchanged(self):
        """No notification if health state stays the same."""
        provider = self._make_provider()
        addon = {"slug": "mosquitto", "name": "Mosquitto", "state": "started"}

        provider._update_addon(addon, "mosquitto", "started")
        provider._on_change.reset_mock()

        # Same healthy state — no change
        provider._update_addon(addon, "mosquitto", "started")
        provider._on_change.assert_not_called()

    def test_failure_count_not_incremented_if_already_unhealthy(self):
        provider = self._make_provider()
        addon_err = {"slug": "mosquitto", "name": "Mosquitto", "state": "error"}

        # First failure
        provider._previous_healthy["mosquitto"] = True
        provider._update_addon(addon_err, "mosquitto", "error")
        assert provider._items["mosquitto"].failure_count == 1

        # Second error — already unhealthy, count stays
        provider._update_addon(addon_err, "mosquitto", "error")
        assert provider._items["mosquitto"].failure_count == 1


# ---------------------------------------------------------------------------
# available — hassio detection
# ---------------------------------------------------------------------------


class TestAvailable:
    """Test AppsProvider.available property."""

    def test_available_returns_false_when_not_hassio(self):
        hass = MagicMock()
        provider = AppsProvider(hass)
        with patch("custom_components.sentinel.providers.apps.is_hassio", return_value=False):
            assert provider.available is False

    def test_available_returns_true_when_hassio(self):
        hass = MagicMock()
        provider = AppsProvider(hass)
        with patch("custom_components.sentinel.providers.apps.is_hassio", return_value=True):
            assert provider.available is True
