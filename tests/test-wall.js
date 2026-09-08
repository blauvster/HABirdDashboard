// Wall mode v2: widgets live in a collage corner and act as a packing
// obstacle. Load with ?wall, stub a BIG widget box covering the right
// half of the collage, and assert no bird tile lands on it. Also check
// the HA-token weather path (Bearer header, entity auto-discovery,
// sun.sun) and the BirdNET-Go fallback.
const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const fs = require('fs');
const { JSDOM } = require('jsdom');
const WWW = ROOT + '/homeassistant/www';
const html = fs.readFileSync(WWW + '/index.html', 'utf8');

function boot({ search, config, onFetch }) {
  const dom = new JSDOM(html, { url: 'http://ha.local:8123/local/habird/index.html' + search, runScripts: 'outside-only', pretendToBeVisual: true });
  const { window } = dom;
  const errors = [];
  window.addEventListener('error', e => errors.push(e.error && e.error.stack || e.message));
  window.fetch = onFetch(window);
  window.Audio = class { addEventListener(){} load(){} play(){return Promise.resolve();} pause(){} };
  Object.defineProperty(window.HTMLElement.prototype, 'clientWidth', { get() { return this.id === 'collage' ? 1200 : 300; } });
  Object.defineProperty(window.HTMLElement.prototype, 'clientHeight', { get() { return this.id === 'collage' ? 800 : 100; } });
  window.HTMLCanvasElement.prototype.getContext = () => null;
  window.eval(`window.AV_CONFIG = ${JSON.stringify(config)};`);
  window.eval(fs.readFileSync(WWW + '/masks.js', 'utf8'));
  window.eval(fs.readFileSync(WWW + '/apt.js', 'utf8'));
  // jsdom has no layout: stub rects AFTER boot so the wall block can measure.
  const collage = window.document.getElementById('collage');
  collage.getBoundingClientRect = () => ({ left: 0, top: 0, right: 1200, bottom: 800, width: 1200, height: 800 });
  const wrap = window.document.getElementById('wallWidgets');
  // Obstacle: the entire right half of the collage.
  wrap.getBoundingClientRect = () => wrap.hidden
    ? { left: 0, top: 0, width: 0, height: 0 }
    : { left: 600, top: 0, right: 1200, bottom: 800, width: 600, height: 800 };
  return { window, errors };
}

const summary = [
  { scientific_name: 'Calypte anna', common_name: "Anna's Hummingbird", count: 500, first_heard: '2026-01-02 08:00:00', last_heard: '2026-06-10 13:55:00', max_confidence: 0.99 },
  { scientific_name: 'Corvus corax', common_name: 'Common Raven', count: 9, first_heard: '2026-06-01 09:00:00', last_heard: '2026-06-10 08:20:00', max_confidence: 0.71 },
];
const daily = summary.map(s => ({ ...s, hourly_counts: Array(24).fill(1), latest_heard: '13:55:00' }));
const ok = (b) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(JSON.parse(JSON.stringify(b))) });
const nf = () => Promise.resolve({ ok: false, status: 404, json: () => Promise.reject(404) });

function bgData(p) {
  if (p === '/api/v2/analytics/species/summary') return ok(summary);
  if (p.startsWith('/api/v2/analytics/species/daily')) return ok(daily);
  if (p.includes('/analytics/')) return ok({ data: [] });
  if (p.includes('/detections')) return ok({ data: [] });
  return null;
}

const assert = require('assert');
let done = 0;

