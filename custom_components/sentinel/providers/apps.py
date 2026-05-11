"""Apps (add-ons) provider stub for HA Sentinel — v2."""
from __future__ import annotations

from collections.abc import Callable
import logging

from ..const import PROVIDER_APPS
from . import HealthItem, HealthProvider

_LOGGER = logging.getLogger(__name__)


class AppsProvider(HealthProvider):
    """Health provider for Home Assistant apps (add-ons).

    This is a v2 stub. Full implementation will use the Supervisor REST API.
    Only available on Home Assistant OS / Supervised installations.
    """

    @property
    def provider_id(self) -> str:
        return PROVIDER_APPS

    @property
    def name(self) -> str:
        return "Apps"

    @property
    def available(self) -> bool:
        """Only available when Supervisor (hassio) is loaded."""
        return "hassio" in self.hass.config.components

    async def async_setup(self, on_change_callback: Callable[[HealthItem], None]) -> None:
        """Set up the apps provider (stub — not yet implemented)."""
        _LOGGER.info(
            "HA Sentinel: Apps provider is a v2 stub and not yet implemented."
        )

    async def async_unload(self) -> None:
        """Unload the apps provider."""

    async def async_reload_item(self, item_id: str) -> bool:
        """Restart the given add-on (stub)."""
        _LOGGER.warning(
            "HA Sentinel: Apps provider reload not yet implemented (item_id=%s)", item_id
        )
        return False
