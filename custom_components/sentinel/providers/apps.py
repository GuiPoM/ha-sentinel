"""Apps (add-ons) provider for HA Sentinel.

Monitors Home Assistant OS add-ons via the Supervisor API.
Only active on HA OS / Supervised installations.

Add-on states (from Supervisor AddonState):
  - started  → ok
  - startup  → transient, ignored
  - stopped  → ignored by default; warning if watch_stopped_addons=True
  - error    → error (Docker failure on start/stop)
  - unknown  → warning (initial state or after uninstall)

State source:
  Reads hass.data[DATA_ADDONS_LIST] — the cache maintained by
  HassioAddOnDataUpdateCoordinator (hassio integration). This cache is kept
  up to date via EVENT_SUPERVISOR_EVENT push events from the Supervisor
  WebSocket, so it always reflects the real container state.

  We also subscribe to EVENT_SUPERVISOR_EVENT directly so we can trigger
  an immediate rescan as soon as the Supervisor notifies HA of a state change,
  without waiting for our poll interval.
"""
from __future__ import annotations

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

# DATA_ADDONS_LIST is a HassKey — import it defensively since older HA versions
# may not export it from hassio.const. Fall back to the raw string key.
try:
    from homeassistant.components.hassio.const import DATA_ADDONS_LIST  # type: ignore[attr-defined]  # noqa: PLC0415
    _ADDONS_LIST_KEY: object = DATA_ADDONS_LIST
except ImportError:
    _ADDONS_LIST_KEY = "hassio_addons_list"

from ..const import DEFAULT_APPS_POLL_INTERVAL, PROVIDER_APPS
from . import HealthItem, HealthProvider

_LOGGER = logging.getLogger(__name__)

# Default poll interval — overridden by config
_DEFAULT_POLL_INTERVAL = timedelta(seconds=DEFAULT_APPS_POLL_INTERVAL)

# Raw Supervisor AddonState values
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


def _get_addons_from_cache(hass: HomeAssistant) -> list[Any]:
    """Return the list of installed add-ons from the hassio coordinator cache.

    hass.data[DATA_ADDONS_LIST] is maintained by HassioAddOnDataUpdateCoordinator
    and kept fresh via EVENT_SUPERVISOR_EVENT push events from the Supervisor.
    This reflects the real container state without any additional API calls.
    """
    return hass.data.get(_ADDONS_LIST_KEY) or []


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

    Reads add-on states from the hassio coordinator cache (hass.data[DATA_ADDONS_LIST])
    which is kept up to date via Supervisor WebSocket push events. Also subscribes
    to EVENT_SUPERVISOR_EVENT for immediate rescans on state changes.
    Periodic polling is kept as a fallback safety net.
    Only active on HA OS / Supervised installations.
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

        # Initial scan from cache
        self._sync_scan()

        # Subscribe to Supervisor push events for immediate rescans
        self._unsub_supervisor_event = async_dispatcher_connect(
            self.hass,
            EVENT_SUPERVISOR_EVENT,
            self._on_supervisor_event,
        )

        # Periodic poll as fallback safety net
        self._unsub_poll = async_track_time_interval(
            self.hass,
            self._async_poll,
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
        """Trigger an immediate rescan when the Supervisor notifies a state change."""
        _LOGGER.debug("Sentinel AppsProvider: supervisor event received, rescanning")
        self._sync_scan()

    @callback
    def _async_poll(self, _now: Any = None) -> None:
        """Periodic fallback poll — re-read from the hassio cache."""
        self._sync_scan()

    @callback
    def _sync_scan(self) -> None:
        """Read add-on states from the hassio coordinator cache and update items."""
        addons = _get_addons_from_cache(self.hass)

        seen_slugs: set[str] = set()

        for addon in addons:
            slug = self._get_slug(addon)
            if not slug:
                continue

            state = self._get_state(addon)
            if state in _TRANSIENT_STATES:
                continue  # ignore transient states

            seen_slugs.add(slug)
            self._update_addon(addon, slug, state)

        # Clean up removed add-ons
        for slug in list(self._items.keys()):
            if slug not in seen_slugs:
                self._items.pop(slug, None)
                self._previous_healthy.pop(slug, None)

    def _get_slug(self, addon: Any) -> str | None:
        """Extract the slug from an InstalledAddon object or dict."""
        if isinstance(addon, dict):
            return addon.get("slug")
        return getattr(addon, "slug", None)

    def _get_state(self, addon: Any) -> str:
        """Extract the raw state string from an InstalledAddon object or dict."""
        if isinstance(addon, dict):
            state = addon.get("state", _STATE_UNKNOWN)
        else:
            state = getattr(addon, "state", _STATE_UNKNOWN)
        # Normalize — AddonState is a StrEnum, .value gives the raw string
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

