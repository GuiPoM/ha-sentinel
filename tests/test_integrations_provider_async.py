"""Tests for IntegrationsProvider — _build_item, _apply_state, failure_count."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.sentinel.const import PROVIDER_INTEGRATIONS
from custom_components.sentinel.providers import HealthItem
from custom_components.sentinel.providers.integrations import (
    IntegrationsProvider,
    _entry_state_str,
)

from homeassistant.config_entries import ConfigEntryState
from homeassistant.util import dt as dt_util


def _make_entry(
    entry_id="entry_1",
    title="Netatmo",
    domain="netatmo",
    source="user",
    state_value="loaded",
    reason=None,
    recoverable=True,
):
    """Create a minimal mock ConfigEntry."""

    state_map = {
        "loaded": ConfigEntryState.LOADED,
        "setup_error": ConfigEntryState.SETUP_ERROR,
        "setup_retry": ConfigEntryState.SETUP_RETRY,
        "migration_error": ConfigEntryState.MIGRATION_ERROR,
        "failed_unload": ConfigEntryState.FAILED_UNLOAD,
        "not_loaded": ConfigEntryState.NOT_LOADED,
        "setup_in_progress": ConfigEntryState.SETUP_IN_PROGRESS,
        "unload_in_progress": ConfigEntryState.UNLOAD_IN_PROGRESS,
    }
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.title = title
    entry.domain = domain
    entry.source = source
    entry.state = state_map.get(state_value, ConfigEntryState.LOADED)
    entry.state.recoverable = recoverable
    entry.reason = reason
    entry.disabled_by = None
    return entry


def _make_provider(hass=None, excluded=None, extra=None):
    """Create a DevicesProvider with a mock hass."""
    if hass is None:
        hass = MagicMock()
    return IntegrationsProvider(
        hass,
        excluded_entry_ids=set(excluded or []),
        extra_entry_ids=set(extra or []),
    )


# ---------------------------------------------------------------------------
# _entry_state_str
# ---------------------------------------------------------------------------

class TestEntryStateStr:
    """Test _entry_state_str mapping."""

    def test_loaded_maps_correctly(self):
        entry = _make_entry(state_value="loaded")
        assert _entry_state_str(entry) == "loaded"

    def test_setup_error_maps_correctly(self):
        entry = _make_entry(state_value="setup_error")
        assert _entry_state_str(entry) == "setup_error"

    def test_setup_retry_maps_correctly(self):
        entry = _make_entry(state_value="setup_retry")
        assert _entry_state_str(entry) == "setup_retry"

    def test_not_loaded_maps_correctly(self):
        entry = _make_entry(state_value="not_loaded")
        assert _entry_state_str(entry) == "not_loaded"


# ---------------------------------------------------------------------------
# _build_item
# ---------------------------------------------------------------------------

class TestBuildItem:
    """Test IntegrationsProvider._build_item."""

    def test_healthy_entry_produces_healthy_item(self):
        provider = _make_provider()
        entry = _make_entry(state_value="loaded")
        item = provider._build_item(entry)
        assert item.healthy is True
        assert item.state == "loaded"
        assert item.severity == "ok"
        assert item.provider == PROVIDER_INTEGRATIONS
        assert item.id == "entry_1"
        assert item.name == "Netatmo"

    def test_setup_error_produces_error_item(self):
        provider = _make_provider()
        entry = _make_entry(state_value="setup_error")
        item = provider._build_item(entry)
        assert item.healthy is False
        assert item.state == "setup_error"
        assert item.severity == "error"

    def test_setup_retry_produces_warning_item(self):
        provider = _make_provider()
        entry = _make_entry(state_value="setup_retry")
        item = provider._build_item(entry)
        assert item.healthy is False
        assert item.state == "setup_retry"
        assert item.severity == "warning"

    def test_failure_count_parameter_is_used(self):
        provider = _make_provider()
        entry = _make_entry(state_value="setup_error")
        item = provider._build_item(entry, failure_count=3)
        assert item.failure_count == 3

    def test_extra_contains_domain_and_source(self):
        provider = _make_provider()
        entry = _make_entry(domain="netatmo", source="user")
        item = provider._build_item(entry)
        assert item.extra["domain"] == "netatmo"
        assert item.extra["source"] == "user"

    def test_reason_from_entry(self):
        provider = _make_provider()
        entry = _make_entry(state_value="setup_error", reason="Token expired")
        item = provider._build_item(entry)
        assert item.reason == "Token expired"

    def test_since_preserved_when_health_unchanged(self):
        """If health state is same as existing item, since is preserved."""
        provider = _make_provider()
        entry = _make_entry(state_value="setup_error")
        # First build
        item1 = provider._build_item(entry)
        provider._items[entry.entry_id] = item1
        original_since = item1.since
        # Second build — same health state
        item2 = provider._build_item(entry)
        assert item2.since == original_since

    def test_since_reset_when_health_changes(self):
        """If health state changes, since is reset to now."""
        provider = _make_provider()
        entry_error = _make_entry(state_value="setup_error")
        item_error = provider._build_item(entry_error)
        provider._items[entry_error.entry_id] = item_error

        # Now build with loaded state — health changes
        entry_loaded = _make_entry(state_value="loaded")
        item_loaded = provider._build_item(entry_loaded)
        assert item_loaded.since != item_error.since


# ---------------------------------------------------------------------------
# _apply_state — failure_count and notification
# ---------------------------------------------------------------------------

class TestApplyState:
    """Test IntegrationsProvider._apply_state."""

    def test_failure_count_increments_on_first_failure(self):
        provider = _make_provider()
        on_change = MagicMock()
        provider._on_change = on_change

        entry = _make_entry(entry_id="e1", state_value="setup_error")
        provider._previous_healthy["e1"] = True  # was healthy

        provider._apply_state(entry, "setup_error")

        assert provider._items["e1"].failure_count == 1

    def test_failure_count_does_not_increment_if_already_unhealthy(self):
        """If already unhealthy, failure_count stays the same."""

        provider = _make_provider()
        provider._on_change = MagicMock()

        entry = _make_entry(entry_id="e1", state_value="setup_error")

        # Set up existing item already unhealthy with count=2
        provider._items["e1"] = HealthItem(
            id="e1", name="Netatmo", provider=PROVIDER_INTEGRATIONS,
            healthy=False, state="setup_error", severity="error",
            failure_count=2, since=dt_util.utcnow(),
        )
        provider._previous_healthy["e1"] = False  # already unhealthy

        provider._apply_state(entry, "setup_error")

        assert provider._items["e1"].failure_count == 2

    def test_failure_count_increments_on_recovery_then_new_failure(self):
        """Each new healthy→unhealthy transition increments the count."""

        provider = _make_provider()
        provider._on_change = MagicMock()

        entry_error = _make_entry(entry_id="e1", state_value="setup_error")
        entry_loaded = _make_entry(entry_id="e1", state_value="loaded")

        # First failure
        provider._previous_healthy["e1"] = True
        provider._apply_state(entry_error, "setup_error")
        assert provider._items["e1"].failure_count == 1

        # Recovery
        provider._apply_state(entry_loaded, "loaded")
        assert provider._items["e1"].failure_count == 1  # preserved

        # Second failure
        provider._apply_state(entry_error, "setup_error")
        assert provider._items["e1"].failure_count == 2

    def test_on_change_called_when_health_changes(self):
        on_change = MagicMock()
        provider = _make_provider()
        provider._on_change = on_change

        entry = _make_entry(entry_id="e1", state_value="setup_error")
        provider._previous_healthy["e1"] = True

        provider._apply_state(entry, "setup_error")

        on_change.assert_called_once()
        item = on_change.call_args[0][0]
        assert item.healthy is False

    def test_on_change_not_called_when_health_unchanged(self):
        on_change = MagicMock()
        provider = _make_provider()
        provider._on_change = on_change

        entry = _make_entry(entry_id="e1", state_value="setup_error")
        provider._previous_healthy["e1"] = False  # already unhealthy

        # Add existing item
        provider._items["e1"] = HealthItem(
            id="e1", name="Netatmo", provider=PROVIDER_INTEGRATIONS,
            healthy=False, state="setup_error", severity="error",
            failure_count=1, since=dt_util.utcnow(),
        )

        provider._apply_state(entry, "setup_error")

        on_change.assert_not_called()

    def test_on_change_called_on_recovery(self):
        """Recovery (unhealthy → healthy) triggers on_change."""
        on_change = MagicMock()
        provider = _make_provider()
        provider._on_change = on_change

        entry = _make_entry(entry_id="e1", state_value="loaded")
        provider._previous_healthy["e1"] = False  # was unhealthy

        provider._items["e1"] = HealthItem(
            id="e1", name="Netatmo", provider=PROVIDER_INTEGRATIONS,
            healthy=False, state="setup_error", severity="error",
            failure_count=1, since=dt_util.utcnow(),
        )

        provider._apply_state(entry, "loaded")

        on_change.assert_called_once()
        item = on_change.call_args[0][0]
        assert item.healthy is True
