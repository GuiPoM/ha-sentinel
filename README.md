# Sentinel

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/GuiPoM/ha-sentinel.svg)](https://github.com/GuiPoM/ha-sentinel/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue)](https://www.home-assistant.io/)

**Proactive health monitoring for Home Assistant — know when something breaks before you notice the lights aren't responding.**

Sentinel watches your integrations and physical devices in real time. No polling. No YAML. No manual entity wrangling. When something goes wrong, you know immediately.

---

## What it does

| Without Sentinel | With Sentinel |
|---|---|
| You notice Netatmo stopped reporting — an hour ago | Push notification the moment it fails |
| You check 40 Lovelace cards to find the broken one | One card showing exactly what's down |
| You wonder if the Z-Wave lock is really unavailable | Sentinel tells you — and since when |

---

## Features

- **Real-time integration monitoring** — listens to HA's internal dispatcher, zero polling
- **Physical device monitoring** — detects unavailable entities and silent devices (no update >24h)
- **Smart noise reduction** — if an integration fails, its devices are suppressed to avoid alert storms
- **Severity levels** — `error` (setup_error, migration_error) vs `warning` (setup_retry)
- **Grace period** — configurable delay before flagging a problem, avoids false positives on startup
- **Failure history** — `failure_count` tracks how many times each item has broken
- **Event bus** — fires `sentinel_item_changed` for use in automations
- **Reload action** — `sentinel.reload` to restart a broken integration from an automation
- **Extensible** — provider architecture ready for future monitoring types

---

## Installation

### Via HACS (recommended)

1. In HACS, go to **Integrations** → **Custom repositories**
2. Add `https://github.com/GuiPoM/ha-sentinel` — type **Integration**
3. Search for **Sentinel** and install
4. Restart Home Assistant
5. Go to **Settings → Devices & Services → Add Integration** → search **Sentinel**

<details>
<summary>Manual installation</summary>

Copy `custom_components/sentinel/` to your `<config>/custom_components/` directory and restart.

</details>

---

## Configuration

After adding the integration, configure via **Settings → Devices & Services → Sentinel → Configure**:

### Integrations provider

| Option | Default | Description |
|---|---|---|
| Grace period | 30s | How long an integration must stay failed before being reported (0 = immediate) |
| Fire events | Yes | Fire `sentinel_item_changed` on the HA event bus on every state change |
| Excluded integrations | None | Integrations to exclude from monitoring |
| Extra integrations | None | Auto-discovered or system entries to add explicitly |

### Devices provider

| Option | Default | Description |
|---|---|---|
| Ignored device sources | None | Integration sources to ignore (e.g. `mobile_app`, `cast`) |
| Ignored devices | None | Specific devices to exclude from monitoring |

> **How device health is determined:** a device is unhealthy when at least one of its monitored entities becomes `unavailable`. This is the only reliable signal that a device has lost connectivity with its hub (Hue, Z-Wave JS, Zigbee2MQTT, Matter…). There is no "silence" detection — event-based sensors (motion, door, smoke, water leak…) only report on state change, which is normal behavior.

### What gets monitored by default

**Integrations** — all user-configured integrations except:
- Internal helpers (`template`, `group`, `input_*`, `automation`, `script`…)
- System domains (`homeassistant`, `hacs`, `sentinel`)

**Devices** — entities in physical domains (`light`, `switch`, `lock`, `climate`, `cover`, `valve`…) and vital device classes (`temperature`, `humidity`, `motion`, `smoke`, `door`, `window`, `co`, `co2`…)

---

## Entities

### Binary sensors

One `binary_sensor.sentinel_*` per monitored item:

- **`on`** = problem detected
- **`off`** = healthy

**Attributes:**

| Attribute | Description |
|---|---|
| `provider` | `integrations` or `devices` |
| `domain` | Integration domain or device source |
| `state` | Raw state (e.g. `setup_error`, `unavailable`) |
| `severity` | `ok`, `warning` or `error` |
| `reason` | Error message if available |
| `since` | ISO timestamp of last state change |
| `failure_count` | Number of times this item has failed |
| `can_reload` | Whether reload is supported (integrations only) |
| `device_url` | Direct link to the HA device page (devices only) |

### Sensor

- `sensor.sentinel_problems` — total number of unhealthy items across all providers

---

## Events

When an item changes health state, Sentinel fires `sentinel_item_changed`:

```yaml
event_type: sentinel_item_changed
data:
  item_id: "abc123..."
  provider: "integrations"        # or "devices"
  item_type: "integration"        # or "device"
  name: "Netatmo"
  domain: "netatmo"
  source: "NETATMO"
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
  alias: "Sentinel — Alert on problem"
  trigger:
    - platform: event
      event_type: sentinel_item_changed
  condition:
    - condition: template
      value_template: "{{ not trigger.event.data.healthy }}"
  action:
    - action: notify.mobile_app_your_phone
      data:
        title: "{{ trigger.event.data.name }} ({{ trigger.event.data.domain }}) — {{ trigger.event.data.item_type }} problem"
        message: >
          {{ trigger.event.data.state | replace('_', ' ') }}
          {%- if trigger.event.data.reason %} — {{ trigger.event.data.reason }}{% endif %}
```

---

## Actions

### `sentinel.reload`

Reload a broken integration.

```yaml
action: sentinel.reload
data:
  item_id: "<config_entry_id>"
```

### `sentinel.reset_failure_count`

Reset the failure counter for an item.

```yaml
action: sentinel.reset_failure_count
data:
  item_id: "<config_entry_id>"
```

### `sentinel.check`

Re-fire events for all currently unhealthy items (useful to trigger automations on demand).

```yaml
action: sentinel.check
```

### `sentinel.purge`

Remove all Sentinel entities from the registry. Restart HA after calling this to recreate them cleanly.

```yaml
action: sentinel.purge
```

---

## Lovelace Card

Install the companion Lovelace card for a visual health dashboard:

**[GuiPoM/lovelace-ha-sentinel](https://github.com/GuiPoM/lovelace-ha-sentinel)**

```yaml
# Integrations card
type: custom:ha-sentinel-card

# Devices card
type: custom:ha-sentinel-devices-card
```

---

## Severity levels

| State | Severity | Meaning |
|---|---|---|
| `loaded` / `ok` | `ok` | Running normally |
| `setup_retry` | `warning` | Retrying setup — may recover |
| `setup_error` | `error` | Setup failed — needs attention |
| `migration_error` | `error` | Migration failed |
| `failed_unload` | `error` | Could not unload cleanly |
| `unavailable` | `error` | Device entity unavailable — device has lost connectivity with its hub |

---

## License

MIT — © 2026 GuiPoM
