"""Constants for HA Sentinel."""
from __future__ import annotations

DOMAIN = "ha_sentinel"
NAME = "HA Sentinel"
VERSION = "0.1.0"

# Configuration keys
CONF_GRACE_PERIOD = "grace_period"
CONF_EXCLUDED_ENTRIES = "excluded_entries"
CONF_FIRE_EVENTS = "fire_events"

# Defaults
DEFAULT_GRACE_PERIOD = 30  # seconds
DEFAULT_FIRE_EVENTS = True

# Event fired on state change
EVENT_ITEM_CHANGED = f"{DOMAIN}_item_changed"

# Dispatcher signal for internal updates
SIGNAL_SENTINEL_UPDATE = f"{DOMAIN}_update"

# Provider identifiers
PROVIDER_INTEGRATIONS = "integrations"
PROVIDER_APPS = "apps"  # v2 stub

# Config entry states considered healthy
HEALTHY_STATES = {"loaded"}

# Config entry states considered problematic
PROBLEM_STATES = {
    "setup_error",
    "setup_retry",
    "migration_error",
    "failed_unload",
}

# Config entry states considered transient (ignored during cooldown)
TRANSIENT_STATES = {
    "setup_in_progress",
    "unload_in_progress",
    "not_loaded",
}
