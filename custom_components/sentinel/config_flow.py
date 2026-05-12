"""Config flow for HA Sentinel."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_EXCLUDED_ENTRIES,
    CONF_EXTRA_ENTRIES,
    CONF_FIRE_EVENTS,
    CONF_GRACE_PERIOD,
    CONF_IGNORED_DEVICE_IDS,
    CONF_IGNORED_DEVICE_SOURCES,
    CONF_WATCH_STOPPED_ADDONS,
    DEFAULT_FIRE_EVENTS,
    DEFAULT_GRACE_PERIOD,
    DEFAULT_WATCH_STOPPED_ADDONS,
    DOMAIN,
    EXCLUDED_DOMAINS,
    EXCLUDED_SOURCES,
    NAME,
)


class SentinelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for HA Sentinel (initial setup)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle the initial setup step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title=NAME,
                data={},
                options={
                    CONF_GRACE_PERIOD: user_input.get(CONF_GRACE_PERIOD, DEFAULT_GRACE_PERIOD),
                    CONF_FIRE_EVENTS: user_input.get(CONF_FIRE_EVENTS, DEFAULT_FIRE_EVENTS),
                    CONF_EXCLUDED_ENTRIES: [],
                    CONF_EXTRA_ENTRIES: [],
                    CONF_IGNORED_DEVICE_SOURCES: [],
                    CONF_IGNORED_DEVICE_IDS: [],
                    CONF_WATCH_STOPPED_ADDONS: DEFAULT_WATCH_STOPPED_ADDONS,
                },
            )

        schema = vol.Schema(
            {
                vol.Optional(CONF_GRACE_PERIOD, default=DEFAULT_GRACE_PERIOD): vol.All(
                    int, vol.Range(min=0, max=300)
                ),
                vol.Optional(CONF_FIRE_EVENTS, default=DEFAULT_FIRE_EVENTS): bool,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SentinelOptionsFlow:
        """Return the options flow."""
        return SentinelOptionsFlow()


class SentinelOptionsFlow(OptionsFlow):
    """Options flow for HA Sentinel."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Manage options."""
        current = self.config_entry.options

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Entries watched by default — shown in "Excluded" list (what you can opt-out)
        watched_entries = {
            entry.entry_id: f"{entry.title} ({entry.domain})"
            for entry in self.hass.config_entries.async_entries()
            if entry.domain != DOMAIN
            and entry.source not in EXCLUDED_SOURCES
            and entry.domain not in EXCLUDED_DOMAINS
        }

        # Entries NOT watched by default but potentially useful — shown in "Extra" list
        extra_entries = {
            entry.entry_id: f"{entry.title} ({entry.domain}) [{entry.source}]"
            for entry in self.hass.config_entries.async_entries()
            if entry.domain != DOMAIN
            and entry.domain not in EXCLUDED_DOMAINS
            and entry.source in EXCLUDED_SOURCES
        }

        schema = vol.Schema(
            {
                # --- Integrations provider ---
                vol.Optional(
                    CONF_GRACE_PERIOD,
                    default=current.get(CONF_GRACE_PERIOD, DEFAULT_GRACE_PERIOD),
                ): vol.All(int, vol.Range(min=0, max=300)),
                vol.Optional(
                    CONF_FIRE_EVENTS,
                    default=current.get(CONF_FIRE_EVENTS, DEFAULT_FIRE_EVENTS),
                ): bool,
                vol.Optional(
                    CONF_EXCLUDED_ENTRIES,
                    default=current.get(CONF_EXCLUDED_ENTRIES, []),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[{"value": k, "label": v} for k, v in watched_entries.items()],
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_EXTRA_ENTRIES,
                    default=current.get(CONF_EXTRA_ENTRIES, []),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[{"value": k, "label": v} for k, v in extra_entries.items()],
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                # --- Devices provider ---
                vol.Optional(
                    CONF_IGNORED_DEVICE_SOURCES,
                    default=current.get(CONF_IGNORED_DEVICE_SOURCES, []),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[],
                        multiple=True,
                        custom_value=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_IGNORED_DEVICE_IDS,
                    default=current.get(CONF_IGNORED_DEVICE_IDS, []),
                ): DeviceSelector(DeviceSelectorConfig(multiple=True)),
                # --- Apps provider ---
                vol.Optional(
                    CONF_WATCH_STOPPED_ADDONS,
                    default=current.get(CONF_WATCH_STOPPED_ADDONS, DEFAULT_WATCH_STOPPED_ADDONS),
                ): BooleanSelector(),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
