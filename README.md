# Sentinel

[![GitHub release](https://img.shields.io/github/release/GuiPoM/ha-sentinel.svg)](https://github.com/GuiPoM/ha-sentinel/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue)](https://www.home-assistant.io/)

**Proactive health monitoring for Home Assistant â€” know when something breaks before you notice the lights aren't responding.**

![Sentinel](icon.png)

Sentinel watches your integrations, physical devices and applications \(add-ons\) in real time. No polling. No YAML. No manual entity wrangling. When something goes wrong, you know immediately.

---

## What it does

| Without Sentinel | With Sentinel |
|---|---|
| You notice Netatmo stopped reporting â€” an hour ago | Push notification the moment it fails |
| You check 40 Lovelace cards to find the broken one | One card showing exactly what's down |
| You wonder if the Z-Wave lock is really unavailable | Sentinel tells you â€” and since when |
| Mosquitto crashed silently and MQTT is down | Sentinel alerts you immediately |

---

## Features

- **Real-time integration monitoring** â€” listens to HA's internal dispatcher, zero polling
- **Physical device monitoring** â€” detects unavailable entities (Hue, Z-Wave, Zigbee, Matterâ€¦)
- **Application (add-on) monitoring** â€” queries the Supervisor API directly (real-time, no cache) for crashed or errored applications (HA OS only)
- **Smart noise reduction** â€” if an integration fails, its devices are suppressed to avoid alert storms
- **Severity levels** â€” `error` (setup_error, migration_error) vs `warning` (setup_retry)
- **Grace period** â€” configurable delay before flagging a problem, avoids false positives on startup
- **Failure history** â€” `failure_count` tracks how many times each item has broken
- **Event bus** â€” fires `sentinel_item_changed` for use in automations
- **Reload action** â€” `sentinel.reload` to restart a broken integration or application (add-on)
- **Three providers** â€” integrations, devices, applications (add-ons)

---

## Installation

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=GuiPoM&repository=ha-sentinel&category=integration)

<details>
<summary>Install via HACS (manual steps)</summary>

1. In HACS, go to **Integrations** â†’ three-dot menu â†’ **Custom repositories**
2. Add `https://github.com/GuiPoM/ha-sentinel` â€” type **Integration**
3. Search for **Sentinel** and install
4. Restart Home Assistant
5. Go to **Settings â†’ Devices & Services â†’ Add Integration** â†’ search **Sentinel**
6. Sentinel starts immediately with sensible defaults â€” no configuration required

</details>

<details>
<summary>Manual installation</summary>

Copy `custom_components/sentinel/` to your `<config>/custom_components/` directory and restart.

</details>

---

## Configuration

All options are available via **Settings â†’ Devices & Services â†’ Sentinel â†’ Configure**.
Sentinel works out of the box â€” configure only what you need to adjust.

| Option | Default | Description |
|---|---|---|
| Fire events on the HA bus | Yes | Fire `sentinel_item_changed` on every state change â€” required for automations |
| Grace period (seconds) | 30s | How long an integration must stay failed before being reported (0 = immediate) |
| Excluded integrations | None | Integrations to exclude from monitoring (dropdown, your install) |
| Ignored device sources | None | Device sources to ignore (dropdown, computed from your device registry) |
| Ignored devices | None | Specific devices to exclude from monitoring |
| Report stopped applications as warning | No | When enabled, stopped applications are reported as warnings |
| Application poll interval (seconds) | 60s | How often Sentinel queries the Supervisor (30â€“300s) |

### What gets monitored by default

**Integrations** â€” all user-configured integrations except:
- Internal helpers (`template`, `group`, `input_*`, `automation`, `script`â€¦)
- System domains (`homeassistant`, `hacs`, `sentinel`)
- User-disabled integrations (`disabled_by = user`)

**Devices** â€” entities in physical domains (`light`, `switch`, `lock`, `climate`, `cover`, `valve`â€¦) and vital device classes (`temperature`, `humidity`, `motion`, `smoke`, `door`, `window`, `co`, `co2`â€¦)

**Applications** â€” all installed applications on HA OS, queried directly from the Supervisor API

### Applications provider (HA OS only)

> The Applications provider is only active on HA OS / Supervised installations. On other installation types it is silently skipped.

**Application states:**

| State | Severity | Meaning |
|---|---|---|
| `started` | `ok` | Running normally |
| `stopped` | `ok` (or `warning` if option enabled) | Intentionally stopped |
| `error` | `error` | Failure on start/stop |
| `unknown` | `warning` | Unknown state |
| `startup` | ignored | Transient â€” application is starting up |

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
| `domain` | Integration domain, device source, or `hassio` for applications |
| `state` | Raw state (e.g. `setup_error`, `unavailable`, `error`) |
| `severity` | `ok`, `warning` or `error` |
| `reason` | Error message if available |
| `since` | ISO timestamp of last state change |
| `failure_count` | Number of times this item has failed |
| `can_reload` | Whether reload is supported (integrations + applications) |
| `device_url` | Direct link to the HA device page (devices only) |
| `slug` | Application slug (apps only) |

### Sensor

- `sensor.sentinel_problems` â€” total number of unhealthy items across all providers

---

## Events

When an item changes health state, Sentinel fires `sentinel_item_changed`:

```yaml
event_type: sentinel_item_changed
data:
  item_id: "abc123..."
  provider: "integrations"        # "integrations", "devices", or "apps" (applications)
  item_type: "integration"        # "integration", "device", or "addon" (application)
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

### Example automation: persistent notification (recommended)

Uses `sentinel_item_changed` events — no hardcoded entity IDs, works immediately.
For devices, a delay before notifying avoids spurious alerts for transient `unavailable` states.

```yaml
alias: Sentinel — Persistent notification
triggers:
  - trigger: event
    event_type: sentinel_item_changed
actions:
  - if:
      - condition: template
        value_template: >
          {{ trigger.event.data.healthy == false
             and trigger.event.data.severity != 'ok' }}
    then:
      - action: persistent_notification.create
        data:
          title: >
            {{ trigger.event.data.name }} ({{ trigger.event.data.domain }}) problem
          message: >
            **State:** {{ trigger.event.data.state | replace('_', ' ') }}
            {%- if trigger.event.data.reason %} — {{ trigger.event.data.reason }}{% endif %}
            {%- if trigger.event.data.failure_count | int > 1 %} ({{ trigger.event.data.failure_count }}x){% endif %}
          notification_id: "sentinel_{{ trigger.event.data.item_id }}"
    else:
      - action: persistent_notification.dismiss
        data:
          notification_id: "sentinel_{{ trigger.event.data.item_id }}"
mode: parallel
max: 10
```

---

## HA Labels

Sentinel automatically assigns HA labels to all its `binary_sensor` entities when they are created.

| Label | Entities |
|---|---|
| `sentinel` | All Sentinel binary_sensor entities |
| `sentinel_integration` | Integration health entities only |
| `sentinel_device` | Device health entities only |
| `sentinel_app` | Application health entities only |

Labels are useful for organizing entities in the HA UI, filtering in dashboards, and grouping in conditions:

```yaml
# In a condition — check if any device sensor is on
condition: template
value_template: >
  {{ label_entities('sentinel_device') | select('is_state', 'on') | list | count > 0 }}
```

> **Note:** `label_entities()` cannot be used in `entity_id` of a `state` trigger — HA does not support templates there. Use the `sentinel_item_changed` event trigger for per-item automation logic.

### Example automation: notify with delay using HA labels (recommended)

Sentinel automatically assigns [HA labels](#ha-labels) to all its entities. This allows using a native `for:` delay â€” no active waiting, no blocked thread.

```yaml
automation:
  alias: "Sentinel â€” Persistent notification"
  triggers:
    - trigger: state
      entity_id: label_entities('sentinel_device')
      to: "on"
      for:
        minutes: 1
      id: problem_device
    - trigger: state
      entity_id: label_entities('sentinel_integration')
      to: "on"
      id: problem_integration
    - trigger: state
      entity_id: label_entities('sentinel_app')
      to: "on"
      id: problem_app
    - trigger: state
      entity_id: label_entities('sentinel')
      to: "off"
      id: resolved
  actions:
    - if:
        - condition: trigger
          id:
            - problem_device
            - problem_integration
            - problem_app
      then:
        - action: persistent_notification.create
          data:
            title: "{{ trigger.to_state.attributes.friendly_name }} problem"
            message: >
              **State:** {{ trigger.to_state.attributes.state | replace('_', ' ') }}
              {%- if trigger.to_state.attributes.reason %} â€” {{ trigger.to_state.attributes.reason }}{% endif %}
              {%- if trigger.to_state.attributes.failure_count | int > 1 %} ({{ trigger.to_state.attributes.failure_count }}x){% endif %}
            notification_id: "{{ trigger.to_state.entity_id }}"
      else:
        - action: persistent_notification.dismiss
          data:
            notification_id: "{{ trigger.to_state.entity_id }}"
  mode: parallel
  max: 10
```

> **Note:** The `for: minutes: 1` delay on devices avoids spurious alerts for transient `unavailable` states (e.g. Z-Wave locks, cameras). Integrations trigger immediately â€” the grace period in Sentinel already handles startup noise.

### Example automation: notify with delay (event-based, without labels)

If you prefer to use the event bus instead of state triggers:

```yaml
automation:
  alias: "Sentinel â€” Alert on problem (with delay)"
  trigger:
    - platform: event
      event_type: sentinel_item_changed
  condition:
    - condition: template
      value_template: "{{ not trigger.event.data.healthy }}"
  action:
    - variables:
        item_sensor: >-
          binary_sensor.sentinel_{{ trigger.event.data.name | slugify }}_{{
          trigger.event.data.domain }}
    - delay: "00:01:00"
    - condition: template
      value_template: "{{ is_state(item_sensor, 'on') }}"
    - action: notify.mobile_app_your_phone
      data:
        title: "{{ trigger.event.data.name }} ({{ trigger.event.data.domain }}) â€” {{ trigger.event.data.item_type }} problem"
        message: >
          {{ trigger.event.data.state | replace('_', ' ') }}
          {%- if trigger.event.data.reason %} â€” {{ trigger.event.data.reason }}{% endif %}
  mode: parallel
```

---

## HA Labels

Sentinel automatically assigns HA labels to all its `binary_sensor` entities when they are created. Labels are created in the label registry if they don't exist yet.

| Label | Entities |
|---|---|
| `sentinel` | All Sentinel binary_sensor entities |
| `sentinel_integration` | Integration health entities only |
| `sentinel_device` | Device health entities only |
| `sentinel_app` | Application health entities only |

This enables clean automations using `label_entities()` with native `for:` delays â€” no active waiting, no hardcoded entity IDs.

```yaml
entity_id: label_entities('sentinel_device')   # all device sensors
entity_id: label_entities('sentinel')          # everything Sentinel monitors
```

---

## Actions

### `sentinel.reload_item`

Reload a broken integration or restart a crashed application (add-on).

```yaml
action: sentinel.reload_item
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

# Applications (add-ons) card (HA OS only)
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
| `unknown` | `warning` | Application in unknown state |

*`stopped` only reported as warning if `watch_stopped_addons` is enabled.

**`not_loaded` without `disabled_by` â€” integration is not intentionally disabled.

---

## License

MIT â€” Â© 2026 GuiPoM
