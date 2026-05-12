"""Config flow for HA Sentinel."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import (
    BooleanSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
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
    EXCLUDED_DOMAINS,
    EXCLUDED_SOURCES,
    NAME,
)


class SentinelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for HA Sentinel (initial setup).

    No configuration required — sensible defaults are applied automatically.
    All options are available after setup via the Configure button.
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Create the config entry with default options — no user input required."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        # Create immediately with defaults — no form needed
        return self.async_create_entry(
            title=NAME,
            data={},
            options={
                CONF_FIRE_EVENTS: DEFAULT_FIRE_EVENTS,
                CONF_GRACE_PERIOD: DEFAULT_GRACE_PERIOD,
                CONF_EXCLUDED_ENTRIES: [],
                CONF_IGNORED_DEVICE_SOURCES: [],
                CONF_IGNORED_DEVICE_IDS: [],
                CONF_WATCH_STOPPED_ADDONS: DEFAULT_WATCH_STOPPED_ADDONS,
                CONF_APPS_POLL_INTERVAL: DEFAULT_APPS_POLL_INTERVAL,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SentinelOptionsFlow:
        """Return the options flow."""
        return SentinelOptionsFlow()


class SentinelOptionsFlow(OptionsFlow):
    """Options flow for HA Sentinel — single screen, seven fields, logical order."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
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

        # Devices: sources present in the device registry (what's actually installed)
        dev_reg = dr.async_get(self.hass)
        device_sources: set[str] = set()
        for device in dev_reg.devices.values():
            identifiers = sorted(device.identifiers)
            if identifiers:
                source = str(identifiers[0][0])
                if source:
                    device_sources.add(source)
        device_source_options = sorted(
            [{"value": s, "label": s} for s in device_sources],
            key=lambda x: x["label"],
        )

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
                # 3 — Devices
                vol.Optional(
                    CONF_IGNORED_DEVICE_SOURCES,
                    default=current.get(CONF_IGNORED_DEVICE_SOURCES, []),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=device_source_options,
                        multiple=True,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_IGNORED_DEVICE_IDS,
                    default=current.get(CONF_IGNORED_DEVICE_IDS, []),
                ): DeviceSelector(DeviceSelectorConfig(multiple=True)),
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
