/**
 * HA Sentinel Card
 * A Lovelace card showing the health status of all monitored integrations.
 *
 * Usage:
 *   type: custom:ha-sentinel-card
 *   title: "Integration Status"        # optional
 *   show_ok: true                      # show healthy items (default: true)
 *   filter_provider: "integrations"    # optional: filter by provider
 */

const CARD_VERSION = "0.1.0";

const STATE_COLORS = {
  ok: "var(--success-color, #4CAF50)",
  problem: "var(--error-color, #f44336)",
  retry: "var(--warning-color, #FF9800)",
  unknown: "var(--disabled-color, #9E9E9E)",
};

const STATE_ICONS = {
  loaded: "mdi:check-circle",
  setup_error: "mdi:alert-circle",
  setup_retry: "mdi:refresh-circle",
  migration_error: "mdi:alert",
  failed_unload: "mdi:close-circle",
  not_loaded: "mdi:minus-circle",
  setup_in_progress: "mdi:progress-clock",
  unload_in_progress: "mdi:progress-clock",
};

function getStateColor(state) {
  if (state === "loaded") return STATE_COLORS.ok;
  if (state === "setup_retry") return STATE_COLORS.retry;
  if (["setup_error", "migration_error", "failed_unload"].includes(state))
    return STATE_COLORS.problem;
  return STATE_COLORS.unknown;
}