// --- Scenario A: ?wall + BirdNET-Go weather + obstacle avoidance ---
{
  const { window, errors } = boot({
    search: '?wall&corner=top-right',
    config: { birdnetGoUrl: '', sitConfidence: 0.96, wall: {} },
    onFetch: () => (url) => {
      const p = String(url).replace('http://ha.local:8080', '');
      if (p === '/api/v2/weather/latest') return ok({
        daily: { sunrise: '2026-06-10T05:42:00Z', sunset: '2026-06-10T20:31:00Z' },
        hourly: { temperature: 18.4, weather_desc: 'Partly cloudy' },
      });
      return bgData(p) || nf();
    },
  });
  setTimeout(() => {
    const doc = window.document;
    try {
      assert.strictEqual(doc.getElementById('wallWidgets').getAttribute('data-corner'), 'top-right', 'corner from URL');
      assert.strictEqual(doc.getElementById('wwTemp').textContent, '18°', 'BG temp');
      // Every placed bird must sit entirely left of x=600 (obstacle = right half,
      // less the 12px breathing margin the collage adds).
      const tiles = [...doc.querySelectorAll('.gtile')];
      assert.ok(tiles.length === 2, 'tiles rendered: ' + tiles.length);
      for (const t of tiles) {
        const x = parseFloat(t.style.left), w = parseFloat(t.style.width);
        assert.ok(x + w < 600, `bird overlaps obstacle: left=${x} w=${w}`);
      }
      assert.deepStrictEqual(errors, [], 'errors: ' + errors.join('; '));
      console.log('A: obstacle packing + BG weather OK (tiles all left of the clock zone)');
      if (++done === 6) { console.log('\nWALL V2 TESTS PASSED'); process.exit(0); }
    } catch (e) { console.error('A FAIL:', e.message); process.exit(1); }
  }, 1600);
}

// --- Scenario B: HA-token weather (auto-discovered entity + sun.sun + Bearer) ---
{
  let sawBearer = false;
  const { window, errors } = boot({
    search: '',
    config: { birdnetGoUrl: '', sitConfidence: 0.96,
      wall: { clock: true, weather: true, haToken: 'TESTTOKEN' } },
    onFetch: () => (url, opts) => {
      const u = String(url);
      const p = u.replace('http://ha.local:8080', '');
      if (u.startsWith('/api/') || u.includes('ha.local:8123/api/')) {
        if ((opts && opts.headers && opts.headers.Authorization) === 'Bearer TESTTOKEN') sawBearer = true;
        const ap = u.slice(u.indexOf('/api/') + 4);
        if (ap === '/states') return ok([
          { entity_id: 'sensor.x', state: '1' },
          { entity_id: 'weather.forecast_home', state: 'partlycloudy' },
        ]);
        if (ap === '/states/weather.forecast_home') return ok({
          state: 'partlycloudy',
          attributes: { temperature: 64.2, temperature_unit: '°F' },
        });
        if (ap === '/states/sun.sun') return ok({
          attributes: { next_rising: '2026-06-11T05:42:00Z', next_setting: '2026-06-10T20:31:00Z' },
        });
        return nf();
      }
      return bgData(p) || nf();
    },
  });
  setTimeout(() => {
    const doc = window.document;
    try {
      assert.ok(sawBearer, 'sent Bearer token to HA');
      assert.strictEqual(doc.getElementById('wwTemp').textContent, '64°', 'HA temp as-is (HA units): ' + doc.getElementById('wwTemp').textContent);
      assert.strictEqual(doc.getElementById('wwCond').textContent, 'partly cloudy', 'HA condition prettified');
      assert.ok(doc.getElementById('wwSun').textContent.startsWith('sun '), 'sun.sun rendered');
      assert.ok(/\d/.test(doc.getElementById('wwTime').textContent), 'clock rendered');
      assert.strictEqual(doc.getElementById('wallWidgets').getAttribute('data-corner'), 'bottom-right', 'default corner');
      assert.deepStrictEqual(errors, [], 'errors: ' + errors.join('; '));
      console.log('B: HA weather via token OK (auto-discovery, units, sun.sun)');
      if (++done === 6) { console.log('\nWALL V2 TESTS PASSED'); process.exit(0); }
    } catch (e) { console.error('B FAIL:', e.message); process.exit(1); }
  }, 1600);
}

