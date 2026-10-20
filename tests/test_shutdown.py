"""Regression tests for shutdown events, resource cleanup, and normal alerts."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntryChange,
    ConfigEntryState,
)
from homeassistant.const import (
    EVENT_HOMEASSISTANT_CLOSE,
    EVENT_HOMEASSISTANT_FINAL_WRITE,
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_HOMEASSISTANT_STOP,
    STATE_UNAVAILABLE,
)
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.setup import async_setup_component

from custom_components.sentinel.const import (
    EVENT_ITEM_CHANGED,
    PROVIDER_APPS,
    PROVIDER_DEVICES,
    SIGNAL_SENTINEL_UPDATE,
)
from custom_components.sentinel.coordinator import SentinelCoordinator
from custom_components.sentinel.providers import HealthItem
from custom_components.sentinel.providers.apps import AppsProvider
from custom_components.sentinel.providers.integrations import IntegrationsProvider


@pytest.fixture
async def watched_light(hass: HomeAssistant) -> AsyncGenerator[str]:
    """Register a real eligible device and entity without loading its integration."""
    entry = MockConfigEntry(domain="hue", title="Hue")
    entry.add_to_hass(hass)
    entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("hue", "test")}, name="Test lamp"
    )
    entity = er.async_get(hass).async_get_or_create(
        "light", "hue", "test", device_id=device.id, config_entry=entry,
        suggested_object_id="test_lamp",
    )
    hass.states.async_set(entity.entity_id, "on")
    yield entity.entity_id
    # This entry is synthetic; do not unload the real Hue integration in teardown.
    entry._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)


@pytest.mark.parametrize("state", [CoreState.stopping, CoreState.final_write])
async def test_events_blocked_before_stop_listener(hass: HomeAssistant, state: CoreState) -> None:
    """A provider callback can run before Sentinel's stop listener is dispatched."""
    coordinator = SentinelCoordinator(hass, {})
    item = HealthItem("test", "Test", PROVIDER_DEVICES, False, "unavailable")
    events = []
    updates = []
    hass.bus.async_listen(EVENT_ITEM_CHANGED, callback(lambda event: events.append(event)))
    unsub = async_dispatcher_connect(hass, SIGNAL_SENTINEL_UPDATE, callback(lambda event: updates.append(event)))
    hass.set_state(state)
    coordinator._on_item_changed(item)
    await hass.async_block_till_done()
    assert not events
    assert not updates
    unsub()
    hass.set_state(CoreState.not_running)


@pytest.mark.parametrize(
    "phase", [EVENT_HOMEASSISTANT_STOP, EVENT_HOMEASSISTANT_FINAL_WRITE, EVENT_HOMEASSISTANT_CLOSE]
)
async def test_shutdown_does_not_start_delayed_automation(
    hass: HomeAssistant, watched_light: str, phase: str, caplog: pytest.LogCaptureFixture,
) -> None:
    """Late device teardown must not start a fresh 60-second automation run.

    Exercise real HA event triggers, script cancellation, and all shutdown stages.
    The close case also covers HA resetting is_stopping before the close event.
    """
    started = asyncio.Event()
    recovered = asyncio.Event()
    hass.bus.async_listen("test_debounce_started", callback(lambda _: started.set()))
    assert await async_setup_component(hass, "automation", {"automation": [{
        "alias": "Sentinel alert on problem",
        "triggers": [{"trigger": "event", "event_type": EVENT_ITEM_CHANGED}],
        "conditions": [{"condition": "template", "value_template": "{{ not trigger.event.data.healthy }}"}],
        "actions": [{"event": "test_debounce_started"}, {"delay": "00:01:00"}, {"event": "test_notification"}],
        "mode": "parallel", "max": 10, "max_exceeded": "silent",
    }]})
    await hass.async_start()
    await hass.async_block_till_done()
    coordinator = SentinelCoordinator(hass, {})
    await coordinator.async_setup()
    devices = coordinator._providers[PROVIDER_DEVICES]
    events = []

    @callback
    def capture(event: Event) -> None:
        events.append(event)
        if event.data["healthy"]:
            recovered.set()

    hass.bus.async_listen(EVENT_ITEM_CHANGED, capture)
    # Start a legitimate debounce run, then recover. HA must cancel this existing
    # run on stop, while Sentinel must not start another from teardown.
    hass.states.async_set(watched_light, STATE_UNAVAILABLE)
    await asyncio.wait_for(started.wait(), timeout=1)
    assert len(events) == 1
    assert not events[0].data["healthy"]
    hass.states.async_set(watched_light, "on")
    await asyncio.wait_for(recovered.wait(), timeout=1)
    events.clear()

    @callback
    def teardown(_event: Event) -> None:
        hass.states.async_set(watched_light, STATE_UNAVAILABLE)
        # Simulate a provider callback already queued before unsubscription.
        devices._on_state_changed(Event("state_changed", {"entity_id": watched_light}))

    hass.bus.async_listen(phase, teardown)
    try:
        # A test deadline detects a new 60s run without changing HA's timeouts.
        await asyncio.wait_for(hass.async_stop(), timeout=2)
        assert not events
        assert not coordinator._providers
        assert "Timed out waiting" not in caplog.text
    finally:
        await hass.services.async_call(
            "automation", "turn_off", {"entity_id": "automation.sentinel_alert_on_problem"}, blocking=True
        )
        await coordinator.async_unload()


