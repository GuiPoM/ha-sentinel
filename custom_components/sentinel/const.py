"""Constants for HA Sentinel."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import Platform

DOMAIN = "sentinel"
NAME = "Sentinel"

# Configuration keys
CONF_GRACE_PERIOD = "grace_period"
CONF_EXCLUDED_ENTRIES = "excluded_entries"
CONF_FIRE_EVENTS = "fire_events"

# Configuration keys — devices provider
CONF_IGNORED_DEVICE_SOURCES = "ignored_device_sources"
CONF_IGNORED_DEVICE_IDS = "ignored_device_ids"

# Configuration keys — apps provider
CONF_WATCH_STOPPED_ADDONS = "watch_stopped_addons"
CONF_APPS_POLL_INTERVAL = "apps_poll_interval"
CONF_IGNORED_ADDON_SLUGS = "ignored_addon_slugs"

# Defaults
DEFAULT_GRACE_PERIOD = 30  # seconds
DEFAULT_FIRE_EVENTS = True
DEFAULT_WATCH_STOPPED_ADDONS = False
DEFAULT_APPS_POLL_INTERVAL = 60  # seconds

# Sources that are always excluded — system internals or user-ignored discoveries
EXCLUDED_SOURCES = {"system", "ignore"}

# Domains that are HA-internal helpers/utilities, not real integrations
EXCLUDED_DOMAINS = {
    "template",
    "group",
    "ping",
    "uptime",
    "local_file",
    "shell_command",
    "smtp",
    "input_boolean",
    "input_number",
    "input_select",
    "input_text",
    "input_datetime",
    "input_button",
    "counter",
    "timer",
    "schedule",
    "zone",
    "person",
    "tag",
    "scene",
    "script",
    "automation",
    "sun",
    "moon",
    "todo",
    "calendar",
    "repairs",
    "persistent_notification",
    "homeassistant",
    "hacs",        # HACS manages itself, not a monitored integration
    "sentinel", # Never watch ourselves
}

# Event fired on state change
EVENT_ITEM_CHANGED = f"{DOMAIN}_item_changed"

# Dispatcher signal for internal updates
SIGNAL_SENTINEL_UPDATE = f"{DOMAIN}_update"

# Provider identifiers
PROVIDER_INTEGRATIONS = "integrations"
PROVIDER_DEVICES = "devices"
PROVIDER_APPS = "apps"  # v2 stub

# Config entry states considered healthy
HEALTHY_STATES = {"loaded"}

# Config entry states considered a real problem (error severity)
ERROR_STATES = {
    "setup_error",
    "migration_error",
    "failed_unload",
}

# Config entry states considered unstable (warning severity)
WARNING_STATES = {
    "setup_retry",
}

# All problem states (error + warning)
PROBLEM_STATES = ERROR_STATES | WARNING_STATES

# Config entry states considered transient (ignored during grace period)
TRANSIENT_STATES = {
    "setup_in_progress",
    "unload_in_progress",
}

# Config entry states considered inactive (intentionally not loaded)
INACTIVE_STATES = {
    "not_loaded",
}

# Any unknown state is treated as a warning

# --- Devices provider ---

# Physical domains: entities in these domains are always monitored (regardless of device_class)
PHYSICAL_DOMAINS: frozenset[str] = frozenset({
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.LOCK,
    Platform.VACUUM,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.VALVE,
    Platform.FAN,
    Platform.HUMIDIFIER,
    Platform.WATER_HEATER,
    Platform.LAWN_MOWER,
})

# Vital device classes: sensor/binary_sensor entities with these classes are monitored
VITAL_DEVICE_CLASSES: frozenset[str] = frozenset({
    # Environment
    SensorDeviceClass.TEMPERATURE,
    SensorDeviceClass.HUMIDITY,
    SensorDeviceClass.MOISTURE,
    SensorDeviceClass.CO,
    SensorDeviceClass.CO2,
    # Safety / Security
    BinarySensorDeviceClass.MOTION,
    BinarySensorDeviceClass.OCCUPANCY,
    BinarySensorDeviceClass.SMOKE,
    BinarySensorDeviceClass.GAS,
    BinarySensorDeviceClass.CO,
    BinarySensorDeviceClass.DOOR,
    BinarySensorDeviceClass.GARAGE_DOOR,
    BinarySensorDeviceClass.WINDOW,
    BinarySensorDeviceClass.OPENING,
    BinarySensorDeviceClass.MOISTURE,
    BinarySensorDeviceClass.VIBRATION,
    BinarySensorDeviceClass.TAMPER,
    BinarySensorDeviceClass.SAFETY,
    BinarySensorDeviceClass.CONNECTIVITY,
})