// --- Scenario C: daily forecast (forecastDays + weather.get_forecasts) ---
{
  let sawForecastCall = false;
  const fc = [
    { datetime: '2026-06-11T00:00:00', condition: 'sunny', temperature: 24.1, templow: 12.6, precipitation: 0, precipitation_probability: 5 },
    { datetime: '2026-06-12T00:00:00', condition: 'rainy', temperature: 19.4, templow: 11.0, precipitation: 3.2, precipitation_probability: 60 },
    { datetime: '2026-06-13T00:00:00', condition: 'partlycloudy', temperature: 21.0, templow: 10.2, precipitation: 0.4, precipitation_probability: 20 },
    { datetime: '2026-06-14T00:00:00', condition: 'cloudy', temperature: 20.0, templow: 9.9, precipitation: 0, precipitation_probability: 10 },
  ];
  const { window, errors } = boot({
    search: '',
    config: { birdnetGoUrl: '', sitConfidence: 0.96,
      wall: { weather: true, haToken: 'T', forecastDays: 3 } },
    onFetch: () => (url, opts) => {
      const u = String(url);
      const p = u.replace('http://ha.local:8080', '');
      if (u.startsWith('/api/') || u.includes('ha.local:8123/api/')) {
        const ap = u.slice(u.indexOf('/api/') + 4);
        if (ap.startsWith('/services/weather/get_forecasts')) {
          sawForecastCall = true;
          const body = JSON.parse((opts && opts.body) || '{}');
          assert.strictEqual(body.type, 'daily', 'asks for the daily forecast');
          return ok({ changed_states: [], service_response: { 'weather.forecast_home': { forecast: fc } } });
        }
        if (ap === '/states') return ok([{ entity_id: 'weather.forecast_home', state: 'sunny' }]);
        if (ap === '/states/weather.forecast_home') return ok({
          state: 'sunny',
          attributes: { temperature: 22, precipitation_unit: 'mm' },
        });
        if (ap === '/states/sun.sun') return ok({ attributes: {} });
        return nf();
      }
      return bgData(p) || nf();
    },
  });
  setTimeout(() => {
    const doc = window.document;
    try {
      assert.ok(sawForecastCall, 'called weather.get_forecasts');
      const strip = doc.getElementById('wwForecast');
      assert.ok(!strip.hidden, 'forecast strip visible');
      const cols = [...strip.querySelectorAll('.ww-fc-day')];
      assert.strictEqual(cols.length, 3, 'forecastDays:3 -> 3 columns, got ' + cols.length);
      assert.ok(/24°/.test(cols[0].textContent), 'day 1 high shown: ' + cols[0].textContent);
      assert.ok(/13°/.test(cols[0].textContent), 'day 1 low shown (rounded): ' + cols[0].textContent);
      assert.ok(/3\.2mm/.test(cols[1].textContent) && /60%/.test(cols[1].textContent), 'day 2 precip amount + chance: ' + cols[1].textContent);
      assert.ok(!/mm/.test(cols[0].textContent) && !/%/.test(cols[0].textContent), 'dry day 1 has no precip text: ' + cols[0].textContent);
      assert.deepStrictEqual(errors, [], 'errors: ' + errors.join('; '));
      console.log('C: daily forecast OK (get_forecasts, column count, high/low, precip)');
      if (++done === 6) { console.log('\nWALL V2 TESTS PASSED'); process.exit(0); }
    } catch (e) { console.error('C FAIL:', e.message); process.exit(1); }
  }, 1600);
}

