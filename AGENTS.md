# Sentinel — Agent Instructions

## Project Overview

**Sentinel** is a Home Assistant custom integration that monitors the health of integrations and physical devices in real time. It fires events and creates binary_sensor entities when something breaks.

- **Repo:** `GuiPoM/ha-sentinel` on `github.com`
- **Domain:** `sentinel`
- **Component path:** `custom_components/sentinel/`
- **Identity:** always use `GuiPoM` / `11942518+GuiPoM@users.noreply.github.com`

---

## Architecture

```
custom_components/sentinel/
├── __init__.py          # Setup, services (reload, reset_failure_count, check, purge)
├── binary_sensor.py     # One binary_sensor per monitored item
├── sensor.py            # sensor.sentinel_problems — total problem count
├── coordinator.py       # Orchestrates all providers, fires bus events
├── config_flow.py       # Config + Options flow
├── const.py             # All constants, DOMAIN, PHYSICAL_DOMAINS, VITAL_DEVICE_CLASSES, PERIODIC_DEVICE_CLASSES
├── manifest.json        # domain: sentinel, keys must be sorted: domain, name, then alphabetical
└── providers/
    ├── __init__.py      # HealthItem dataclass, HealthProvider base class
    ├── integrations.py  # IntegrationsProvider — monitors config entries
    ├── devices.py       # DevicesProvider — monitors physical devices
    └── apps.py          # Stub — future add-ons monitoring
```

---

## Key Concepts

### Providers
Each provider implements `HealthProvider` and produces `HealthItem` objects:
- `PROVIDER_INTEGRATIONS = "integrations"` — watches HA config entries
- `PROVIDER_DEVICES = "devices"` — watches physical device entities

### HealthItem
```python
id: str           # config_entry_id or device_id
name: str         # display name
provider: str     # "integrations" or "devices"
healthy: bool
state: str        # "loaded", "setup_error", "unavailable", "silent", "ok"...
severity: str     # "ok", "warning", "error"
reason: str|None
since: datetime
failure_count: int
can_reload: bool
extra: dict       # provider-specific: domain, source, device_url, unavailable_entities...
```

### Event
Every health change fires `sentinel_item_changed` on the HA event bus with fields:
`item_id`, `provider`, `item_type`, `name`, `domain`, `source`, `healthy`, `state`, `severity`, `reason`, `failure_count`, `since`

### Entity naming
- `_attr_has_entity_name = True`
- `_attr_name = f"{item.name} ({domain})"` or `item.name`
- Device parent: `name="Sentinel"` → entity_ids: `binary_sensor.sentinel_*`
- `unique_id = f"{DOMAIN}_{item.id}"`

---

## Devices Provider — Key Rules

### Eligible entities
- Domain in `PHYSICAL_DOMAINS` (light, switch, lock, climate, cover, valve, fan, humidifier, water_heater, lawn_mower)
- OR `sensor`/`binary_sensor` with `device_class` in `VITAL_DEVICE_CLASSES`
- Must have `device_id`, no `entity_category`, not `disabled_by`

### Silence detection
- **Removed in v0.5.2** — silence detection generated false positives on event-based sensors
- A device is unhealthy **only** when at least one entity is `unavailable`
- `unavailable` is the reliable signal from hubs (Hue, Z-Wave JS, Matter...) that a device is unreachable

### Noise suppression
If an integration is already in error, its devices are suppressed (coordinator checks `IntegrationsProvider` for the device's `config_entries`)

### Startup recheck
On `EVENT_HOMEASSISTANT_STARTED`, all devices are re-evaluated to clear transient unavailable states from boot. If HA is already running (reload), recheck fires immediately.

---

## Services

| Service | Parameters | Description |
|---|---|---|
| `sentinel.reload` | `item_id` | Reload a broken integration |
| `sentinel.reset_failure_count` | `item_id` | Reset failure counter |
| `sentinel.check` | — | Re-fire events for all unhealthy items |
| `sentinel.purge` | — | Remove all Sentinel entities from registry (platform == DOMAIN) |

---

## manifest.json Rules

Keys must be sorted: `domain`, `name`, then alphabetical order — required by Hassfest.

```json
{
  "domain": "sentinel",
  "name": "Sentinel",
  "codeowners": [...],
  "config_flow": true,
  "dependencies": [...],
  "documentation": "...",
  ...
  "version": "x.y.z"
}
```

---

## Version & Release

- Bump `manifest.json` version for every release
- Release tags on `github.com` — no push without explicit user approval
- CI: HACS Action + Hassfest run on every push

---

## Coding Rules

- No French in code (comments, variable names, log messages) — English only
- No magic strings for domain/provider — use `DOMAIN`, `PROVIDER_*` constants
- All constants in `const.py` using HA enums (`Platform`, `SensorDeviceClass`, `BinarySensorDeviceClass`)
- Use `dt_util.utcnow()` for timezone-aware datetimes, never `datetime.now()`
- Follow HA async patterns: `@callback` for sync callbacks, `async def` for coroutines

---

## Open Issues (Roadmap)

| # | Feature |
|---|---|
| [#2](https://github.com/GuiPoM/ha-sentinel/issues/2) | Internationalisation (i18n) |
| [#3](https://github.com/GuiPoM/ha-sentinel/issues/3) | Provider Apps (Supervisor add-ons) |
| [#4](https://github.com/GuiPoM/ha-sentinel/issues/4) | Provider Batteries |
| [#5](https://github.com/GuiPoM/ha-sentinel/issues/5) | Provider Network (ping) |
| [#6](https://github.com/GuiPoM/ha-sentinel/issues/6) | Auto-generated health dashboard |
