# HA Sentinel

**Proactive health monitoring for Home Assistant integrations (and apps in v2).**

HA Sentinel watches your Home Assistant config entries (integrations) in real time and alerts you the moment one goes down — before you notice the lights aren't responding or the lawn mower stopped reporting.

---

## Features

- **Real-time monitoring** — listens to HA's internal dispatcher signal, no polling
- **One entity per integration** — `binary_sensor` with `device_class: problem` (on = problem, off = OK)
- **Global counter** — `sensor.ha_sentinel_problems` showing total unhealthy count
- **Grace period** — configurable delay before flagging a problem (avoids false positives on startup)
- **Failure history** — `failure_count` attribute tracks how many times each integration has broken
- **Bus events** — fires `ha_sentinel_item_changed` for use in your automations
- **Reload action** — `ha_sentinel.reload` to restart a broken integration from an automation or dashboard
- **Lovelace card** — visual dashboard with color-coded status, inline reload buttons
- **Extensible** — provider architecture ready for Apps (add-ons) monitoring in v2

---

## Installation

### Via HACS (recommended)

1. In HACS, go to **Integrations** → **Custom repositories**
2. Add `https://github.com/GuiPoM/ha-sentinel` as an **Integration**
3. Search for "HA Sentinel" and install
4. Restart Home Assistant
5. Go to **Settings → Devices & Services → Add Integration** and search for "HA Sentinel"

### Manual

Copy `custom_components/ha_sentinel/` to your `<config>/custom_components/` directory and restart.

---

## Configuration

After adding the integration via the UI, you can configure:

| Option | Default | Description |
|---|---|---|
| Grace period | 30s | How long an integration must stay in a failed state before being reported |
| Fire events | Yes | Fire `ha_sentinel_item_changed` on the HA event bus |
| Excluded integrations | None | Integrations to exclude from monitoring |

---

## Entities

### Binary Sensors

One `binary_sensor` per monitored integration:

- **State**: `on` = problem detected, `off` = healthy
- **Entity ID**: `binary_sensor.ha_sentinel_<integration_name>`

**Attributes:**

| Attribute | Description |
|---|---|
| `provider` | `integrations` (v1) |
| `domain` | Integration domain (e.g. `netatmo`) |
| `state` | Raw HA config entry state |
| `reason` | Error message if available |
| `since` | ISO timestamp of last state change |
| `failure_count` | Number of times this integration has broken |
| `can_reload` | Whether reload is supported |

### Sensor

- `sensor.ha_sentinel_problems` — total number of unhealthy integrations
  - Attribute `problems`: list of currently unhealthy items with details

---

## Services

### `ha_sentinel.reload`

Reload a broken integration.

```yaml
service: ha_sentinel.reload
data:
  item_id: "<config_entry_id>"
```

### `ha_sentinel.reset_failure_count`

Reset the failure counter for an integration.

```yaml
service: ha_sentinel.reset_failure_count
data:
  item_id: "<config_entry_id>"
```

---

## Events

When an integration changes health state, HA Sentinel fires:

```yaml
event_type: ha_sentinel_item_changed
data:
  item_id: "abc123def456..."
  provider: "integrations"
  name: "Netatmo"
  healthy: false
  state: "setup_error"
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
        event_type: ha_sentinel_item_changed
    condition:
      - condition: template
        value_template: "{{ not trigger.event.data.healthy }}"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "Integration problem"
          message: >
            {{ trigger.event.data.name }} is {{ trigger.event.data.state }}
            {% if trigger.event.data.reason %}({{ trigger.event.data.reason }}){% endif %}
```

---

## Lovelace Card

Install the card resource from `lovelace/ha-sentinel-card.js` (add as `/local/ha-sentinel-card.js`).

```yaml
type: custom:ha-sentinel-card
title: "Integration Status"   # optional
show_ok: true                  # show healthy integrations (default: true)
filter_provider: integrations  # optional: filter by provider
```

---

## Roadmap

- **v0.1** — Integration monitoring (config entries)
- **v0.2** — Apps (add-ons) monitoring via Supervisor API
- **v0.3** — Notification blueprints, HACS default repository submission

---

## License

MIT — © 2026 GuiPoM
