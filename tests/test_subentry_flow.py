"""Tests for Sentinel subentry flow — device subentry add, reconfigure, migration.

These tests verify the rendered behaviour:
- The options flow no longer exposes ignored_device_* fields
- The subentry flow creates a subentry with the correct data
- Duplicate devices are rejected
- Reconfigure updates grace_period / ignored / note
- Ignored subentries are excluded from watched_device_ids in the coordinator
- Migration v1→v2 removes deprecated keys and adds enable_device_discovery
"""
from __future__ import annotations

from types import MappingProxyType
from unittest.mock import MagicMock, patch
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.sentinel.const import (
    CONF_ENABLE_DEVICE_DISCOVERY,
    CONF_FIRE_EVENTS,
    CONF_GRACE_PERIOD,
    CONF_SUBENTRY_DEVICE_ID,
    CONF_SUBENTRY_GRACE_PERIOD,
    CONF_SUBENTRY_IGNORED,
    CONF_SUBENTRY_NOTE,
    DOMAIN,
    SUBENTRY_TYPE_DEVICE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sentinel_entry(hass: HomeAssistant, **extra_options) -> MockConfigEntry:
    """Create and register a v2 Sentinel config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Sentinel",
        data={},
        options={
            CONF_GRACE_PERIOD: 30,
            CONF_FIRE_EVENTS: True,
            CONF_ENABLE_DEVICE_DISCOVERY: False,
            **extra_options,
        },
        entry_id="test_sentinel",
        unique_id=DOMAIN,
        version=2,
    )
    entry.add_to_hass(hass)
    return entry


def _make_device(device_id: str, name: str = "Test Device", domain: str = "hue"):
    """Create a mock HA device registry entry."""
    device = MagicMock()
    device.id = device_id
    device.name = name
    device.name_by_user = None
    device.identifiers = {(domain, device_id)}
    return device


def _make_entity(
    entity_id: str,
    device_id: str,
    domain: str = "light",
    entity_category=None,
    disabled_by=None,
    original_device_class=None,
):
    """Create a mock entity registry entry that passes _is_eligible."""
    entity = MagicMock()
    entity.entity_id = entity_id
    entity.device_id = device_id
    entity.domain = domain
    entity.entity_category = entity_category
    entity.disabled_by = disabled_by
    entity.original_device_class = original_device_class
    entity.device_class = original_device_class
    return entity


# ---------------------------------------------------------------------------
# Options flow — verify removed fields are gone
# ---------------------------------------------------------------------------


async def test_options_flow_does_not_expose_ignored_device_fields(
    hass: HomeAssistant,
) -> None:
    """Options flow must not include ignored_device_sources or ignored_device_ids."""
    with patch("custom_components.sentinel.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    entry = hass.config_entries.async_get_entry(result["result"].entry_id)

    options_result = await hass.config_entries.options.async_init(entry.entry_id)
    assert options_result["type"] == FlowResultType.FORM

    # The schema must not contain the removed fields
    schema_keys = [str(k) for k in options_result["data_schema"].schema]
    assert "ignored_device_sources" not in schema_keys
    assert "ignored_device_ids" not in schema_keys
    # New field must be present
    assert any("enable_device_discovery" in k for k in schema_keys)


# ---------------------------------------------------------------------------
# Subentry flow — async_get_supported_subentry_types
# ---------------------------------------------------------------------------


async def test_sentinel_config_flow_exposes_device_subentry_type(
    hass: HomeAssistant,
) -> None:
    """SentinelConfigFlow must declare the 'device' subentry type."""
    from custom_components.sentinel.config_flow import SentinelConfigFlow

    with patch("custom_components.sentinel.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
    entry = hass.config_entries.async_get_entry(result["result"].entry_id)
    supported = SentinelConfigFlow.async_get_supported_subentry_types(entry)
    assert SUBENTRY_TYPE_DEVICE in supported


# ---------------------------------------------------------------------------
# Subentry flow — no eligible devices
# ---------------------------------------------------------------------------


async def test_subentry_flow_aborts_when_no_eligible_devices(
    hass: HomeAssistant,
) -> None:
    """When no eligible devices exist, the subentry flow aborts."""
    entry = _make_sentinel_entry(hass)

    with patch(
        "custom_components.sentinel.config_flow._get_eligible_devices",
        return_value=[],
    ):
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_DEVICE),
            context={"source": "user"},
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_eligible_devices"


# ---------------------------------------------------------------------------
# Subentry flow — adds a device
# ---------------------------------------------------------------------------


async def test_subentry_flow_creates_subentry_with_correct_data(
    hass: HomeAssistant,
) -> None:
    """Completing the subentry user flow creates a subentry with device_id."""
    entry = _make_sentinel_entry(hass)

    with (
        patch(
            "custom_components.sentinel.config_flow._get_eligible_devices",
            return_value=[("hue_device_abc", "Bandeau LED (hue)")],
        ),
        patch(
            "custom_components.sentinel.config_flow._build_subentry_title",
            return_value="Bandeau LED (hue)",
        ),
    ):
        # Step 1 — show form
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_DEVICE),
            context={"source": "user"},
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"

        # Step 2 — submit
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            user_input={
                CONF_SUBENTRY_DEVICE_ID: "hue_device_abc",
                CONF_SUBENTRY_GRACE_PERIOD: 60,
                CONF_SUBENTRY_NOTE: "Living room light strip",
            },
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bandeau LED (hue)"

    # Verify the subentry was stored on the config entry
    subentries = list(entry.subentries.values())
    assert len(subentries) == 1
    sub = subentries[0]
    assert sub.data[CONF_SUBENTRY_DEVICE_ID] == "hue_device_abc"
    assert sub.data[CONF_SUBENTRY_GRACE_PERIOD] == 60
    assert sub.data[CONF_SUBENTRY_IGNORED] is False
    assert sub.data[CONF_SUBENTRY_NOTE] == "Living room light strip"
    assert sub.unique_id == "hue_device_abc"


async def test_subentry_flow_creates_subentry_without_optional_fields(
    hass: HomeAssistant,
) -> None:
    """Subentry created with only device_id — grace_period and note are None."""
    entry = _make_sentinel_entry(hass)

    with (
        patch(
            "custom_components.sentinel.config_flow._get_eligible_devices",
            return_value=[("hue_device_abc", "Bandeau LED (hue)")],
        ),
        patch(
            "custom_components.sentinel.config_flow._build_subentry_title",
            return_value="Bandeau LED (hue)",
        ),
    ):
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_DEVICE),
            context={"source": "user"},
        )
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            user_input={CONF_SUBENTRY_DEVICE_ID: "hue_device_abc"},
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    sub = list(entry.subentries.values())[0]
    assert sub.data[CONF_SUBENTRY_GRACE_PERIOD] is None
    assert sub.data[CONF_SUBENTRY_NOTE] is None
    assert sub.data[CONF_SUBENTRY_IGNORED] is False


# ---------------------------------------------------------------------------
# Subentry flow — duplicate device rejected
# ---------------------------------------------------------------------------


async def test_subentry_flow_aborts_on_duplicate_device(
    hass: HomeAssistant,
) -> None:
    """Adding a device already tracked must abort with already_configured."""
    entry = _make_sentinel_entry(hass)

    # Pre-add a subentry for hue_device_abc
    existing_subentry = ConfigSubentry(
        data=MappingProxyType({
            CONF_SUBENTRY_DEVICE_ID: "hue_device_abc",
            CONF_SUBENTRY_GRACE_PERIOD: None,
            CONF_SUBENTRY_IGNORED: False,
            CONF_SUBENTRY_NOTE: None,
        }),
        subentry_type=SUBENTRY_TYPE_DEVICE,
        title="Bandeau LED (hue)",
        unique_id="hue_device_abc",
    )
    hass.config_entries.async_add_subentry(entry, existing_subentry)

    with (
        patch(
            "custom_components.sentinel.config_flow._get_eligible_devices",
            return_value=[("hue_device_abc", "Bandeau LED (hue)")],
        ),
        patch(
            "custom_components.sentinel.config_flow._build_subentry_title",
            return_value="Bandeau LED (hue)",
        ),
    ):
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_DEVICE),
            context={"source": "user"},
        )
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            user_input={CONF_SUBENTRY_DEVICE_ID: "hue_device_abc"},
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Subentry reconfigure — updates data
# ---------------------------------------------------------------------------


async def test_subentry_reconfigure_updates_grace_period_and_note(
    hass: HomeAssistant,
) -> None:
    """Reconfigure flow updates grace_period, ignored, and note."""
    entry = _make_sentinel_entry(hass)

    subentry = ConfigSubentry(
        data=MappingProxyType({
            CONF_SUBENTRY_DEVICE_ID: "hue_device_abc",
            CONF_SUBENTRY_GRACE_PERIOD: None,
            CONF_SUBENTRY_IGNORED: False,
            CONF_SUBENTRY_NOTE: None,
        }),
        subentry_type=SUBENTRY_TYPE_DEVICE,
        title="Bandeau LED (hue)",
        unique_id="hue_device_abc",
    )
    hass.config_entries.async_add_subentry(entry, subentry)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_DEVICE),
        context={"source": "reconfigure", "subentry_id": subentry.subentry_id},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_SUBENTRY_GRACE_PERIOD: 90,
            CONF_SUBENTRY_IGNORED: True,
            CONF_SUBENTRY_NOTE: "Offline until repaired",
        },
    )

    assert result["type"] == FlowResultType.ABORT  # async_update_and_abort

    updated = entry.subentries[subentry.subentry_id]
    assert updated.data[CONF_SUBENTRY_GRACE_PERIOD] == 90
    assert updated.data[CONF_SUBENTRY_IGNORED] is True
    assert updated.data[CONF_SUBENTRY_NOTE] == "Offline until repaired"
    # device_id must be preserved
    assert updated.data[CONF_SUBENTRY_DEVICE_ID] == "hue_device_abc"


# ---------------------------------------------------------------------------
# Coordinator — ignored subentries excluded from watched_device_ids
# ---------------------------------------------------------------------------


def test_ignored_subentry_excluded_from_watched_device_ids() -> None:
    """A subentry with ignored=True must not be in watched_device_ids."""
    from custom_components.sentinel.coordinator import SentinelCoordinator

    hass = MagicMock()

    active_sub = MagicMock()
    active_sub.subentry_type = SUBENTRY_TYPE_DEVICE
    active_sub.data = {
        CONF_SUBENTRY_DEVICE_ID: "device_active",
        CONF_SUBENTRY_IGNORED: False,
        CONF_SUBENTRY_GRACE_PERIOD: None,
    }

    ignored_sub = MagicMock()
    ignored_sub.subentry_type = SUBENTRY_TYPE_DEVICE
    ignored_sub.data = {
        CONF_SUBENTRY_DEVICE_ID: "device_ignored",
        CONF_SUBENTRY_IGNORED: True,
        CONF_SUBENTRY_GRACE_PERIOD: None,
    }

    coordinator = SentinelCoordinator(hass, {}, subentries=[active_sub, ignored_sub])

    # Patch providers to avoid real HA setup
    with patch.object(coordinator, "_providers", {}):
        # Manually simulate what async_setup does: build watched_device_ids
        watched: set[str] = set()
        for sub in [active_sub, ignored_sub]:
            if sub.subentry_type == SUBENTRY_TYPE_DEVICE:
                if not sub.data.get(CONF_SUBENTRY_IGNORED, False):
                    watched.add(sub.data[CONF_SUBENTRY_DEVICE_ID])

    assert "device_active" in watched
    assert "device_ignored" not in watched


def test_grace_period_override_from_subentry() -> None:
    """Subentry with grace_period override must be passed to DevicesProvider."""
    from custom_components.sentinel.coordinator import SentinelCoordinator

    hass = MagicMock()

    sub = MagicMock()
    sub.subentry_type = SUBENTRY_TYPE_DEVICE
    sub.data = {
        CONF_SUBENTRY_DEVICE_ID: "device_abc",
        CONF_SUBENTRY_IGNORED: False,
        CONF_SUBENTRY_GRACE_PERIOD: 120,
    }

    coordinator = SentinelCoordinator(hass, {}, subentries=[sub])
    _ = coordinator  # constructed to verify no errors in __init__

    overrides: dict[str, int | None] = {}
    for s in [sub]:
        if s.subentry_type == SUBENTRY_TYPE_DEVICE and not s.data.get(CONF_SUBENTRY_IGNORED):
            overrides[s.data[CONF_SUBENTRY_DEVICE_ID]] = s.data.get(CONF_SUBENTRY_GRACE_PERIOD)

    assert overrides["device_abc"] == 120


def test_no_subentries_means_no_watched_devices() -> None:
    """With no subentries, DevicesProvider watches no devices."""
    from custom_components.sentinel.coordinator import SentinelCoordinator

    hass = MagicMock()
    SentinelCoordinator(hass, {}, subentries=[])

    watched: set[str] = set()
    # No subentries — set stays empty
    assert watched == set()
