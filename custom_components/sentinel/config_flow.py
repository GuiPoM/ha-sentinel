"""Config flow for HA Sentinel."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_APPS_POLL_INTERVAL,
    CONF_ENABLE_DEVICE_DISCOVERY,
    CONF_EXCLUDED_ENTRIES,
    CONF_FIRE_EVENTS,
    CONF_GRACE_PERIOD,
    CONF_SUBENTRY_DEVICE_ID,
    CONF_SUBENTRY_GRACE_PERIOD,
    CONF_SUBENTRY_IGNORED,
    CONF_SUBENTRY_NOTE,
    CONF_WATCH_STOPPED_ADDONS,
    DEFAULT_APPS_POLL_INTERVAL,
    DEFAULT_ENABLE_DEVICE_DISCOVERY,
    DEFAULT_FIRE_EVENTS,
    DEFAULT_GRACE_PERIOD,
    DEFAULT_WATCH_STOPPED_ADDONS,
    DOMAIN,
    EXCLUDED_DOMAINS,
    EXCLUDED_SOURCES,
    NAME,
    SUBENTRY_TYPE_DEVICE,
)
from .providers.devices import _is_eligible


def _get_eligible_devices(
    hass: HomeAssistant,
    already_tracked: set[str],
) -> list[tuple[str, str]]:
    """Return list of (device_id, display_label) for devices eligible as subentries.

    A device is eligible if:
    - It has at least one monitored entity (physical domain or vital device class,
      not disabled, not diagnostic, with a device_id)
    - It is not already tracked in an existing subentry
    """
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    # Collect device_ids that have at least one eligible entity
    eligible_ids: set[str] = set()
    for entity in ent_reg.entities.values():
        if entity.device_id and _is_eligible(entity) and entity.device_id not in already_tracked:
            eligible_ids.add(entity.device_id)

    result: list[tuple[str, str]] = []
    for device_id in sorted(eligible_ids):
        device = dev_reg.async_get(device_id)
        if device is None:
            continue
        name = device.name_by_user or device.name or device_id
        # Source = first identifier domain, lowercase
        identifiers = sorted(device.identifiers)
        source = str(identifiers[0][0]).lower() if identifiers else "device"
        result.append((device_id, f"{name} ({source})"))

    return result


def _build_subentry_title(hass: HomeAssistant, device_id: str) -> str:
    """Return the subentry title for a device: 'Device Name (source)'."""
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get(device_id)
    if device is None:
        return device_id
    name = device.name_by_user or device.name or device_id
    identifiers = sorted(device.identifiers)
    source = str(identifiers[0][0]).lower() if identifiers else "device"
    return f"{name} ({source})"


class SentinelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for HA Sentinel (initial setup).

    No configuration required — sensible defaults are applied automatically.
    All options are available after setup via the Configure button.
    Device monitoring is configured via subentries (the '+' button).
    """

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the config entry with default options — no user input required."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=NAME,
            data={},
            options={
                CONF_FIRE_EVENTS: DEFAULT_FIRE_EVENTS,
                CONF_GRACE_PERIOD: DEFAULT_GRACE_PERIOD,
                CONF_EXCLUDED_ENTRIES: [],
                CONF_WATCH_STOPPED_ADDONS: DEFAULT_WATCH_STOPPED_ADDONS,
                CONF_APPS_POLL_INTERVAL: DEFAULT_APPS_POLL_INTERVAL,
                CONF_ENABLE_DEVICE_DISCOVERY: DEFAULT_ENABLE_DEVICE_DISCOVERY,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SentinelOptionsFlow:
        """Return the options flow."""
        return SentinelOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentry types supported by Sentinel."""
        return {SUBENTRY_TYPE_DEVICE: DeviceSubentryFlowHandler}


class SentinelOptionsFlow(OptionsFlow):
    """Options flow for HA Sentinel — global settings, device monitoring via subentries."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single options screen."""
        current = self.config_entry.options

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Integrations: entries the user can opt-out of monitoring
        watched_entries = {
            entry.entry_id: f"{entry.title} ({entry.domain})"
            for entry in self.hass.config_entries.async_entries()
            if entry.domain != DOMAIN
            and entry.source not in EXCLUDED_SOURCES
            and entry.domain not in EXCLUDED_DOMAINS
            and getattr(entry, "disabled_by", None) is None
        }

        schema = vol.Schema(
            {
                # 1 — General
                vol.Optional(
                    CONF_FIRE_EVENTS,
                    default=current.get(CONF_FIRE_EVENTS, DEFAULT_FIRE_EVENTS),
                ): BooleanSelector(),
                # 2 — Integrations
                vol.Optional(
                    CONF_GRACE_PERIOD,
                    default=current.get(CONF_GRACE_PERIOD, DEFAULT_GRACE_PERIOD),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=300, step=1, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_EXCLUDED_ENTRIES,
                    default=current.get(CONF_EXCLUDED_ENTRIES, []),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[{"value": k, "label": v} for k, v in watched_entries.items()],
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                # 3 — Devices (discovery opt-in)
                vol.Optional(
                    CONF_ENABLE_DEVICE_DISCOVERY,
                    default=current.get(
                        CONF_ENABLE_DEVICE_DISCOVERY, DEFAULT_ENABLE_DEVICE_DISCOVERY
                    ),
                ): BooleanSelector(),
                # 4 — Applications
                vol.Optional(
                    CONF_WATCH_STOPPED_ADDONS,
                    default=current.get(CONF_WATCH_STOPPED_ADDONS, DEFAULT_WATCH_STOPPED_ADDONS),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_APPS_POLL_INTERVAL,
                    default=current.get(CONF_APPS_POLL_INTERVAL, DEFAULT_APPS_POLL_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(min=30, max=300, step=30, mode=NumberSelectorMode.BOX)
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)


class DeviceSubentryFlowHandler(ConfigSubentryFlow):
    """Handle subentry flow for adding and reconfiguring a monitored device."""

    @property
    def _is_new(self) -> bool:
        """Return True if this is a new subentry (not a reconfigure)."""
        return self.source == "user"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step for adding a new device subentry."""
        entry = self._get_entry()

        # Build set of already-tracked device_ids (to exclude from selector)
        already_tracked: set[str] = {
            s.data.get(CONF_SUBENTRY_DEVICE_ID)
            for s in entry.subentries.values()
            if s.subentry_type == SUBENTRY_TYPE_DEVICE
            and s.data.get(CONF_SUBENTRY_DEVICE_ID)
        }

        if user_input is not None:
            device_id = user_input[CONF_SUBENTRY_DEVICE_ID]

            # Manual duplicate check (no _abort_if_unique_id_configured for subentries)
            for existing in entry.subentries.values():
                if existing.unique_id == device_id:
                    return self.async_abort(reason="already_configured")

            title = _build_subentry_title(self.hass, device_id)
            grace = user_input.get(CONF_SUBENTRY_GRACE_PERIOD)
            note = user_input.get(CONF_SUBENTRY_NOTE) or None

            return self.async_create_entry(
                title=title,
                data={
                    CONF_SUBENTRY_DEVICE_ID: device_id,
                    CONF_SUBENTRY_GRACE_PERIOD: grace,
                    CONF_SUBENTRY_IGNORED: False,
                    CONF_SUBENTRY_NOTE: note,
                },
                unique_id=device_id,
            )

        eligible = _get_eligible_devices(self.hass, already_tracked)
        if not eligible:
            return self.async_abort(reason="no_eligible_devices")

        schema = vol.Schema(
            {
                vol.Required(CONF_SUBENTRY_DEVICE_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": d_id, "label": label} for d_id, label in eligible
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_SUBENTRY_GRACE_PERIOD): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=300, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(CONF_SUBENTRY_NOTE): TextSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step for reconfiguring an existing device subentry."""
        subentry = self._get_reconfigure_subentry()
        current = dict(subentry.data)

        if user_input is not None:
            grace = user_input.get(CONF_SUBENTRY_GRACE_PERIOD)
            note = user_input.get(CONF_SUBENTRY_NOTE) or None
            ignored = user_input.get(CONF_SUBENTRY_IGNORED, False)

            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                data={
                    **current,
                    CONF_SUBENTRY_GRACE_PERIOD: grace,
                    CONF_SUBENTRY_IGNORED: ignored,
                    CONF_SUBENTRY_NOTE: note,
                },
            )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SUBENTRY_GRACE_PERIOD,
                    description={"suggested_value": current.get(CONF_SUBENTRY_GRACE_PERIOD)},
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=300, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_SUBENTRY_IGNORED,
                    default=current.get(CONF_SUBENTRY_IGNORED, False),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_SUBENTRY_NOTE,
                    description={"suggested_value": current.get(CONF_SUBENTRY_NOTE, "")},
                ): TextSelector(),
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema)
