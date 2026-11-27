/**
 * Sentinel Cards — bundled companion to the Sentinel integration.
 * Adapted from GuiPoM/lovelace-ha-sentinel, MIT license, copyright 2026 GuiPoM.
 * No external dependencies or requests; uses only Sentinel's published states.
 */
const PROVIDER_INTEGRATIONS = "integrations";
const PROVIDER_DEVICES = "devices";
const PROVIDER_APPS = "apps";

const LABELS = {
  en: {
    integrations_error: "Integrations with errors",
    devices_error: "Devices with errors",
    apps_error: "Applications with errors",
    no_error: "No errors detected.",
    waiting: "Waiting for Home Assistant…",
    ok: "OK",
    more_items: (hidden, total) => `+ ${hidden} more out of ${total}`,
    unavailable_count: (n) => `${n} unavailable entit${n === 1 ? "y" : "ies"}`,
    state_loaded: "Loaded", state_setup_error: "Setup error",
    state_migration_error: "Migration error", state_setup_retry: "Setup retry",
    state_not_loaded: "Not loaded", state_failed_unload: "Failed to unload",
    state_setup_in_progress: "Setup in progress", state_unload_in_progress: "Unload in progress",
    state_unavailable: "Unavailable", state_started: "Started",
    state_error: "Error", state_stopped: "Stopped", state_unknown: "Unknown",
    state_startup: "Starting up",
  },
  fr: {
    integrations_error: "Intégrations en erreur",
    devices_error: "Appareils en erreur",
    apps_error: "Applications en erreur",
    no_error: "Aucune erreur détectée.",
    waiting: "En attente de Home Assistant…",
    ok: "OK",
    more_items: (hidden, total) => `+ ${hidden} autre${hidden > 1 ? "s" : ""} sur ${total}`,
    unavailable_count: (n) => `${n} entité${n > 1 ? "s" : ""} indisponible${n > 1 ? "s" : ""}`,
    state_loaded: "Chargée", state_setup_error: "Erreur de configuration",
    state_migration_error: "Erreur de migration", state_setup_retry: "Nouvelle tentative",
    state_not_loaded: "Non chargée", state_failed_unload: "Échec du déchargement",
    state_setup_in_progress: "Configuration en cours", state_unload_in_progress: "Déchargement en cours",
    state_unavailable: "Indisponible", state_started: "Démarrée",
    state_error: "En erreur", state_stopped: "Arrêtée", state_unknown: "Inconnu",
    state_startup: "Démarrage",
  },
};

const COLOR = {
  error: "var(--error-color, #f44336)",
  warning: "var(--warning-color, #ff9800)",
  ok: "var(--success-color, #4caf50)",
  off: "var(--disabled-color, #bdbdbd)",
};
const ICON = { error: "mdi:alert-circle", warning: "mdi:alert", ok: "mdi:check-circle" };
const SHARED_CSS = `
  ha-card { overflow: hidden; }
  .card-header { display: flex; align-items: center; gap: 8px; padding: 12px 16px 8px;
    font-size: .875rem; font-weight: 500; color: var(--secondary-text-color);
    text-transform: uppercase; letter-spacing: .05em; }
  .card-header ha-icon { --mdc-icon-size: 18px; }
  .card-content { padding: 8px 0; }
  .row { display: flex; align-items: center; min-height: 48px; padding: 4px 16px;
    box-sizing: border-box; gap: 16px; }
  ha-icon { --mdc-icon-size: 24px; flex-shrink: 0; }
  .info { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .name { font-size: .9em; color: var(--primary-text-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .name a { color: inherit; text-decoration: none; }
  .name a:hover { text-decoration: underline; }
  .secondary { font-size: .78em; color: var(--secondary-text-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .value { font-size: .85em; font-weight: 500; flex-shrink: 0; }
  .divider { border-top: 1px solid var(--divider-color, rgba(0,0,0,.12)); }
  .source-header { padding: 4px 16px 2px; font-size: .7em; font-weight: 600;
    color: var(--secondary-text-color); text-transform: uppercase; }
  .footer { padding: 4px 16px 8px; font-size: .75em; color: var(--secondary-text-color); text-align: right; }
  .empty { padding: 8px 16px; color: var(--secondary-text-color); font-size: .9em; }
`;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function extractDisplayName(entity) {
  const fullName = String(entity.attributes.friendly_name || entity.entity_id)
    .replace(/^Sentinel\s+/i, "");
  return fullName.replace(/\s*\([^)]+\)\s*$/, "").trim() || fullName;
}

function sanitizeUrl(url) {
  // Reject protocol-relative URLs, backslashes and control characters too.
  if (typeof url !== "string" || !url.startsWith("/") || /^\/\//.test(url)
      || /[\\\x00-\x20]/.test(url)) return null;
  return url;
}

function localizeState(state, labels) {
  if (!state) return "";
  return labels[`state_${state}`] || String(state).replace(/_/g, " ")
    .replace(/^./, (character) => character.toUpperCase());
}

class SentinelBaseCard extends HTMLElement {
  set hass(hass) { this._hass = hass; this._render(); }

  setConfig(config) {
    if (config.max_items !== undefined
        && (!Number.isInteger(config.max_items) || config.max_items < 0)) {
      throw new Error("max_items must be a non-negative integer");
    }
    this._config = { ...config };
    this._render();
  }

  static getStubConfig() { return { show_ok: false, max_items: 10 }; }
  getCardSize() { return (this._config?.max_items || 10) + 2; }
  connectedCallback() { this._render(); }

