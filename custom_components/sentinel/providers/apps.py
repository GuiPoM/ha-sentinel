"""Apps (add-ons) provider for HA Sentinel.

Monitors Home Assistant OS add-ons via the Supervisor API.
Only active on HA OS / Supervised installations.

Add-on states (from Supervisor AppState):
  - started  → ok
  - startup  → transient, ignored
  - stopped  → ignored by default; warning if watch_stopped_addons=True
  - error    → error (Docker failure on start/stop)
  - unknown  → warning (initial state or after uninstall)
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from ..const import PROVIDER_APPS
from . import HealthItem, HealthProvider

_LOGGER = logging.getLogger(__name__)

# How often to poll the Supervisor for add-on states
_POLL_INTERVAL = timedelta(seconds=60)

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


def _is_hassio(hass: HomeAssistant) -> bool:
    """Return True if running on HA OS / Supervised (Supervisor available)."""
    try:
        from homeassistant.components.hassio import is_hassio  # noqa: PLC0415
        return is_hassio(hass)
    except ImportError:
        return False


def _get_addons(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return the list of installed add-ons from the hassio coordinator cache."""
    try:
        from homeassistant.components.hassio import get_addons_info  # noqa: PLC0415
        info = get_addons_info(hass)
        if info is None:
            return []
        # get_addons_info returns a dict[slug, AddonInfo] or list depending on HA version
        if isinstance(info, dict):
            return list(info.values())
        return list(info) if info else []
    except (ImportError, Exception) as err:
        _LOGGER.debug("Could not get addons info: %s", err)
        return []


async def _restart_addon(hass: HomeAssistant, slug: str) -> bool:
    """Restart an add-on via the Supervisor API."""
    try:
        from homeassistant.components.hassio import get_supervisor_client  # noqa: PLC0415
        client = get_supervisor_client(hass)
        await client.addons.restart_addon(slug)
        return True
    except Exception as err:
        _LOGGER.error("Failed to restart add-on %s: %s", slug, err)
        return False


class AppsProvider(HealthProvider):
    """Health provider for Home Assistant OS add-ons.

    Polls the Supervisor API every 60s to detect add-ons that are in error
    or unknown state. Only active on HA OS / Supervised installations.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        watch_stopped: bool = False,
    ) -> None:
        """Initialize the apps provider."""
        super().__init__(hass)
        self._watch_stopped = watch_stopped
        self._on_change: Callable[[HealthItem], None] | None = None
        self._unsub_poll: Callable | None = None
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
        return _is_hassio(self.hass)

    async def async_setup(self, on_change_callback: Callable[[HealthItem], None]) -> None:
        """Set up the apps provider."""
        if not self.available:
            _LOGGER.debug("Sentinel AppsProvider: not on HA OS, skipping setup")
            return

        self._on_change = on_change_callback

        # Initial scan
        await self._async_scan()

        # Schedule periodic polling
        self._unsub_poll = async_track_time_interval(
            self.hass,
            self._async_poll,
            _POLL_INTERVAL,
        )

        _LOGGER.debug(
            "Sentinel AppsProvider: monitoring %d add-ons", len(self._items)
        )

    async def async_unload(self) -> None:
        """Unload provider and cancel polling."""
        if self._unsub_poll:
            self._unsub_poll()
            self._unsub_poll = None

    async def async_reload_item(self, item_id: str) -> bool:
        """Restart the given add-on (item_id = slug)."""
        return await _restart_addon(self.hass, item_id)

    @callback
    def _async_poll(self, _now: Any = None) -> None:
        """Schedule a scan from the time interval callback."""
        self.hass.async_create_task(self._async_scan())

    async def _async_scan(self) -> None:
        """Scan all installed add-ons and update health items."""
        addons = _get_addons(self.hass)
        if not addons:
            return

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
        """Extract the slug from an addon info object or dict."""
        if isinstance(addon, dict):
            return addon.get("slug")
        return getattr(addon, "slug", None)

    def _get_state(self, addon: Any) -> str:
        """Extract the raw state string from an addon info object or dict."""
        if isinstance(addon, dict):
            state = addon.get("state", _STATE_UNKNOWN)
        else:
            state = getattr(addon, "state", _STATE_UNKNOWN)
        # Normalize — may be an enum value
        return str(state.value if hasattr(state, "value") else state)

    def _get_name(self, addon: Any) -> str:
        """Extract the display name from an addon info object or dict."""
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