async def test_normal_debounce_and_run_cap(hass: HomeAssistant, freezer) -> None:
    """Ordinary events still alert after 60s and retain the ten-run limit."""
    started = asyncio.Event()
    notifications = []
    hass.bus.async_listen("test_debounce_started", callback(lambda _: started.set()))
    hass.bus.async_listen("test_notification", callback(lambda event: notifications.append(event)))
    assert await async_setup_component(hass, "automation", {"automation": [{
        "alias": "Sentinel alert on problem",
        "triggers": [{"trigger": "event", "event_type": EVENT_ITEM_CHANGED}],
        "conditions": [{"condition": "template", "value_template": "{{ not trigger.event.data.healthy }}"}],
        "actions": [
            {"variables": {"item_sensor": "binary_sensor.sentinel_test_hue"}},
            {"event": "test_debounce_started"},
            {"delay": "00:01:00"},
            {"condition": "template", "value_template": "{{ is_state(item_sensor, 'on') }}"},
            {"event": "test_notification"},
        ],
        "mode": "parallel", "max": 10, "max_exceeded": "silent",
    }]})
    await hass.async_start()
    await hass.async_block_till_done()
    coordinator = SentinelCoordinator(hass, {})
    item = HealthItem("test", "Test", PROVIDER_DEVICES, False, "unavailable")
    hass.states.async_set("binary_sensor.sentinel_test_hue", "on")
    try:
        for _ in range(11):
            started.clear()
            coordinator._on_item_changed(item)
            # Yield enough turns to dispatch event triggers and write run counts.
            if _ < 10:
                await asyncio.wait_for(started.wait(), timeout=1)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert hass.states.get("automation.sentinel_alert_on_problem").attributes["current"] == 10
        freezer.tick(timedelta(seconds=59))
        async_fire_time_changed(hass)
        await asyncio.sleep(0)
        assert not notifications
        freezer.tick(timedelta(seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert len(notifications) == 10
        # A recovered item must fail the post-delay condition.
        started.clear()
        coordinator._on_item_changed(item)
        await asyncio.wait_for(started.wait(), timeout=1)
        hass.states.async_set("binary_sensor.sentinel_test_hue", "off")
        freezer.tick(timedelta(seconds=60))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert len(notifications) == 10
    finally:
        await hass.services.async_call(
            "automation", "turn_off", {"entity_id": "automation.sentinel_alert_on_problem"}, blocking=True
        )
        await coordinator.async_unload()


async def test_unload_removes_startup_listener_and_reload_monitors(
    hass: HomeAssistant, watched_light: str,
) -> None:
    """Unloading before HA starts must not leave a stale startup recheck."""
    hass.set_state(CoreState.not_running)
    old = SentinelCoordinator(hass, {})
    await old.async_setup()
    devices = old._providers[PROVIDER_DEVICES]
    assert devices._unsub_started is not None
    await old.async_unload()
    await old.async_unload()  # idempotent
    assert devices._unsub_started is None
    assert old._unsub_stop is None
    with patch.object(devices, "_async_evaluate_device") as evaluate:
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()
        evaluate.assert_not_called()
    await hass.async_start()
    await hass.async_block_till_done()
    # Reload while HA is running immediately checks existing unavailable devices.
    hass.states.async_set(watched_light, STATE_UNAVAILABLE)
    new = SentinelCoordinator(hass, {})
    events = []
    hass.bus.async_listen(EVENT_ITEM_CHANGED, callback(lambda event: events.append(event)))
    await new.async_setup()
    await hass.async_block_till_done()
    assert any(not event.data["healthy"] for event in events)
    events.clear()
    hass.states.async_set(watched_light, "on")
    await hass.async_block_till_done()
    assert any(event.data["healthy"] for event in events)
    await new.async_unload()


async def test_grace_period_and_stop_cleanup(hass: HomeAssistant, freezer) -> None:
    """Grace timers still debounce problems, then cancel and reject late callbacks."""
    entry = MockConfigEntry(domain="hue", title="Hue")
    entry.add_to_hass(hass)
    entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    provider = IntegrationsProvider(hass, grace_period=30)
    changed = MagicMock()
    await provider.async_setup(changed)
    entry._async_set_state(hass, ConfigEntryState.SETUP_ERROR, "test")
    await hass.async_block_till_done()
    assert provider._pending_timers
    changed.assert_not_called()
    # A transient failure that recovers inside the grace period stays silent.
    entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    await hass.async_block_till_done()
    assert not provider._pending_timers
    freezer.tick(timedelta(seconds=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    changed.assert_not_called()
    entry._async_set_state(hass, ConfigEntryState.SETUP_ERROR, "test")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    changed.assert_called_once()
    entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    await hass.async_block_till_done()
    assert changed.call_args.args[0].healthy
    entry._async_set_state(hass, ConfigEntryState.SETUP_ERROR, "test")
    await hass.async_block_till_done()
    timer = provider._pending_timers[entry.entry_id]
    late_callback = timer._callback
    await provider.async_unload()
    assert timer.cancelled()
    assert not provider._pending_timers
    assert provider._unsubscribe is None
    changed.reset_mock()
    late_callback()
    async_dispatcher_send(hass, SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntryChange.UPDATED, entry)
    await hass.async_block_till_done()
    assert not provider._pending_timers
    changed.assert_not_called()


@pytest.mark.parametrize("during_setup", [False, True])
async def test_stop_cancels_inflight_addon_scan(hass: HomeAssistant, during_setup: bool) -> None:
    """Stop cancels owned I/O, including initial scan; setup cannot resubscribe."""
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked_scan(_hass):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    with (
        patch("custom_components.sentinel.providers.apps.is_hassio", return_value=True),
        patch("custom_components.sentinel.providers.apps._get_addons_with_state", return_value=[]) as scan,
    ):
        coordinator = SentinelCoordinator(hass, {})
        if during_setup:
            scan.side_effect = blocked_scan
            setup_task = asyncio.create_task(coordinator.async_setup())
        else:
            await coordinator.async_setup()
            scan.side_effect = blocked_scan
            setup_task = None
        provider = coordinator._providers.get(PROVIDER_APPS)
        if not during_setup:
            provider._schedule_scan()
        await asyncio.wait_for(entered.wait(), timeout=1)
        provider = coordinator._providers[PROVIDER_APPS]
        provider._on_supervisor_event({})
        provider._schedule_scan()
        tasks = tuple(task for task in provider._scan_tasks if not task.done())
        assert len(tasks) == 3  # include scans queued behind the in-flight request
        hass.set_state(CoreState.stopping)
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await asyncio.wait_for(hass.async_block_till_done(), timeout=1)
        # Entry unload may follow the stop listener and must remain safe.
        await coordinator.async_unload()
        if setup_task:
            await setup_task
        assert cancelled.is_set()
        assert all(task.cancelled() for task in tasks)
        assert provider._unsub_poll is None
        assert provider._unsub_supervisor_event is None
        provider._schedule_scan()
        provider._on_supervisor_event({})
        assert not provider._scan_tasks
        hass.set_state(CoreState.not_running)


async def test_addon_scan_result_ignored_when_shutdown_begins(hass: HomeAssistant) -> None:
    """A request completing before the stop listener runs must not publish results."""
    provider = AppsProvider(hass)
    changed = MagicMock()

    async def response_at_shutdown(_hass):
        hass.set_state(CoreState.stopping)
        return [{"slug": "test", "name": "Test", "state": "error"}]

    provider._on_change = changed
    with patch("custom_components.sentinel.providers.apps._get_addons_with_state", side_effect=response_at_shutdown):
        await provider._async_scan()
    changed.assert_not_called()
    assert not provider.get_items()
    await provider.async_unload()
    hass.set_state(CoreState.not_running)


async def test_addon_poll_and_push_still_work(hass: HomeAssistant, freezer) -> None:
    """Polling and push still detect faults and recovery before unload."""
    changed = MagicMock()
    provider = AppsProvider(hass, poll_interval=60)
    with (
        patch("custom_components.sentinel.providers.apps.is_hassio", return_value=True),
        patch("custom_components.sentinel.providers.apps._get_addons_with_state", new_callable=AsyncMock) as scan,
    ):
        scan.return_value = [{"slug": "test", "state": "started"}]
        await provider.async_setup(changed)
        assert changed.call_args.args[0].healthy
        scan.return_value = [{"slug": "test", "state": "error"}]
        freezer.tick(timedelta(seconds=60))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert not changed.call_args.args[0].healthy
        scan.return_value = [{"slug": "test", "state": "started"}]
        provider._on_supervisor_event({})
        await hass.async_block_till_done()
        assert changed.call_args.args[0].healthy
        await provider.async_unload()
        scan.reset_mock()
        freezer.tick(timedelta(seconds=60))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        scan.assert_not_called()


async def test_boot_snapshot_waits_for_startup_recheck(hass: HomeAssistant, watched_light: str) -> None:
    """Transient boot unavailability stays healthy until HA has started."""
    hass.set_state(CoreState.not_running)
    hass.states.async_set(watched_light, STATE_UNAVAILABLE)
    coordinator = SentinelCoordinator(hass, {})
    await coordinator.async_setup()
    devices = coordinator._providers[PROVIDER_DEVICES]
    assert all(item.healthy for item in devices.get_items().values())
    await hass.async_start()
    await hass.async_block_till_done()
    assert all(not item.healthy for item in devices.get_items().values())
    await coordinator.async_unload()


async def test_config_entry_reload_keeps_monitoring(hass: HomeAssistant, watched_light: str) -> None:
    """A real entry reload replaces stopped providers and still reports problems."""
    from custom_components.sentinel.const import DOMAIN

    entry = MockConfigEntry(domain=DOMAIN, title="Sentinel", data={}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    old = hass.data[DOMAIN][entry.entry_id]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    new = hass.data[DOMAIN][entry.entry_id]
    assert new is not old
    assert old._stopped
    assert not old._providers
    assert old._unsub_stop is None
    assert new._unsub_stop is not None
    events = []
    hass.bus.async_listen(EVENT_ITEM_CHANGED, callback(lambda event: events.append(event)))
    hass.states.async_set(watched_light, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["provider"] == PROVIDER_DEVICES
    assert not events[0].data["healthy"]