// --- Scenario D: Audubon analog dial (clock_style: analog) ---
{
  // Two species with distinct morning vs afternoon hourly_counts so the
  // assignment has something to chew on.
  const morningBird = { scientific_name: 'Turdus migratorius', common_name: 'American Robin',
    count: 300, max_confidence: 0.95, latest_heard: '07:30:00',
    hourly_counts: [0,0,0,0,0,0,9,9,4,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0] };
  const duskBird = { scientific_name: 'Strix varia', common_name: 'Barred Owl',
    count: 120, max_confidence: 0.9, latest_heard: '19:40:00',
    hourly_counts: [1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,6,7,3,0,0,1] };
  const clockDaily = [morningBird, duskBird];
  const { window, errors } = boot({
    search: '',
    config: { birdnetGoUrl: '', sitConfidence: 0.96,
      wall: { clock: true, clockStyle: 'analog', clockHours: 12, clockSeconds: true } },
    onFetch: () => (url) => {
      const p = String(url).replace('http://ha.local:8080', '');
      if (p.startsWith('/api/v2/analytics/species/daily')) return ok(clockDaily);
      return bgData(p) || nf();
    },
  });
  setTimeout(() => {
    const doc = window.document;
    try {
      const clock = doc.getElementById('wwClock');
      assert.ok(clock.classList.contains('ww-analog'), '#wwClock marked ww-analog');
      assert.ok(clock.classList.contains('ww-digital-hidden'), 'analog style hides the digital line');
      const dial = doc.getElementById('wwDial');
      assert.ok(!dial.hidden, 'dial visible');
      const face = doc.getElementById('wwDialFace');
      assert.ok(face.querySelector('.ww-hand-h') && face.querySelector('.ww-hand-m'), 'hour + minute hands drawn');
      assert.ok(face.querySelector('.ww-hand-s'), 'second hand drawn (clockSeconds)');
      assert.strictEqual(face.querySelectorAll('.ww-dial-tick').length, 12, '12 hour ticks');
      // Hands carry a rotate() transform from the tick loop.
      assert.ok(/rotate\(/.test(face.querySelector('.ww-hand-h').style.transform || ''), 'hour hand rotated');
      const birds = doc.getElementById('wwDialBirds').querySelectorAll('img.ww-dial-bird');
      assert.ok(birds.length >= 1, 'rim birds rendered: ' + birds.length);
      // The morning bird should own a morning position (hour 6/7 -> pos 6/7),
      // the owl an evening one (hour 18/19 -> pos 6/7 folds... use 24h check
      // separately). Here just assert both assigned species appear.
      const scis = [...birds].map((b) => b.getAttribute('data-sci'));
      assert.ok(scis.includes('Turdus migratorius'), 'robin on the dial');
      assert.ok(scis.includes('Strix varia'), 'owl on the dial');
      // Persisted for hysteresis on the next recompute.
      let saved = null;
      try { saved = JSON.parse(window.localStorage.getItem('bird:clockAssign')); } catch (e) {}
      assert.ok(saved && saved.positions === 12 && saved.byPos, 'assignment persisted to localStorage');
      assert.deepStrictEqual(errors, [], 'errors: ' + errors.join('; '));
      console.log('D: analog dial OK (face, hands, ticks, rim birds, persistence)');
      if (++done === 6) { console.log('\nWALL V2 TESTS PASSED'); process.exit(0); }
    } catch (e) { console.error('D FAIL:', e.message); process.exit(1); }
  }, 1600);
}

// --- Scenario E: calendar (month grid + agenda via calendar.get_events) ---
{
  const pad = (n) => String(n).padStart(2, '0');
  const d0 = new Date();
  const todayStr = d0.getFullYear() + '-' + pad(d0.getMonth() + 1) + '-' + pad(d0.getDate());
  const tmr = new Date(d0.getTime() + 86400000);
  const tmrStr = tmr.getFullYear() + '-' + pad(tmr.getMonth() + 1) + '-' + pad(tmr.getDate());
  const tmrTimed = tmrStr + 'T09:30:00';
  const events = [
    { start: todayStr, end: tmrStr, summary: 'Recycling day' },                // all-day today (exclusive end)
    { start: tmrTimed, end: tmrStr + 'T10:30:00', summary: 'Dentist' },        // timed tomorrow
  ];
  let sawGetEvents = false;
  const { window, errors } = boot({
    search: '',
    config: { birdnetGoUrl: '', sitConfidence: 0.96,
      wall: { calendar: true, calendarEntities: ['calendar.test'], calendarView: 'both', haToken: 'T' } },
    onFetch: () => (url, opts) => {
      const u = String(url);
      if (u.includes('/api/services/calendar/get_events')) {
        sawGetEvents = true;
        assert.ok(/return_response/.test(u), 'uses the return_response path');
        const body = JSON.parse((opts && opts.body) || '{}');
        assert.deepStrictEqual(body.entity_id, ['calendar.test'], 'passes the configured entity');
        return ok({ service_response: { 'calendar.test': { events } } });
      }
      const p = u.replace('http://ha.local:8080', '');
      return bgData(p) || nf();
    },
  });
  setTimeout(() => {
    const doc = window.document;
    try {
      assert.ok(sawGetEvents, 'called calendar.get_events');
      const cal = doc.getElementById('wwCalendar');
      assert.ok(!cal.hidden, 'calendar visible');
      const today = cal.querySelector('.ww-cal-grid td.is-today');
      assert.ok(today, 'today highlighted in the month grid');
      assert.ok(today.classList.contains('has-ev'), "today's recycling event dotted");
      const agenda = [...cal.querySelectorAll('.ww-cal-agenda li')];
      assert.ok(agenda.length >= 2, 'agenda lists both events: ' + agenda.length);
      assert.ok(/Today/i.test(agenda[0].textContent) && /Recycling/.test(agenda[0].textContent), 'all-day today first: ' + agenda[0].textContent);
      assert.ok(/Tomorrow/i.test(agenda[1].textContent) && /Dentist/.test(agenda[1].textContent), 'timed tomorrow second: ' + agenda[1].textContent);
      assert.deepStrictEqual(errors, [], 'errors: ' + errors.join('; '));
      console.log('E: calendar OK (get_events, month grid, today dot, agenda labels)');
      if (++done === 6) { console.log('\nWALL V2 TESTS PASSED'); process.exit(0); }
    } catch (e) { console.error('E FAIL:', e.message); process.exit(1); }
  }, 1600);
}

// --- Scenario F: chime autoplay-unlock overlay ---
{
  const browserChime = boot({
    search: '',
    config: { birdnetGoUrl: '', sitConfidence: 0.96,
      wall: { clock: true, clockStyle: 'analog', clockChime: true, clockChimeOutput: 'browser' } },
    onFetch: () => (url) => {
      const p = String(url).replace('http://ha.local:8080', '');
      if (p.startsWith('/api/v2/analytics/species/daily')) return ok(daily);
      return bgData(p) || nf();
    },
  });
  const mpChime = boot({
    search: '',
    config: { birdnetGoUrl: '', sitConfidence: 0.96,
      wall: { clock: true, clockStyle: 'analog', clockChime: true,
        clockChimeOutput: 'media_player', clockChimeMediaPlayer: 'media_player.den' } },
    onFetch: () => (url) => {
      const p = String(url).replace('http://ha.local:8080', '');
      if (p.startsWith('/api/v2/analytics/species/daily')) return ok(daily);
      return bgData(p) || nf();
    },
  });
  setTimeout(() => {
    try {
      const bDoc = browserChime.window.document;
      const overlay = bDoc.getElementById('wwChimeUnlock');
      assert.ok(!overlay.hidden, 'browser chimes: unlock overlay shown until a gesture');
      overlay.dispatchEvent(new browserChime.window.MouseEvent('click', { bubbles: true }));
      assert.ok(overlay.hidden, 'overlay hides once tapped (audio unlocked)');
      assert.deepStrictEqual(browserChime.errors, [], 'browser errors: ' + browserChime.errors.join('; '));

      const mDoc = mpChime.window.document;
      assert.ok(mDoc.getElementById('wwChimeUnlock').hidden, 'media_player output: no unlock overlay');
      assert.deepStrictEqual(mpChime.errors, [], 'mp errors: ' + mpChime.errors.join('; '));

      console.log('F: chime unlock overlay OK (shown for browser, tapped-away, absent for media_player)');
      if (++done === 6) { console.log('\nWALL V2 TESTS PASSED'); process.exit(0); }
    } catch (e) { console.error('F FAIL:', e.message); process.exit(1); }
  }, 1600);
}
