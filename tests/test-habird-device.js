// Card bound to a BirdNET-Go Audubon Clock integration device
// (audubon_clock_device): the analog dial's rim assignment must come from
// that device's sensor.*_position_N entities (via hass.entities/hass.states)
// instead of computing one locally from BirdNET-Go data - and it must
// ignore position-shaped entities that belong to a DIFFERENT device.
const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const fs = require('fs');
const { JSDOM } = require('jsdom');
const CARD = fs.readFileSync(ROOT + '/dist/habird-card.js', 'utf8');

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'http://ha.local:8123/lovelace/birds', runScripts: 'outside-only', pretendToBeVisual: true,
});
const { window } = dom;
const errors = [];
window.addEventListener('error', e => errors.push((e.error && e.error.stack) || e.message));

// BirdNET-Go has its own, DIFFERENT species - if the device binding didn't
// take over, these (not the device's birds) would end up on the dial.
const summary = [
  { scientific_name: 'Calypte anna', common_name: "Anna's Hummingbird", count: 500,
    first_heard: '2026-01-02 08:00:00', last_heard: '2026-06-10 13:55:00', max_confidence: 0.99 },
];
window.fetch = (url) => {
  const p = String(url).replace('http://ha.local:8080', '');
  const ok = (b) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(JSON.parse(JSON.stringify(b))) });
  if (p.startsWith('/api/v2/analytics/species/summary')) return ok(summary);
  if (p.startsWith('/api/v2/analytics/species/daily')) return ok(summary.map(s => ({ ...s, hourly_counts: Array(24).fill(1) })));
  if (p.includes('/analytics/')) return ok({ data: [] });
  if (p.includes('/detections')) return ok({ data: [] });
  return Promise.resolve({ ok: false, status: 404, json: () => Promise.reject(404) });
};
window.Audio = class { addEventListener(){} load(){} play(){return Promise.resolve();} pause(){} };
Object.defineProperty(window.HTMLElement.prototype, 'clientWidth', { get() { return this.id === 'collage' ? 1200 : 300; } });
Object.defineProperty(window.HTMLElement.prototype, 'clientHeight', { get() { return this.id === 'collage' ? 800 : 100; } });
window.HTMLCanvasElement.prototype.getContext = () => null;
window.ResizeObserver = class { observe(){} disconnect(){} };

window.eval(CARD);

const hass = {
  themes: { darkMode: false },
  // Entity registry display entries - device_id is what the card filters on.
  entities: {
    'sensor.audubon_clock_position_6': { device_id: 'device-1' },
    'sensor.audubon_clock_position_7': { device_id: 'device-1' },
    // Same naming shape, but a DIFFERENT device - must be ignored.
    'sensor.other_clock_position_8': { device_id: 'device-2' },
  },
  states: {
    'sensor.audubon_clock_position_6': {
      state: 'American Robin',
      attributes: { scientific_name: 'Turdus migratorius', source: 'history', dim: false },
    },
    'sensor.audubon_clock_position_7': {
      state: 'Barred Owl',
      attributes: { scientific_name: 'Strix varia', source: 'history', dim: false },
    },
    'sensor.other_clock_position_8': {
      state: 'Some Other Bird',
      attributes: { scientific_name: 'Junco hyemalis', source: 'history', dim: false },
    },
  },
};

const card = window.document.createElement('habird-card');
card.setConfig({
  clock: true, clock_style: 'analog', clock_birds: true,
  audubon_clock_device: 'device-1',
  // Chime configured too, to exercise the config path alongside binding -
  // suppressing the card's own chime cast when a device is bound is a
  // simple, directly-readable gate (see apt.js's clockChime check), not
  // separately exercised here since it only fires on a real hour boundary.
  clock_chime: true, clock_chime_media_player: 'media_player.kitchen',
});
card.hass = hass;
window.document.body.appendChild(card);

setTimeout(() => {
  const assert = require('assert');
  try {
    const root = card.shadowRoot;
    const birds = [...root.getElementById('wwDialBirds').querySelectorAll('img.ww-dial-bird')];
    const scis = birds.map(b => b.getAttribute('data-sci'));
    assert.strictEqual(birds.length, 2, 'exactly the bound device\'s 2 position entities rendered: ' + scis);
    assert.ok(scis.includes('Turdus migratorius'), 'position 6 bird (robin) from the device');
    assert.ok(scis.includes('Strix varia'), 'position 7 bird (owl) from the device');
    // The OTHER device's entity, and BirdNET-Go's own species, must not
    // leak onto the dial - proves the device binding fully replaced local
    // computation rather than merging with it.
    assert.ok(!scis.includes('Junco hyemalis'), 'other device\'s entity excluded');
    assert.ok(!scis.includes('Calypte anna'), 'local BirdNET-Go computation bypassed');
    assert.deepStrictEqual(errors, [], 'uncaught errors: ' + errors.join('; '));
    console.log('HABIRD DEVICE BINDING TEST PASSED:', birds.length, 'rim birds from the bound device');
    process.exit(0);
  } catch (e) {
    console.error('FAIL:', e.message);
    process.exit(1);
  }
}, 1600);
