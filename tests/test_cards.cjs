/* Dependency-free regression tests for the bundled cards (no live HA needed). */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname,
  "../custom_components/sentinel/frontend/ha-sentinel.js"), "utf8");
const types = ["ha-sentinel-card", "ha-sentinel-devices-card", "ha-sentinel-apps-card"];
const providers = ["integrations", "devices", "apps"];

function environment(existing = new Map()) {
  const context = vm.createContext({
    HTMLElement: class { innerHTML = ""; },
    window: { customCards: [] },
    customElements: {
      get: (name) => existing.get(name),
      define: (name, constructor) => {
        assert.ok(!existing.has(name), `Duplicate custom element ${name}`);
        existing.set(name, constructor);
      },
    },
  });
  // Modules have separate lexical scopes even when loaded under two URLs.
  const load = () => vm.runInContext(`(() => { ${source}\n })()`, context);
  load();
  return { context, existing, load };
}

function state(provider, overrides = {}) {
  return {
    entity_id: "binary_sensor.renamed_by_user", state: "on",
    attributes: { provider, state: "setup_error", severity: "error",
      friendly_name: "Sentinel Demo (demo)", ...overrides },
  };
}

test("register all cards, previews and default configuration exactly once", () => {
  const { context, existing, load } = environment();
  assert.equal(existing.size, 3);
  for (const type of types) {
    assert.equal(existing.get(type).getStubConfig().max_items, 10);
  }
  load();
  assert.equal(existing.size, 3);
  assert.equal(context.window.customCards.length, 3);
});

test("coexist with custom elements from a standalone installation", () => {
  const previous = class {};
  const { existing } = environment(new Map([[types[0], previous]]));
  assert.equal(existing.get(types[0]), previous);
  assert.equal(existing.size, 3);
});

for (const [index, type] of types.entries()) {
  test(`${type}: provider filtering, privacy-safe states, reconnection and localization`, () => {
    const { existing } = environment();
    const card = new (existing.get(type))();
    card.setConfig({});
    assert.match(card.innerHTML, /Waiting for Home Assistant/);
    card.hass = { language: "fr-FR", states: {
      one: state(providers[index]), other: state("unrelated", { friendly_name: "DO NOT SHOW" }),
    } };
    assert.match(card.innerHTML, /Demo/);
    assert.doesNotMatch(card.innerHTML, /DO NOT SHOW|undefined|NaN/);
    card.innerHTML = "";
    card.connectedCallback();
    assert.match(card.innerHTML, /Demo/);
    assert.match(card.innerHTML, /Erreur de configuration/);
  });

  test(`${type}: escape all untrusted text`, () => {
    const { existing } = environment();
    const card = new (existing.get(type))();
    const payload = '<img src=x onerror="alert(1)">';
    card.setConfig({ title: payload });
    card.hass = { language: "en", states: { one: state(providers[index], {
      friendly_name: payload, reason: payload, slug: payload, source: payload,
      state: payload, device_url: '/config/devices/" onmouseover="alert(1)',
    }) } };
    assert.doesNotMatch(card.innerHTML, /<img|href="[^"]*" onmouseover=/);
    assert.match(card.innerHTML, /&lt;img/);
  });

  test(`${type}: show_ok, limits and full problem count`, () => {
    const { existing } = environment();
    const card = new (existing.get(type))();
    card.setConfig({ max_items: 1 });
    const first = state(providers[index], { friendly_name: "First" });
    const second = state(providers[index], { friendly_name: "Second" });
    const healthy = { ...state(providers[index], { friendly_name: "Healthy" }), state: "off" };
    card.hass = { language: "en", states: { first, second, healthy } };
    assert.match(card.innerHTML, /1 more out of 2/);
    assert.doesNotMatch(card.innerHTML, /Healthy/);
    card.setConfig({ show_ok: true, max_items: 0 });
    assert.match(card.innerHTML, /Healthy/);
    assert.doesNotMatch(card.innerHTML, /more out of/);
    assert.throws(() => card.setConfig({ max_items: -1 }), /max_items/);
  });
}

test("device links reject external URLs and preserve safe internal links", () => {
  const { existing } = environment();
  const card = new (existing.get(types[1]))();
  card.setConfig({});
  for (const url of ["javascript:alert(1)", "//evil.example", "/\\evil.example", "/\nevil"]) {
    card.hass = { states: { one: state("devices", { device_url: url }) } };
    assert.doesNotMatch(card.innerHTML, /href=/);
  }
  card.hass = { states: { one: state("devices", {
    device_url: "/config/devices/device/123", unavailable_entities: ["one", "two"],
  }) } };
  assert.match(card.innerHTML, /href="\/config\/devices\/device\/123"/);
  assert.match(card.innerHTML, /2 unavailable entities/);
});

test("device grouping keeps each source together and can be disabled", () => {
  const { existing } = environment();
  const card = new (existing.get(types[1]))();
  card.setConfig({ show_ok: true });
  card.hass = { states: {
    first: state("devices", { source: "hue", friendly_name: "Hue error" }),
    second: state("devices", { source: "zwave", friendly_name: "Zwave error" }),
    healthy: { ...state("devices", { source: "hue", friendly_name: "Hue healthy" }), state: "off" },
  } };
  assert.equal((card.innerHTML.match(/class="source-header">HUE/g) || []).length, 1);
  assert.ok(card.innerHTML.indexOf("Hue healthy") < card.innerHTML.indexOf("Zwave error"));
  card.setConfig({ show_ok: true, group_by_source: false });
  assert.doesNotMatch(card.innerHTML, /class="source-header"/);
  assert.ok(card.innerHTML.indexOf("Zwave error") < card.innerHTML.indexOf("Hue healthy"));
});
