"""Test configuration and shared fixtures for ha-sentinel."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure custom_components is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    yield


@pytest.fixture
def mock_config_entry(hass):
    """Return a mock Sentinel config entry."""
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    entry = pytest.importorskip("homeassistant.config_entries").ConfigEntry(
        version=1,
        minor_version=1,
        domain="sentinel",
        title="Sentinel",
        data={},
        options={},
        source="user",
        entry_id="test_sentinel_entry",
        unique_id="sentinel",
    )
    return entry
