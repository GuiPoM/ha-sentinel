"""Tests for config flow — initial setup and options."""
from __future__ import annotations

from unittest.mock import patch

from custom_components.sentinel.const import (
    CONF_APPS_POLL_INTERVAL,
    CONF_EXCLUDED_ENTRIES,
    CONF_FIRE_EVENTS,
    CONF_GRACE_PERIOD,
    CONF_IGNORED_DEVICE_IDS,
    CONF_IGNORED_DEVICE_SOURCES,
    CONF_WATCH_STOPPED_ADDONS,
    DEFAULT_APPS_POLL_INTERVAL,
    DEFAULT_FIRE_EVENTS,
    DEFAULT_GRACE_PERIOD,
    DEFAULT_WATCH_STOPPED_ADDONS,
    DOMAIN,
)
import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


@pytest.fixture
def mock_setup_entry():
    """Prevent actual integration setup during config flow tests."""
    with patch(
        "custom_components.sentinel.async_setup_entry",
        return_value=True,
    ) as mock:
        yield mock


async def test_config_flow_creates_entry_directly(hass: HomeAssistant, mock_setup_entry):
    """Test that setup creates a config entry directly without a form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Setup creates entry directly — no form
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Sentinel"
    options = result["options"]
    assert options[CONF_FIRE_EVENTS] == DEFAULT_FIRE_EVENTS
    assert options[CONF_GRACE_PERIOD] == DEFAULT_GRACE_PERIOD
    assert options[CONF_EXCLUDED_ENTRIES] == []
    assert options[CONF_IGNORED_DEVICE_SOURCES] == []
    assert options[CONF_IGNORED_DEVICE_IDS] == []
    assert options[CONF_WATCH_STOPPED_ADDONS] == DEFAULT_WATCH_STOPPED_ADDONS
    assert options[CONF_APPS_POLL_INTERVAL] == DEFAULT_APPS_POLL_INTERVAL


async def test_config_flow_aborts_if_already_configured(hass: HomeAssistant, mock_setup_entry):
    """Test that a second setup attempt is aborted."""
    # First setup
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Second setup attempt
    result2 = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] in ("already_configured", "single_instance_allowed")


async def test_options_flow_updates_options(hass: HomeAssistant, mock_setup_entry):
    """Test that the options flow updates config entry options."""
    # Create entry
    entry_result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert entry_result["type"] == FlowResultType.CREATE_ENTRY

    entry = hass.config_entries.async_get_entry(entry_result["result"].entry_id)
    assert entry is not None

    # Open options flow
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_FIRE_EVENTS: False,
            CONF_GRACE_PERIOD: 60,
            CONF_EXCLUDED_ENTRIES: [],
            CONF_IGNORED_DEVICE_SOURCES: ["mobile_app"],
            CONF_IGNORED_DEVICE_IDS: [],
            CONF_WATCH_STOPPED_ADDONS: True,
            CONF_APPS_POLL_INTERVAL: 120,
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_GRACE_PERIOD] == 60
    assert entry.options[CONF_FIRE_EVENTS] is False
    assert entry.options[CONF_IGNORED_DEVICE_SOURCES] == ["mobile_app"]
    assert entry.options[CONF_WATCH_STOPPED_ADDONS] is True
    assert entry.options[CONF_APPS_POLL_INTERVAL] == 120
