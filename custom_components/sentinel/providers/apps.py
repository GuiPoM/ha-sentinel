"""Apps (add-ons) provider for HA Sentinel.

Monitors Home Assistant OS add-ons via the Supervisor API.
Only active on HA OS / Supervised installations.

Add-on states (from Supervisor AppState):
  - started  → ok
  - startup  → transient, ignored
  - stopped  → ok by default (intentional stop); warning if watch_stopped_addons=True
  - error    → error (container exited with non-zero code, or Docker API failure)
  - unknown  → warning (initial state or after uninstall)

State source:
  Uses addons.list() to enumerate slugs, then addon_info(slug) for each one to
  get the real-time state from the Supervisor's in-memory AppState — not a cache.

  Also subscribes to EVENT_SUPERVISOR_EVENT as an opportunistic trigger for
  immediate rescans when the Supervisor notifies HA of any change.
  Periodic polling is kept as a fallback safety net.

Note on error vs stopped:
  Due to a Supervisor bug (container_state_changed does not check _manual_stop),
  a manual stop that exits with non-zero code (e.g. SIGTERM → exit 143) produces
  AppState.ERROR instead of AppState.STOPPED. A fix has been reported upstream.
  Until then, error = potentially a real problem or a manual stop with bad exit code.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.hassio.const import EVENT_SUPERVISOR_EVENT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.hassio import is_hassio
from homeassistant.util import dt as dt_util

from ..const import DEFAULT_APPS_POLL_INTERVAL, PROVIDER_APPS
from . import HealthItem, HealthProvider

_LOGGER = logging.getLogger(__name__)

# Raw Supervisor AppState values
_STATE_STARTED = "started"
_STATE_STARTUP = "startup"
_STATE_STOPPED = "stopped"
_STATE_ERROR = "error"
_STATE_UNKNOWN = "unknown"

# States that indicate a real problem
_ERROR_STATES = {_STATE_ERROR}
_WARNING_STATES = {_STATE_UNKNOWN}
# States that are transient — never reported
_TRANSIENT_STATES = {_STATE_STARTUP}


async def _get_addons_with_state(hass: HomeAssistant) -> list[Any]:
    """Return installed add-ons with fresh real-time state via addon_info().

    Uses addons.list() to enumerate slugs, then addon_info(slug) per add-on
    to read the Supervisor's in-memory AppState — not a cached value.
    Falls back to the list() data for any add-on where addon_info() fails.
    """
    try:
        from homeassistant.components.hassio import get_supervisor_client  # noqa: PLC0415
        client = get_supervisor_client(hass)
        addons_list = await client.addons.list()
        if not addons_list:
            return []
    except Exception as err:
        _LOGGER.debug("Sentinel AppsProvider: could not list add-ons: %s", err)
        return []

    result = []
    for addon in addons_list:
        slug = addon.slug if hasattr(addon, "slug") else addon.get("slug")
        if not slug:
            continue
        try:
            info = await client.addons.addon_info(slug)
            result.append(info)
        except Exception as err:
            _LOGGER.debug(
                "Sentinel AppsProvider: could not get info for %s: %s", slug, err
            )
            result.append(addon)  # fallback to list() data
    return result


async def _restart_addon(hass: HomeAssistant, slug: str) -> bool:
    """Restart an add-on via the Supervisor API."""
    try:
        from homeassistant.components.hassio import get_supervisor_client  # noqa: PLC0415
        await get_supervisor_client(hass).addons.restart_addon(slug)
        return True
    except Exception as err:
        _LOGGER.error("Failed to restart add-on %s: %s", slug, err)
        return False


class AppsProvider(HealthProvider):
    """Health provider for Home Assistant OS add-ons.

    Fetches real-time add-on states via addon_info(slug) from the Supervisor.
    Rescans are triggered by EVENT_SUPERVISOR_EVENT (opportunistic push) and
    by a periodic poll as a fallback. Only active on HA OS / Supervised installs.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        watch_stopped: bool = False,
        poll_interval: int = DEFAULT_APPS_POLL_INTERVAL,
    ) -> None:
        """Initialize the apps provider."""
        super().__init__(hass)
        self._watch_stopped = watch_stopped
        self._poll_interval = timedelta(seconds=poll_interval)
        self._on_change: Callable[[HealthItem], None] | None = None
        self._unsub_poll: Callable | None = None
        self._unsub_supervisor_event: Callable | None = None
        self._previous_healthy: dict[str, bool] = {}
        self._scan_lock = asyncio.Lock()

    @property
    def provider_id(self) -> str:
        return PROVIDER_APPS

    @property
    def name(self) -> str:
        return "Apps"

    @property
    def available(self) -> bool:
        """Only available when Supervisor (hassio) is loaded."""
        return is_hassio(self.hass)

    async def async_setup(self, on_change_callback: Callable[[HealthItem], None]) -> None:
        """Set up the apps provider."""
        if not self.available:
            _LOGGER.debug("Sentinel AppsProvider: not on HA OS, skipping setup")
            return

        self._on_change = on_change_callback

        # Initial scan
        await self._async_scan()

        # Subscribe to Supervisor push events for opportunistic immediate rescans
        self._unsub_supervisor_event = async_dispatcher_connect(
            self.hass,
            EVENT_SUPERVISOR_EVENT,
            self._on_supervisor_event,
        )

        # Periodic poll as fallback safety net
        self._unsub_poll = async_track_time_interval(
            self.hass,
            self._schedule_scan,
            self._poll_interval,
        )

        _LOGGER.debug(
            "Sentinel AppsProvider: monitoring %d add-ons (push + %ds poll)",
            len(self._items),
            self._poll_interval.seconds,
        )

    async def async_unload(self) -> None:
        """Unload provider and cancel subscriptions."""
        if self._unsub_poll:
            self._unsub_poll()
            self._unsub_poll = None
        if self._unsub_supervisor_event:
            self._unsub_supervisor_event()
            self._unsub_supervisor_event = None

    async def async_reload_item(self, item_id: str) -> bool:
        """Restart the given add-on (item_id = slug)."""
        return await _restart_addon(self.hass, item_id)

    @callback
    def _on_supervisor_event(self, event: dict[str, Any]) -> None:
        """Schedule an immediate rescan when the Supervisor fires an event."""
        _LOGGER.debug("Sentinel AppsProvider: supervisor event — scheduling rescan")
        self.hass.async_create_task(self._async_scan())

    @callback
    def _schedule_scan(self, _now: Any = None) -> None:
        """Schedule a periodic scan from the time interval callback."""
        self.hass.async_create_task(self._async_scan())

    async def _async_scan(self) -> None:
        """Fetch fresh add-on states via addon_info() and update health items."""
        async with self._scan_lock:
            addons = await _get_addons_with_state(self.hass)
            if not addons:
                return

            seen_slugs: set[str] = set()

            for addon in addons:
                slug = self._get_slug(addon)
                if not slug:
                    continue

                state = self._get_state(addon)
                if state in _TRANSIENT_STATES:
                    continue

                seen_slugs.add(slug)
                self._update_addon(addon, slug, state)

            # Clean up removed add-ons
            for slug in list(self._items.keys()):
                if slug not in seen_slugs:
                    self._items.pop(slug, None)
                    self._previous_healthy.pop(slug, None)

    def _get_slug(self, addon: Any) -> str | None:
        """Extract the slug from an InstalledAddon/InstalledAddonComplete object or dict."""
        if isinstance(addon, dict):
            return addon.get("slug")
        return getattr(addon, "slug", None)

    def _get_state(self, addon: Any) -> str:
        """Extract the raw state string from an InstalledAddon object or dict."""
        if isinstance(addon, dict):
            state = addon.get("state", _STATE_UNKNOWN)
        else:
            state = getattr(addon, "state", _STATE_UNKNOWN)
        # Normalize — AppState/AddonState is a StrEnum, .value gives the raw string
        return str(state.value if hasattr(state, "value") else state)

    def _get_name(self, addon: Any) -> str:
        """Extract the display name from an InstalledAddon object or dict."""
        if isinstance(addon, dict):
            return addon.get("name") or addon.get("slug", "unknown")
        return getattr(addon, "name", None) or getattr(addon, "slug", "unknown")

    def _update_addon(self, addon: Any, slug: str, state: str) -> None:
        """Evaluate an add-on's health and notify if changed."""
        is_healthy, severity = self._classify(state)
        existing = self._items.get(slug)
        was_healthy = self._previous_healthy.get(slug, True)

        failure_count = existing.failure_count if existing else 0
        if was_healthy and not is_healthy:
            failure_count += 1

        name = self._get_name(addon)
        now = dt_util.utcnow()

        item = HealthItem(
            id=slug,
            name=name,
            provider=PROVIDER_APPS,
            healthy=is_healthy,
            state=state,
            severity=severity,
            reason=None,
            since=existing.since if existing and existing.healthy == is_healthy else now,
            failure_count=failure_count,
            can_reload=True,
            extra={
                "slug": slug,
                "source": "hassio",
            },
        )

        self._items[slug] = item
        self._previous_healthy[slug] = is_healthy

        if is_healthy != was_healthy or existing is None:
            if self._on_change:
                self._on_change(item)

    def _classify(self, state: str) -> tuple[bool, str]:
        """Return (is_healthy, severity) for a raw addon state string."""
        if state == _STATE_STARTED:
            return True, "ok"
        if state in _ERROR_STATES:
            return False, "error"
        if state in _WARNING_STATES:
            return False, "warning"
        if state == _STATE_STOPPED:
            if self._watch_stopped:
                return False, "warning"
            return True, "ok"  # ignored — intentional stop
        # Any future unknown state → warning
        return False, "warning"

