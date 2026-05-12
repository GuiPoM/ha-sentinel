"""Tests for IntegrationsProvider — filtering, state transitions, failure_count."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.sentinel.const import (
    DOMAIN,
    ERROR_STATES,
    EXCLUDED_DOMAINS,
    EXCLUDED_SOURCES,
    HEALTHY_STATES,
    INACTIVE_STATES,
    TRANSIENT_STATES,
    WARNING_STATES,
)
from custom_components.sentinel.providers.integrations import (
    IntegrationsProvider,
    _get_severity,
    _is_healthy,
    _is_problem,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryDisabler

# ---------------------------------------------------------------------------
# _is_healthy / _is_problem / _get_severity — pure functions
# ---------------------------------------------------------------------------

class TestStateClassification:
    """Test pure state classification functions."""

    def test_loaded_is_healthy(self):
        assert _is_healthy("loaded") is True

    def test_setup_error_is_not_healthy(self):
        assert _is_healthy("setup_error") is False

    def test_setup_retry_is_not_healthy(self):
        assert _is_healthy("setup_retry") is False

    def test_not_loaded_is_not_healthy(self):
        assert _is_healthy("not_loaded") is False

    def test_setup_in_progress_is_not_a_problem(self):
        assert _is_problem("setup_in_progress") is False

    def test_unload_in_progress_is_not_a_problem(self):
        assert _is_problem("unload_in_progress") is False

    def test_not_loaded_is_not_a_problem(self):
        assert _is_problem("not_loaded") is False

    def test_setup_error_is_a_problem(self):
        assert _is_problem("setup_error") is True

    def test_setup_retry_is_a_problem(self):
        assert _is_problem("setup_retry") is True

    def test_severity_error_states(self):
        for state in ERROR_STATES:
            assert _get_severity(state) == "error", f"{state} should be error"

    def test_severity_warning_states(self):
        for state in WARNING_STATES:
            assert _get_severity(state) == "warning", f"{state} should be warning"

    def test_severity_healthy_states(self):
        for state in HEALTHY_STATES:
            assert _get_severity(state) == "ok", f"{state} should be ok"

    def test_severity_inactive_states(self):
        """not_loaded is a warning — integration should be running but isn't."""
        for state in INACTIVE_STATES:
            assert _get_severity(state) == "warning", f"{state} should be warning"

    def test_severity_transient_states(self):
        for state in TRANSIENT_STATES:
            assert _get_severity(state) == "ok", f"{state} should be ok"

    def test_severity_unknown_state_is_warning(self):
        assert _get_severity("some_future_unknown_state") == "warning"


# ---------------------------------------------------------------------------
# IntegrationsProvider._should_watch — filtering logic
# ---------------------------------------------------------------------------


class TestShouldWatch:
    """Test IntegrationsProvider._should_watch filtering."""

    def _make_provider(self, excluded=None):
        hass = MagicMock()
        return IntegrationsProvider(
            hass,
            excluded_entry_ids=set(excluded or []),
        )

    def test_normal_user_integration_is_watched(self):
        provider = self._make_provider()
        entry = MockConfigEntry(domain="netatmo", source="user")
        assert provider._should_watch(entry) is True

    def test_excluded_domain_is_not_watched(self):
        provider = self._make_provider()
        for domain in EXCLUDED_DOMAINS:
            entry = MockConfigEntry(domain=domain, source="user")
            assert provider._should_watch(entry) is False, f"{domain} should be excluded"

    def test_excluded_source_is_not_watched(self):
        provider = self._make_provider()
        for source in EXCLUDED_SOURCES:
            entry = MockConfigEntry(domain="netatmo", source=source)
            assert provider._should_watch(entry) is False, f"source={source} should be excluded"

    def test_explicit_excluded_entry_is_not_watched(self):
        provider = self._make_provider(excluded=["excluded_id"])
        entry = MockConfigEntry(entry_id="excluded_id", domain="netatmo", source="user")
        assert provider._should_watch(entry) is False

    def test_explicit_extra_entry_overrides_source_exclusion(self):
        """Removed — extra_entries feature has been removed."""

    def test_explicit_excluded_takes_priority(self):
        """Excluded entries are not watched."""
        provider = self._make_provider(excluded=["conflict_id"])
        entry = MockConfigEntry(entry_id="conflict_id", domain="netatmo", source="user")
        assert provider._should_watch(entry) is False

    def test_sentinel_domain_never_watched(self):
        provider = self._make_provider()
        entry = MockConfigEntry(domain=DOMAIN, source="user")
        assert provider._should_watch(entry) is False

    def test_user_disabled_entry_is_not_watched(self):
        """User-disabled integrations (disabled_by=USER) should not be monitored."""
        provider = self._make_provider()
        entry = MockConfigEntry(domain="netatmo", source="user")
        entry.disabled_by = ConfigEntryDisabler.USER
        assert provider._should_watch(entry) is False

    def test_not_disabled_entry_is_watched(self):
        """Entry with disabled_by=None should be monitored normally."""
        provider = self._make_provider()
        entry = MockConfigEntry(domain="netatmo", source="user")
        entry.disabled_by = None
        assert provider._should_watch(entry) is True