  _renderRow(entity, labels) {
    const attributes = entity.attributes;
    const isProblem = entity.state === "on";
    const severity = isProblem ? (attributes.severity || "warning") : "ok";
    const color = isProblem ? (COLOR[severity] || COLOR.warning) : COLOR.off;
    const icon = isProblem ? (ICON[severity] || ICON.warning) : ICON.ok;
    const name = escapeHtml(extractDisplayName(entity));
    let subtitle = "";
    let nameHtml = name;
    if (this.constructor.provider === PROVIDER_INTEGRATIONS && isProblem) {
      subtitle = attributes.reason || attributes.domain || "";
    } else if (this.constructor.provider === PROVIDER_DEVICES) {
      const url = sanitizeUrl(attributes.device_url);
      if (url) nameHtml = `<a class="device-link" href="${escapeHtml(url)}">${name}</a>`;
      const count = Array.isArray(attributes.unavailable_entities)
        ? attributes.unavailable_entities.length : 0;
      if (isProblem && count > 0) subtitle = labels.unavailable_count(count);
    } else if (this.constructor.provider === PROVIDER_APPS) {
      subtitle = attributes.slug || "";
    }
    const state = isProblem ? localizeState(attributes.state, labels) : labels.ok;
    return `<div class="row">
      <ha-icon icon="${icon}" style="color:${color}"></ha-icon>
      <div class="info"><span class="name">${nameHtml}</span>
        ${subtitle ? `<span class="secondary">${escapeHtml(subtitle)}</span>` : ""}</div>
      <span class="value" style="color:${isProblem ? color : "var(--secondary-text-color)"}">${escapeHtml(state)}</span>
    </div>`;
  }

  _render() {
    if (!this._config) return;
    const labels = LABELS[this._hass?.language?.split("-")[0]] || LABELS.en;
    const provider = this.constructor.provider;
    const showOk = this._config.show_ok === true;
    const maxItems = this._config.max_items ?? 10;
    const title = this._config.title ?? null;
    const allEntities = Object.values(this._hass?.states || {}).filter(
      (entity) => entity.attributes.provider === provider
    );
    const problemCount = allEntities.filter((entity) => entity.state === "on").length;
    let entities = allEntities.filter((entity) => showOk || entity.state === "on");
    const groupBySource = provider === PROVIDER_DEVICES && this._config.group_by_source !== false;
    const rank = (entity) => entity.state === "on"
      ? ({ error: 0, warning: 1, ok: 2 }[entity.attributes.severity] ?? 1) : 2;
    entities.sort((left, right) => {
      if (groupBySource) {
        const sourceOrder = String(left.attributes.source || "DEVICE").toUpperCase()
          .localeCompare(String(right.attributes.source || "DEVICE").toUpperCase());
        if (sourceOrder) return sourceOrder;
      }
      return rank(left) - rank(right) || extractDisplayName(left).localeCompare(extractDisplayName(right));
    });
    const total = entities.length;
    if (maxItems > 0) entities = entities.slice(0, maxItems);
    const hidden = total - entities.length;
    let rows = "";
    let currentSource = null;
    for (const entity of entities) {
      if (groupBySource) {
        const source = String(entity.attributes.source || "DEVICE").toUpperCase();
        if (source !== currentSource) {
          rows += `<div class="source-header">${escapeHtml(source)}</div>`;
          currentSource = source;
        }
      }
      rows += this._renderRow(entity, labels);
    }
    const summaryIcon = provider === PROVIDER_DEVICES
      ? (problemCount ? "mdi:devices" : "mdi:check-network")
      : (problemCount ? "mdi:puzzle-remove" : "mdi:puzzle-check");
    const summaryColor = problemCount ? COLOR.error : COLOR.ok;
    this.innerHTML = `<ha-card>
      ${title !== null ? `<div class="card-header"><ha-icon icon="${this.constructor.headerIcon}"></ha-icon><span>${escapeHtml(title)}</span></div>` : ""}
      <div class="card-content"><div class="row">
        <ha-icon icon="${summaryIcon}" style="color:${summaryColor}"></ha-icon>
        <div class="info"><span class="name">${labels[this.constructor.summaryLabel]}</span></div>
        <span class="value" style="color:${summaryColor}">${problemCount}</span>
      </div><div class="divider"></div>
      ${rows || `<div class="empty">${this._hass ? labels.no_error : labels.waiting}</div>`}</div>
      ${hidden ? `<div class="footer">${labels.more_items(hidden, total)}</div>` : ""}
    </ha-card><style>${SHARED_CSS}</style>`;
  }
}

class HaSentinelCard extends SentinelBaseCard {
  static provider = PROVIDER_INTEGRATIONS;
  static summaryLabel = "integrations_error";
  static headerIcon = "mdi:shield-check";
}
class HaSentinelDevicesCard extends SentinelBaseCard {
  static provider = PROVIDER_DEVICES;
  static summaryLabel = "devices_error";
  static headerIcon = "mdi:devices";
}
class HaSentinelAppsCard extends SentinelBaseCard {
  static provider = PROVIDER_APPS;
  static summaryLabel = "apps_error";
  static headerIcon = "mdi:puzzle";
}

window.customCards = window.customCards || [];
for (const [type, constructor, name] of [
  ["ha-sentinel-card", HaSentinelCard, "Sentinel Card"],
  ["ha-sentinel-devices-card", HaSentinelDevicesCard, "Sentinel Devices Card"],
  ["ha-sentinel-apps-card", HaSentinelAppsCard, "Sentinel Apps Card"],
]) {
  if (!customElements.get(type)) customElements.define(type, constructor);
  if (!window.customCards.some((card) => card.type === type)) {
    window.customCards.push({
      type, name, preview: true,
      description: "Health status monitored by the Sentinel integration.",
      documentationURL: "https://github.com/GuiPoM/ha-sentinel#dashboard-cards",
    });
  }
}