function formatSince(isoString) {
  if (!isoString) return "";
  const d = new Date(isoString);
  const now = new Date();
  const diffMs = now - d;
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${Math.floor(diffHours / 24)}d ago`;
}

class HaSentinelCard extends HTMLElement {
  static get properties() {
    return { hass: {}, config: {} };
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  setConfig(config) {
    this._config = config;
  }

  getCardSize() {
    return 4;
  }

  getGridOptions() {
    return { rows: 4, columns: 12, min_rows: 2 };
  }

  _getSentinelEntities() {
    if (!this._hass) return [];
    const entities = Object.values(this._hass.states).filter(
      (s) =>
        s.entity_id.startsWith("binary_sensor.ha_sentinel_") &&
        s.attributes.provider !== undefined
    );
    return entities;
  }

  _render() {
    if (!this._hass || !this._config) return;

    const title = this._config.title || "HA Sentinel";
    const showOk = this._config.show_ok !== false;
    const filterProvider = this._config.filter_provider || null;

    let entities = this._getSentinelEntities();

    if (filterProvider) {
      entities = entities.filter(
        (e) => e.attributes.provider === filterProvider
      );
    }

    if (!showOk) {
      entities = entities.filter((e) => e.state === "on");
    }

    // Sort: problems first, then by name
    entities.sort((a, b) => {
      if (a.state === "on" && b.state !== "on") return -1;
      if (a.state !== "on" && b.state === "on") return 1;
      return (a.attributes.friendly_name || a.entity_id).localeCompare(
        b.attributes.friendly_name || b.entity_id
      );
    });

    const problemCount = entities.filter((e) => e.state === "on").length;
    const totalCount = entities.length;

    const rows = entities
      .map((entity) => {
        const isProblem = entity.state === "on";
        const state = entity.attributes.state || "unknown";
        const color = getStateColor(state);
        const since = formatSince(entity.attributes.since);
        const reason = entity.attributes.reason || "";
        const failCount = entity.attributes.failure_count || 0;
        const canReload = entity.attributes.can_reload === true;
        const domain = entity.attributes.domain || "";
        const name =
          entity.attributes.friendly_name ||
          entity.entity_id.replace("binary_sensor.ha_sentinel_", "");

        return `
          <div class="sentinel-row ${isProblem ? "problem" : "ok"}">
            <div class="sentinel-indicator" style="background:${color}"></div>
            <div class="sentinel-info">
              <div class="sentinel-name">${name}</div>
              <div class="sentinel-meta">
                <span class="sentinel-domain">${domain}</span>
                <span class="sentinel-state" style="color:${color}">${state.replace(/_/g, " ")}</span>
                ${since ? `<span class="sentinel-since">${since}</span>` : ""}
                ${failCount > 0 ? `<span class="sentinel-failures" title="Total failures">${failCount}x</span>` : ""}
              </div>
              ${reason ? `<div class="sentinel-reason">${reason}</div>` : ""}
            </div>
            ${
              canReload && isProblem
                ? `<button class="sentinel-reload" data-entry-id="${entity.attributes.entry_id}" title="Reload integration">
                    &#x21BB;
                  </button>`
                : '<div class="sentinel-reload-placeholder"></div>'
            }
          </div>
        `;
      })
      .join("");

    const headerColor =
      problemCount > 0 ? STATE_COLORS.problem : STATE_COLORS.ok;

    this.innerHTML = `
      <ha-card>
        <div class="sentinel-card">
          <div class="sentinel-header">
            <span class="sentinel-title">${title}</span>
            <span class="sentinel-badge" style="background:${headerColor}">
              ${problemCount > 0 ? `${problemCount} problem${problemCount > 1 ? "s" : ""}` : "All OK"}
            </span>
          </div>
          <div class="sentinel-subtitle">${totalCount} monitored</div>
          <div class="sentinel-list">
            ${rows.length > 0 ? rows : '<div class="sentinel-empty">No integrations to display.</div>'}
          </div>
        </div>
      </ha-card>
      <style>
        .sentinel-card { padding: 16px; }
        .sentinel-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 4px;
        }
        .sentinel-title { font-size: 1.1em; font-weight: 600; }
        .sentinel-badge {
          padding: 2px 10px;
          border-radius: 12px;
          color: white;
          font-size: 0.8em;
          font-weight: 600;
        }
        .sentinel-subtitle {
          font-size: 0.8em;
          color: var(--secondary-text-color);
          margin-bottom: 12px;
        }
        .sentinel-row {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 8px 4px;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
        }
        .sentinel-row:last-child { border-bottom: none; }
        .sentinel-indicator {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          flex-shrink: 0;
        }
        .sentinel-info { flex: 1; min-width: 0; }
        .sentinel-name {
          font-weight: 500;
          font-size: 0.95em;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .sentinel-meta {
          display: flex;
          gap: 8px;
          font-size: 0.78em;
          color: var(--secondary-text-color);
          flex-wrap: wrap;
          margin-top: 2px;
        }
        .sentinel-domain { font-style: italic; }
        .sentinel-state { font-weight: 500; }
        .sentinel-since { opacity: 0.8; }
        .sentinel-failures {
          background: var(--warning-color, #FF9800);
          color: white;
          padding: 0 5px;
          border-radius: 8px;
          font-size: 0.9em;
        }
        .sentinel-reason {
          font-size: 0.78em;
          color: var(--error-color, #f44336);
          margin-top: 2px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .sentinel-reload {
          background: none;
          border: 1px solid var(--primary-color);
          border-radius: 50%;
          width: 28px;
          height: 28px;
          cursor: pointer;
          color: var(--primary-color);
          font-size: 1em;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }
        .sentinel-reload:hover { background: var(--primary-color); color: white; }
        .sentinel-reload-placeholder { width: 28px; flex-shrink: 0; }
        .sentinel-empty {
          color: var(--secondary-text-color);
          font-size: 0.9em;
          padding: 8px 0;
        }
      </style>
    `;

    // Attach reload button handlers
    this.querySelectorAll(".sentinel-reload").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const entryId = btn.dataset.entryId;
        if (entryId && this._hass) {
          this._hass.callService("ha_sentinel", "reload", { item_id: entryId });
        }
      });
    });
  }

  connectedCallback() {
    this._render();
  }
}

customElements.define("ha-sentinel-card", HaSentinelCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "ha-sentinel-card",
  name: "HA Sentinel Card",
  description: "Shows the health status of your Home Assistant integrations.",
  preview: false,
  documentationURL: "https://github.com/GuiPoM/ha-sentinel",
});

console.info(
  `%c HA-SENTINEL-CARD %c v${CARD_VERSION} `,
  "color: white; background: #e91e63; font-weight: 700;",
  "color: #e91e63; background: white; font-weight: 700;"
);
