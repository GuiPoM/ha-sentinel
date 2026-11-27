"""Tests for the optional, reload-safe bundled card registration."""
from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components import frontend
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant

from custom_components.sentinel.frontend import (
    CARD_PATH,
    CARD_URL,
    async_setup_cards,
)


@pytest.fixture
def frontend_hass(hass: HomeAssistant) -> HomeAssistant:
    """Provide frontend state without starting a real HTTP server."""
    hass.config.components.add("frontend")
    hass.data[frontend.DATA_EXTRA_MODULE_URL] = frontend.UrlManager(MagicMock(), [])
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    return hass


async def test_headless_monitoring_does_not_register_cards(hass: HomeAssistant):
    """Do not require frontend or HTTP for backend monitoring."""
    assert await async_setup_cards(hass) is None


async def test_cards_register_once_across_entry_reloads(frontend_hass):
    """Only the versioned module is loaded; the static route is registered once."""
    hass = frontend_hass
    remove = await async_setup_cards(hass)
    assert remove is not None
    manager = hass.data[frontend.DATA_EXTRA_MODULE_URL]
    urls = manager.urls
    assert len(urls) == 1
    url = next(iter(urls))
    assert url == f"{CARD_URL}?v={sha256(CARD_PATH.read_bytes()).hexdigest()[:12]}"
    configs = hass.http.async_register_static_paths.call_args.args[0]
    assert configs[0].url_path == CARD_URL
    assert configs[0].path == str(CARD_PATH)
    manager.add("/other-card.js")
    remove()
    remove()  # Cleanup is idempotent.
    assert manager.urls == {"/other-card.js"}
    assert await async_setup_cards(hass) is not None
    assert manager.urls == {url, "/other-card.js"}
    hass.http.async_register_static_paths.assert_awaited_once()


async def test_existing_registration_is_idempotent(frontend_hass):
    """Repeated setup does not duplicate URLs or register conflicting routes."""
    assert await async_setup_cards(frontend_hass) is not None
    assert await async_setup_cards(frontend_hass) is not None
    assert len(frontend_hass.data[frontend.DATA_EXTRA_MODULE_URL].urls) == 1
    frontend_hass.http.async_register_static_paths.assert_awaited_once()


@pytest.mark.parametrize("url", [
    "/hacsfiles/lovelace-ha-sentinel/ha-sentinel.js?hacstag=123",
    "/local/community/lovelace-ha-sentinel/ha-sentinel.js?v=1230780623070",
    "/local/ha-sentinel.js?v=1",
])
@pytest.mark.parametrize("yaml_mode", [False, True])
async def test_standalone_resources_are_preserved(frontend_hass, url, yaml_mode):
    """Do not mutate existing YAML/storage resources or load a second card."""
    resources = MagicMock(loaded=yaml_mode)
    resources.async_load = AsyncMock()
    resources.async_items.return_value = [{"url": url, "type": "module"}]
    frontend_hass.data[LOVELACE_DATA] = SimpleNamespace(resources=resources)
    assert await async_setup_cards(frontend_hass) is None
    assert frontend_hass.data[frontend.DATA_EXTRA_MODULE_URL].urls == set()
    frontend_hass.http.async_register_static_paths.assert_not_awaited()
    if yaml_mode:
        resources.async_load.assert_not_awaited()
    else:
        resources.async_load.assert_awaited_once()
    resources.async_update_item.assert_not_called()
    resources.async_delete_item.assert_not_called()


async def test_standalone_extra_module_is_preserved(frontend_hass):
    """Also detect manually installed cards loaded outside Lovelace resources."""
    url = "/local/ha-sentinel.js"
    frontend_hass.data[frontend.DATA_EXTRA_MODULE_URL].add(url)
    assert await async_setup_cards(frontend_hass) is None
    assert frontend_hass.data[frontend.DATA_EXTRA_MODULE_URL].urls == {url}


@pytest.mark.parametrize("yaml_mode", [False, True])
async def test_unrelated_resources_do_not_prevent_bundling(frontend_hass, yaml_mode):
    resources = MagicMock(loaded=yaml_mode)
    resources.async_load = AsyncMock()
    resources.async_items.return_value = [{"url": "/other-card.js", "type": "module"}]
    frontend_hass.data[LOVELACE_DATA] = SimpleNamespace(resources=resources)
    assert await async_setup_cards(frontend_hass) is not None
    assert len(frontend_hass.data[frontend.DATA_EXTRA_MODULE_URL].urls) == 1


async def test_http_failure_is_nonfatal_and_can_be_retried(frontend_hass):
    """Card failures must not prevent monitoring, or poison route registration."""
    frontend_hass.http.async_register_static_paths.side_effect = RuntimeError("HTTP error")
    with patch("custom_components.sentinel.frontend._LOGGER.exception"):
        assert await async_setup_cards(frontend_hass) is None
    assert frontend_hass.data[frontend.DATA_EXTRA_MODULE_URL].urls == set()
    frontend_hass.http.async_register_static_paths.side_effect = None
    assert await async_setup_cards(frontend_hass) is not None
