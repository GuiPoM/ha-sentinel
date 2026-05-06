# Sentinel

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/GuiPoM/ha-sentinel.svg)](https://github.com/GuiPoM/ha-sentinel/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue)](https://www.home-assistant.io/)

**Proactive health monitoring for Home Assistant integrations — get notified the moment one goes down.**

Sentinel watches your integrations in real time and alerts you before you notice the lights aren't responding or the lawn mower stopped reporting. No polling, no YAML, no manual entity wrangling.

---

## Features

- **Real-time monitoring** — listens to HA's internal dispatcher, zero polling
- **Smart filtering** — monitors real integrations only, ignores helpers, auto-discovered devices and system components
- **Severity levels** — distinguishes errors (`setup_error`, `migration_error`) from warnings (`setup_retry`)
- **Grace period** — configurable delay before flagging a problem, avoids false positives on startup
- **Failure history** — `failure_count` attribute tracks how many times each integration has broken
- **Bus events** — fires `sentinel_item_changed` for use in automations
- **Reload action** — `ha_sentinel.reload` to restart a broken integration from an automation or dashboard
- **Lovelace card** — visual dashboard with color-coded status and inline reload button (separate repo)
- **Extensible** — provider architecture ready for Apps (add-ons) monitoring in v2

---

## Installation

### Via HACS (recommended)

1. In HACS, go to **Integrations** → **Custom repositories**
2. Add `https://github.com/GuiPoM/ha-sentinel` — type **Integration**
3. Search for **Sentinel** and install
4. Restart Home Assistant
5. Go to **Settings → Devices & Services → Add Integration** → search **Sentinel**

### Manual

Copy `custom_components/ha_sentinel/` to your `<config>/custom_components/` directory and restart.

---

## Configuration

After adding the integration, configure via **Settings → Devices & Services → Sentinel → Configure**:

| Option | Default | Description |
|---|---|---|
| Grace period | 30s | How long an integration must stay in a failed state before being reported (0 = immediate) |
| Fire events | Yes | Fire `sentinel_item_changed` on the HA event bus on every state change |
| Excluded integrations | None | User-configured integrations to exclude from monitoring |
| Extra integrations to monitor | None | Auto-discovered or system entries to add explicitly |

### What gets monitored by default

Sentinel monitors all integrations **except**:

- `source=system` — HA internal components (Backup, Supervisor, go2rtc...)
- `source=ignore` — entries you have deliberately dismissed in HA
- Helper domains — `template`, `group`, `ping`, `uptime`, `local_file`, `shell_command`, and other HA utilities

Everything else (Netatmo, Z-Wave, Zigbee, MQTT, ESPHome, cloud integrations...) is monitored by default.

---

## Entities

### Binary sensors

One `binary_sensor` per monitored integration:

- **`on`** = problem detected
- **`off`** = healthy

**Attributes:**

| Attribute | Description |
|---|---|
| `provider` | `integrations` (v1) |
| `domain` | Integration domain (e.g. `netatmo`) |
| `state` | Raw HA config entry state |
| `severity` | `ok`, `warning` or `error` |
| `reason` | Error message if available |
| `since` | ISO timestamp of last state change |
| `failure_count` | Number of times this integration has entered an unhealthy state |
| `can_reload` | Whether reload is supported |

### Sensor

- `sensor.sentinel_problems` — total number of unhealthy integrations
  - Attribute `problems`: list of currently unhealthy items with details

---

## Severity levels

| State | Severity | Meaning |
|---|---|---|
| `loaded` | `ok` | Running normally |
| `setup_retry` | `warning` | Retrying setup — may recover on its own |
| `setup_error` | `error` | Setup failed — requires attention |
| `migration_error` | `error` | Migration failed |
| `failed_unload` | `error` | Could not unload cleanly |

---

## Actions

### `ha_sentinel.reload`

Reload a broken integration.

```yaml
action: ha_sentinel.reload
data:
  item_id: "<config_entry_id>"
```

### `ha_sentinel.reset_failure_count`

Reset the failure counter for an integration.

```yaml
action: ha_sentinel.reset_failure_count
data:
  item_id: "<config_entry_id>"
```

---

## Events

When an integration changes health state, Sentinel fires:

```yaml
event_type: sentinel_item_changed
data:
  item_id: "abc123def456..."
  provider: "integrations"
  name: "Netatmo"
  healthy: false
  state: "setup_error"
  severity: "error"
  reason: "Token expired"
  failure_count: 3
  since: "2026-05-06T11:00:00"
```

### Example automation: notify on problem

```yaml
automation:
  - alias: "Notify when integration breaks"
    trigger:
      - platform: event
        event_type: sentinel_item_changed
    condition:
      - condition: template
        value_template: "{{ not trigger.event.data.healthy }}"
    action:
      - action: notify.mobile_app_your_phone
        data:
          title: "Integration problem"
          message: >
            {{ trigger.event.data.name }} — {{ trigger.event.data.state }}
            {% if trigger.event.data.reason %}({{ trigger.event.data.reason }}){% endif %}
```

---

## Lovelace Card

The Lovelace card is distributed as a separate HACS frontend repository:
**[GuiPoM/lovelace-ha-sentinel](https://github.com/GuiPoM/lovelace-ha-sentinel)**

```yaml
type: custom:ha-sentinel-card
title: "Integration Status"
show_ok: true
```

---

## Roadmap

- **v0.x** — Integration monitoring (config entries) ✅
- **v1.0** — Apps (add-ons) monitoring via Supervisor API
- **v1.x** — Notification blueprints, HACS default repository submission

---

## License

MIT — © 2026 GuiPoM
