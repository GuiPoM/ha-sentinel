"""Constants for HA Sentinel."""
from __future__ import annotations

DOMAIN = "ha_sentinel"
NAME = "Sentinel"
VERSION = "0.1.0"

# Configuration keys
CONF_GRACE_PERIOD = "grace_period"
CONF_EXCLUDED_ENTRIES = "excluded_entries"
CONF_EXTRA_ENTRIES = "extra_entries"
CONF_FIRE_EVENTS = "fire_events"

# Defaults
DEFAULT_GRACE_PERIOD = 30  # seconds
DEFAULT_FIRE_EVENTS = True

# Sources considered "user-configured integrations" — monitored by default
WATCHED_SOURCES = {"user", "import", "repair"}

# Sources considered "auto-discovered devices" — ignored by default
AUTO_SOURCES = {"bluetooth", "dhcp", "zeroconf", "hassio_discovery", "ssdp", "homekit", "mqtt"}

# Event fired on state change
EVENT_ITEM_CHANGED = f"{DOMAIN}_item_changed"

# Dispatcher signal for internal updates
SIGNAL_SENTINEL_UPDATE = f"{DOMAIN}_update"

# Provider identifiers
PROVIDER_INTEGRATIONS = "integrations"
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
