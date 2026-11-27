"""Serve and load the bundled Sentinel cards without modifying dashboards."""
from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
import logging
from pathlib import Path
from urllib.parse import urlsplit

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
CARD_PATH = Path(__file__).parent / "frontend" / "ha-sentinel.js"
CARD_URL = f"/{DOMAIN}/ha-sentinel.js"
DATA_CARD_URL = f"{DOMAIN}_card_url"
LEGACY_PATHS = {
    "/hacsfiles/lovelace-ha-sentinel/ha-sentinel.js",
    "/local/community/lovelace-ha-sentinel/ha-sentinel.js",
    "/local/ha-sentinel.js",
}


def _card_version() -> str:
    """Use the JS content as a cache key, independently of release tags."""
    return sha256(CARD_PATH.read_bytes()).hexdigest()[:12]


async def async_setup_cards(hass: HomeAssistant) -> Callable[[], None] | None:
    """Load the cards in storage and YAML dashboards when frontend is present."""
    if "frontend" not in hass.config.components:
        return None

    try:
        # Leave existing standalone installations alone rather than loading two
        # versions of the same custom elements. No user resources are deleted.
        module_manager = hass.data.get(frontend.DATA_EXTRA_MODULE_URL)
        urls = set(module_manager.urls) if module_manager is not None else set()
        if lovelace := hass.data.get(LOVELACE_DATA):
            resources = lovelace.resources
            if not resources.loaded:
                await resources.async_load()
                resources.loaded = True
            urls.update(item["url"] for item in resources.async_items())
        if any(urlsplit(url).path in LEGACY_PATHS for url in urls):
            _LOGGER.info(
                "Standalone Sentinel cards detected; remove their resource and "
                "reload Sentinel to use the bundled cards"
            )
            return None

        url = hass.data.get(DATA_CARD_URL)
        if url is None:
            version = await hass.async_add_executor_job(_card_version)
            await hass.http.async_register_static_paths([
                StaticPathConfig(CARD_URL, str(CARD_PATH), False),
            ])
            url = f"{CARD_URL}?v={version}"
            hass.data[DATA_CARD_URL] = url

        frontend.add_extra_js_url(hass, url)
    except Exception:  # Cards must never prevent backend monitoring from starting.
        _LOGGER.exception("Unable to load bundled Sentinel cards")
        return None

    @callback
    def remove_cards() -> None:
        """Remove only our module URL; HTTP routes persist across entry reloads."""
        manager = hass.data.get(frontend.DATA_EXTRA_MODULE_URL)
        if manager is not None and url in manager.urls:
            frontend.remove_extra_js_url(hass, url)

    return remove_cards
