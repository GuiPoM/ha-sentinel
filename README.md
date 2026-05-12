# Sentinel

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/GuiPoM/ha-sentinel.svg)](https://github.com/GuiPoM/ha-sentinel/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue)](https://www.home-assistant.io/)

**Proactive health monitoring for Home Assistant — know when something breaks before you notice the lights aren't responding.**

![Sentinel](icon.png)

Sentinel watches your integrations, physical devices and applications \(add-ons\) in real time. No polling. No YAML. No manual entity wrangling. When something goes wrong, you know immediately.

---

## What it does

| Without Sentinel | With Sentinel |
|---|---|
| You notice Netatmo stopped reporting — an hour ago | Push notification the moment it fails |
| You check 40 Lovelace cards to find the broken one | One card showing exactly what's down |
| You wonder if the Z-Wave lock is really unavailable | Sentinel tells you — and since when |
| Mosquitto crashed silently and MQTT is down | Sentinel alerts you immediately |

---

## Features

- **Real-time integration monitoring** — listens to HA's internal dispatcher, zero polling
- **Physical device monitoring** — detects unavailable entities (Hue, Z-Wave, Zigbee, Matter…)
- **Add-on monitoring** — queries the Supervisor API directly (real-time, no cache) for crashed or errored add-ons (HA OS only)
- **Smart noise reduction** — if an integration fails, its devices are suppressed to avoid alert storms
- **Severity levels** — `error` (setup_error, migration_error) vs `warning` (setup_retry)
- **Grace period** — configurable delay before flagging a problem, avoids false positives on startup
- **Failure history** — `failure_count` tracks how many times each item has broken
- **Event bus** — fires `sentinel_item_changed` for use in automations
- **Reload action** — `sentinel.reload` to restart a broken integration or application (add-on)
- **Three providers** — integrations, devices, apps (add-ons)

---

## Installation

### Via HACS (recommended)

1. In HACS, go to **Integrations** → **Custom repositories**
2. Add `https://github.com/GuiPoM/ha-sentinel` — type **Integration**
3. Search for **Sentinel** and install
4. Restart Home Assistant
5. Go to **Settings → Devices & Services → Add Integration** → search **Sentinel**
6. Sentinel starts immediately with sensible defaults — no configuration required

<details>
<summary>Manual installation</summary>

Copy `custom_components/sentinel/` to your `<config>/custom_components/` directory and restart.

</details>

---

## Configuration

All options are available via **Settings → Devices & Services → Sentinel → Configure**.
Sentinel works out of the box — configure only what you need to adjust.

| Option | Default | Description |
|---|---|---|
| Fire events on the HA bus | Yes | Fire `sentinel_item_changed` on every state change — required for automations |
| Grace period (seconds) | 30s | How long an integration must stay failed before being reported (0 = immediate) |
| Excluded integrations | None | Integrations to exclude from monitoring (dropdown, your install) |
| Ignored device sources | None | Device sources to ignore (dropdown, computed from your device registry) |
| Ignored devices | None | Specific devices to exclude from monitoring |
| Report stopped applications as warning | No | When enabled, stopped applications are reported as warnings |
| Application poll interval (seconds) | 60s | How often Sentinel queries the Supervisor (30–300s) |

### What gets monitored by default

**Integrations** — all user-configured integrations except:
- Internal helpers (`template`, `group`, `input_*`, `automation`, `script`…)
- System domains (`homeassistant`, `hacs`, `sentinel`)
- User-disabled integrations (`disabled_by = user`)

**Devices** — entities in physical domains (`light`, `switch`, `lock`, `climate`, `cover`, `valve`…) and vital device classes (`temperature`, `humidity`, `motion`, `smoke`, `door`, `window`, `co`, `co2`…)

**Applications** — all installed applications on HA OS, queried directly from the Supervisor API

### Applications provider (HA OS only)

> The Applications provider is only active on HA OS / Supervised installations. On other installation types it is silently skipped.

**Application states:**

| State | Severity | Meaning |
|---|---|---|
| `started` | `ok` | Running normally |
| `stopped` | `ok` (or `warning` if option enabled) | Intentionally stopped |
| `error` | `error` | Failure on start/stop |
| `unknown` | `warning` | Unknown state |
| `startup` | ignored | Transient — application is starting up |

---

## Entities

### Binary sensors

One `binary_sensor.sentinel_*` per monitored item:

- **`on`** = problem detected
- **`off`** = healthy

**Attributes:**

| Attribute | Description |
|---|---|
| `provider` | `integrations`, `devices`, or `apps` |
| `domain` | Integration domain, device source, or `hassio` for add-ons |
| `state` | Raw state (e.g. `setup_error`, `unavailable`, `error`) |
| `severity` | `ok`, `warning` or `error` |
| `reason` | Error message if available |
| `since` | ISO timestamp of last state change |
| `failure_count` | Number of times this item has failed |
| `can_reload` | Whether reload is supported (integrations + add-ons) |
| `device_url` | Direct link to the HA device page (devices only) |
| `slug` | Add-on slug (apps only) |

### Sensor

- `sensor.sentinel_problems` — total number of unhealthy items across all providers

---

## Events

When an item changes health state, Sentinel fires `sentinel_item_changed`:

```yaml
event_type: sentinel_item_changed
data:
  item_id: "abc123..."
  provider: "integrations"        # "integrations", "devices", or "apps"
  item_type: "integration"        # "integration", "device", or "addon"
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

Reload a broken integration or restart a crashed add-on.

```yaml
action: sentinel.reload
data:
  item_id: "<config_entry_id or addon_slug>"
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

# Add-ons card (HA OS only)
type: custom:ha-sentinel-apps-card
```

---

## Severity levels

| State | Severity | Meaning |
|---|---|---|
| `loaded` / `started` / `ok` | `ok` | Running normally |
| `setup_retry` / `stopped`* | `warning` | May recover on its own |
| `not_loaded`** | `warning` | Integration should be running but isn't |
| `setup_error` / `error` | `error` | Needs attention |
| `migration_error` | `error` | Migration failed |
| `failed_unload` | `error` | Could not unload cleanly |
| `unavailable` | `error` | Device entity unavailable |
| `unknown` | `warning` | Add-on in unknown state |

*`stopped` only reported as warning if `watch_stopped_addons` is enabled.
**`not_loaded` without `disabled_by` — integration is not intentionally disabled.

---

## License

MIT — © 2026 GuiPoM
