# TODO — Audubon bird clock + calendar/weather for HABirdDashboard

Spec for a fork of
[`adamoberley/HABirdDashboard`](https://github.com/adamoberley/HABirdDashboard)
(default branch `HABirdDashboard`). Drop this file into the fork and work the
phases in order.

> The standalone `birdnet-clock-card` prototype is superseded. The only things
> worth carrying over are the **calendar** components and the **hour-assignment
> algorithm** — both described below, both rewritten to fit HABirdDashboard's
> plain-JS, single-app architecture.

---

## Goal

Turn the card into an **Audubon Society Singing Bird Clock** wall display:

1. **Analog clock face**; each of the 12 hour positions shows a **bird
   illustration** (reuse `avian/assets`, keyed by species).
2. On the hour, play **that hour's bird call** — like the real clock.
3. Each hour's bird comes from **that hour's detection history**, via the
   BirdNET-Go **API** (hourly-by-species counts, not HA recorder).
4. **No bird on more than one hour** (one-to-one).
5. An hour with **no detections** borrows the best bird from the **nearest hour**
   that has data.
6. The user can **pin a bird to an hour** in card config.
7. Static call file per bird — **no audio fetched from the API**.
8. Bring **weather** (already in the card) and a new **calendar** (month grid +
   agenda) into the same wall widget block.
9. The collage birds **pack around** the clock/weather/calendar block — filling
   the space around them, not overlapping.

---

## What the HABirdDashboard README / source tells us

- **API is reachable from the browser.** README: *"reads BirdNET-Go's API v2
  (public routes, CORS-open by default)"*. So direct `fetch` works — the only
  remaining risk is **mixed content** (HTTPS HA page → HTTP BirdNET). If that
  bites, put BirdNET behind the HA reverse proxy or use `data_source: ha`.
- **`data_source: auto | api | ha`** already exists, with automatic fallback to
  MQTT/recorder history when the API isn't reachable.
- **The packing engine already supports "obstacles."** `apt.js` reads the
  bounding box of an element with id `wallWidgets` at render time
  (`if (wwEl && !wwEl.hidden) addObstacle(wwEl)`), stamps a padded rectangle
  (margin `M ≈ 12px`) — or an **ellipse** in ring mode — into a coarse occupancy
  grid (`GRID_STRIDE` px/cell) *before* placing any bird, then spirals birds
  outward from the cluster centre of mass around it. A floated card title is
  also registered as an obstacle. **This is exactly the "birds fill the space
  around them" behavior — we mostly need to feed the right element to it.**
- Birds are placed by **silhouette mask** collision (`MASKS[slug]`, sparse
  base64 bitmap), not bounding boxes, so "wings cradle tails."
- `hass` is obtained via `AV_CFG.__getHass()`.
- **Weather** already reads the HA weather entity through the card's own
  connection (no token), sunrise/sunset from `sun.sun`, and falls back to
  BirdNET-Go's built-in weather if HA has no weather entity.
- **No calendar exists** in HABirdDashboard today.
- Art is kachō-e woodblock style, `sit_confidence` picks perched vs flight pose,
  license is CC-BY-NC-SA-4.0.
- Build: `node homeassistant/card/build.js` → `dist/habird-card.js`. Source of
  truth is `homeassistant/www/` (`index.html`, `apt.js`, `styles.css`,
  `config.js`).

---

## Layout — one wall widget block, birds pack around it

Render the analog clock, weather, and calendar as children of a **single
container** that the packer already treats as an obstacle:

```
#wallWidgets            ← packer reads this bbox, birds avoid it
  .ww-clock             ← analog dial (Audubon bird clock)
  .ww-weather           ← current + forecast strip (existing weather code)
  .ww-calendar          ← month grid and/or agenda (new)
```

Tasks:

- Confirm the current clock/weather DOM is (or becomes) `#wallWidgets`; move
  weather + the new calendar inside it so they register as **one** obstacle.
- The obstacle rect must track the block's **real rendered size** — the month
  grid is large and its height changes with 5 vs 6 week rows. Re-measure on
  resize and after the calendar data loads (the packer already re-reads bbox at
  render; make sure a calendar update triggers a re-render).
- **Round clock → elliptical keep-out.** Extend `addObstacle(el, {ellipse})` so
  the round dial reserves an ellipse, letting birds tuck into the four corners
  of its bounding square. The engine already has ellipse obstacle support
  (`ob.ellipse`) — reuse it.
- Keep `corner` working: the whole block still anchors to a configurable corner;
  in a full-screen panel view the block can also go `center` with the flock
  ringing it (pairs well with `collage_shape: ring`, `collage_hole`).
- Nothing about mask-based bird placement changes — only the obstacle input.

---

## The analog clock

HABirdDashboard's current clock is a **digital serif block**. New work:

- SVG dial: face, ticks, hour/minute/second hands. Use the "unwrapped angle"
  trick (keep a running cumulative angle) so hands don't spin backwards through
  the face at the 360°→0° wrap.
- 12 (or 24) **bird thumbnails** positioned around the rim at the hour marks,
  each the species' illustration via the existing loader (CDN / `image_base` /
  `avian/assets`). Show the species name on the active/hovered hour.
- `clock_style: digital | analog | both` — default keeps digital so existing
  users are unaffected.
- Tap a rim bird → play its call now + honor existing `tap_action`.
- Second hand is optional (`clock_seconds`) — a moving hand forces a 1s
  re-render loop; make sure that doesn't re-run the packer.

---

## Hour → bird assignment

### Positions: 12, folding AM+PM (default)
The physical clock has 12 birds. For clock position *h* (1–12), sum detection
counts from hour *h* and hour *h+12* before assigning. `clock_hours: 24` opt-in
gives distinct dawn-chorus vs dusk birds and swaps the 12-bird face at noon
(needs 24 distinct species in the pool).

### It's an assignment problem — Hungarian, not greedy
Greedy visibly fails: a species leading hours 6–8 takes hour 6, then 7 and 8
fall to weak leftovers. Build a `positions × species` score matrix and solve for
the max-weight one-to-one matching (Hungarian / Kuhn–Munkres, ~80 lines,
microseconds at this size). One-to-one enforces requirement 4 by construction.

### Score (position *p*, species *s*)
Raw counts hand every hour to the single most common backyard bird. Instead:

- **affinity** `A = c(s,p) / Σ_p c(s,·)` — how characteristic this hour is *of that bird*
- **dominance** `D = c(s,p) / Σ_s c(·,p)` — how much of this hour *belongs to* that bird
- **support** `S = log(1 + c(s,p))` — tie-break toward well-attested birds
- `score = sqrt(A · D) · S`

### Order of operations
1. **Pins first.** Remove pinned species *and* their positions from the matrix
   before solving — the solver then structurally cannot double-assign them.
2. **Hungarian** over the remaining positions × remaining pool.
3. **Empty positions** (no data at *h* / *h+12*): walk outward by circular
   distance (±1, ±2 …), take the best still-unused species from the nearest
   position with data. Final fallback: global top species.
4. Pool smaller than positions to fill → allow reuse only as a last resort and
   mark those positions (dim the thumbnail) so thin data is visible.

### Stability
Compute over a long window (`clock_window_days`, default 30), recompute on a
cadence (`clock_reassign: daily`), **persist** the result, and apply hysteresis
— only unseat an incumbent bird if the challenger's score beats it by ≥ 25%.

### Implementation
Pure function, no DOM / no `hass`:
`assignHours(matrix, { positions, pins }) → { [pos]: { species, source } }`
with `source ∈ {pinned, history, borrowed, fallback}`. Fully unit-testable.

---

## Audio / chimes

Static files. Resolution order per position:
`hour_call_overrides[h]` → `{clock_call_base}{scientific-slug}.mp3` → silent
(log once).

**Browser autoplay is the real hazard.** No sound until a genuine user gesture —
an untouched wall kiosk stays silent and looks broken. Mitigations:

- One-tap "enable chimes" overlay that unlocks the `AudioContext`; keep showing
  it until unlock succeeds.
- Document `--autoplay-policy=no-user-gesture-required` for kiosk Chromium.
- `clock_chime_output: media_player` routes the call to a real HA speaker via
  `media_player.play_media` — sidesteps autoplay entirely.

Also: quiet hours, volume, fire exactly once per hour change (dedupe across
re-renders).

---

## Calendar (new — port from the prototype)

HABirdDashboard has no calendar. Port the prototype's approach, rewritten to
plain JS in `apt.js`:

- **Fetch:** `hass.callWS({ type: "call_service", domain: "calendar",
  service: "get_events", target: { entity_id: [...] }, service_data:
  { start_date_time, end_date_time }, return_response: true })`. Poll every
  ~5 min; window ≈ 35 days.
- Parse all-day (`YYYY-MM-DD`) vs timed (`YYYY-MM-DD HH:MM:SS`, local) starts.
- **Month grid:** 6-week (auto-trim to 5) table, today highlighted, days with
  events underlined/dotted, `calendar_week_start: sunday | monday`, narrow
  weekday labels via `Intl.DateTimeFormat`.
- **Agenda:** next N events within `agenda_days_ahead`, "Today/Tomorrow/Wed"
  labels, all-day vs time.
- Renders inside `#wallWidgets` (`.ww-calendar`) so birds pack around it.
- Style to match the woodblock/`paper` theme (light + dark), not the
  prototype's fixed dark palette.

---

## New / changed config options

```yaml
type: custom:habird-card

# clock
clock: true                 # existing on/off
clock_style: analog         # digital | analog | both   (NEW; default digital)
clock_birds: true           # illustration at each hour position
clock_hours: 12             # 12 | 24
clock_seconds: false        # show a second hand
clock_window_days: 30       # history window for assignment
clock_reassign: daily       # daily | hourly | manual
clock_min_confidence: 0.5

# chimes
clock_chime: true
clock_chime_quiet_hours: "22:00-07:00"
clock_chime_volume: 0.7
clock_chime_output: browser         # browser | media_player
clock_chime_media_player: media_player.living_room
clock_call_base: /local/birdcalls/  # {scientific-slug}.mp3

# manual assignment
hour_birds:
  7: Turdus migratorius
  18: Strix varia
hour_call_overrides:
  7: /local/birdcalls/robin-custom.mp3

# weather (mostly exists already)
weather: true
weather_entity:             # empty = first weather.* entity
forecast_days: 0            # DONE (not clock-specific): N-day daily forecast
                            #   (glyph + high/low + precip amount & chance)
                            #   under current conditions, via HA
                            #   weather.get_forecasts. 0 = off.

# calendar (NEW)
calendar: true
calendar_entities: [calendar.family, calendar.holidays]
calendar_view: both         # month | agenda | both
calendar_week_start: sunday
agenda_days_ahead: 7
agenda_max_events: 6

# layout
corner: top-left            # existing; + allow `center` for panel view
```

---

## API work

Extend the BirdNET-Go adapter in `apt.js`.

| Need | Endpoint | Notes |
|---|---|---|
| Species pool + totals | `GET /api/v2/analytics/species/summary?start_date&end_date` | already used |
| **Species × hour matrix** | `GET /api/v2/analytics/time/hourly/batch?species=<repeat>&start_date&end_date&min_confidence` | one call for the whole pool; **verify response shape** (per-species 24-bucket array aggregated across range) |
| Overall hourly distribution | `GET /api/v2/analytics/time/distribution/hourly` | already used; fallback / sanity check |
| `ha` fallback | bucket recorder history by `getHours()` per species | degraded; note pinning matters more here |

Dial images use the existing illustration loader — no new media calls.

---

## File-by-file

- **`homeassistant/www/apt.js`**
  - `assignHours(...)` — pure module, unit tested.
  - Adapter: `fetchHourlyMatrix(pool, start, end, minConfidence)`.
  - Analog dial renderer + rim thumbnails.
  - Chime scheduler + `AudioContext` unlock overlay + `media_player` path.
  - Calendar: fetch + month grid + agenda renderers.
  - `#wallWidgets` container groups clock + weather + calendar; ensure
    `addObstacle` picks it up and (new) supports an `{ellipse}` hint for the
    round dial.
  - Wire all new config keys through the options parser + defaults.
  - Guard against the 1s clock tick re-running the packer.
- **`homeassistant/www/styles.css`** — dial, rim thumbnails, active-hour label,
  calendar grid + agenda, unlock overlay. Must work in `paper` + `transparent`
  backgrounds and light/dark.
- **`homeassistant/www/config.js`** — standalone-page defaults for new keys.
- **`homeassistant/card/build.js`** — add any new source file to the bundle
  include list.
- **Card editor** — if HABirdDashboard ships `getConfigElement`, add controls
  for `clock_style`, `clock_hours`, the chime group, calendar group, and a
  12-row per-hour "pin a bird" table populated from the live species pool.
  YAML-only is acceptable for v1 — say so in the README.
- **`README.md` / `CHANGELOG.md`** — document the mode, config, the
  `/local/birdcalls/` convention, calendar setup, kiosk autoplay flag.

---

## Testing

- **Assignment unit tests** (`tests/`), synthetic matrices:
  - dawn-chorus spike; one species dominant across all hours (must NOT sweep);
    only 4 hours have data (borrow fills rest, no dupes); all-empty (fallback,
    no dupes until pool exhausted); pins removed cleanly; hysteresis holds
    incumbent within 25%.
  - 12-mode AM+PM fold → 12 unique; 24-mode → 24 unique or documented reuse.
- **Layout**: block registers as one obstacle; birds never overlap it; obstacle
  rect updates when the calendar grows to 6 rows or the viewport resizes;
  elliptical keep-out lets birds into the dial's bounding-box corners.
- **Chime**: once per hour, silent in quiet hours, silent until unlock, routes
  to `media_player` when configured.
- **Calendar**: all-day vs timed parsing; month rollover; empty-calendar state.
- **Manual**: kiosk Chromium with the autoplay flag; unlock overlay on a tablet.

---

## Phases

- [x] **P1 — API**: `clockHourMatrix()` in the adapter — tries
  `analytics/time/hourly/batch` (defensive multi-shape parser), falls back to
  summing `analytics/species/daily` per day, and `ha` mode buckets the
  reconstructed MQTT stream by `getHours()`. **Batch response shape still
  unverified against a live server** — the daily-summary fallback is the
  reliable path.
- [x] **P2 — Assignment engine**: `assignHours()` + `_hungarianMaxWeight()` +
  affinity/dominance/support scoring + pins + borrow-walk + hysteresis, as a
  sliced-out pure block. `tests/test-clock-assign.js` (13 checks).
- [x] **P3 — Wall widget block + layout**: `addObstacle(el, {ellipse})`;
  `#wallWidgets` registers clock/weather/calendar as separate obstacles (dial
  = ellipse keep-out), falling back to the whole block. `test-wall.js` A.
- [x] **P4 — Analog dial**: SVG face + ticks + unwrapped-angle hands + rim
  thumbnails (existing loader) + active/hover species label; `clock_style` /
  `clock_hours` / `clock_seconds` / `clock_birds`. 1s hand loop is
  transform-only — never re-runs the packer. `test-wall.js` D.
  *Deviation:* 24-mode shows all 24 rim thumbnails rather than swapping a
  12-bird face at noon.
- [x] **P5 — Calendar**: `haCallService()` + `fetchCalendarEvents()` (5-min
  poll, 35-day window), month grid (5/6-week auto-trim, today, event dots,
  week-start) + agenda (Today/Tomorrow/weekday), themed. `test-wall.js` E.
- [x] **P6 — Chimes**: hourly scheduler on the tick loop (once-per-hour
  dedupe, never on load), quiet hours, volume, `AudioContext` unlock overlay,
  `media_player` `play_media` output, `hour_call_overrides` → `{base}{slug}.mp3`
  → silent. `test-wall.js` F.
- [x] **P7 — Overrides + editor + docs**: `hour_birds` / `hour_call_overrides`
  wired; editor gains "Audubon clock" + "Calendar" expandable sections (no
  per-hour pin table — YAML only); README + CHANGELOG + config.js.

**Verified:** `npm run build` + `npm test` — all suites green, incl. the new
`test-clock-assign.js` and 6 wall-widget scenarios (A–F) in `test-wall.js`.
**Not verifiable here** (needs a browser + HA + BirdNET-Go): the dial's visual
layout / rim-bird placement, hand smoothness, chime playback, calendar grid
sizing, `time/hourly/batch` shape, and mixed-content behaviour.

---

## Decisions (confirmed 2026-09-08)

1. **`clock_hours` default: 12**, folding AM+PM. `clock_hours: 24` stays opt-in.
2. **Sum** hour *h* and hour *h+12* counts before scoring — not "stronger hour".
   The affinity/dominance/support scoring already normalizes; summing maximizes
   support and stability.
3. **Chime default output: `browser`** with the one-tap unlock overlay. Zero
   config on the wall tablet. `clock_chime_output: media_player` documented as
   the autoplay-proof alternative.
4. **YAML-only pin UI for v1** (`hour_birds` map). Defer the live-pool editor
   table; say so in the README.
5. **Woodblock illustrations** for rim birds — existing `avian/assets` loader,
   matches the kachō-e collage. No photo cutouts.
6. Hour with no data and no nearby hour with data → **global top species,
   thumbnail dimmed** (same dim treatment as last-resort reuse in step 4 of the
   assignment). Never leave a rim position blank.
7. **Panel-first, degrade gracefully.** Full experience (12-bird dial + weather +
   forecast + month grid) targets panel / full-screen view. At sidebar-card
   size: keep the dial + current weather, drop the rim species labels and the
   calendar month grid (fall back to agenda-only, or hide the calendar). No full
   responsive layout work to cram everything into a small card.
8. **`clock_style: analog` renders the dial only** — no digital time/date line
   (real Audubon clocks have no digits). `clock_style: both` is the opt-in for
   users who want the digital block beneath the dial. `digital` stays the
   default so existing users are unaffected.
   *Superseded 2026-09-09:* the dial became the intended main widget
   (`corner: center`), so the digital time + current conditions moved into
   the dial's own hub (`#wwDialCenter`) instead of a line below it —
   `clock_style: both` now shares that same hub rather than repeating them
   underneath. Hands are tapered lance shapes, not bare lines, and a rim
   position with a bird illustration drops its tick mark (one landmark per
   hour, not two).
   *Superseded 2026-09-11:* `corner: center` no longer centers the whole
   `#wallWidgets` block (clock + weather + calendar stacked together) — it
   now promotes just the clock into its own `#wallClock` box, dead-centre
   and alone, with the flock ringing it. Weather/calendar, if also on, fall
   back to `bottom-right` instead of piling into the middle with the dial.
   See `wallDisplay()` / the `clockStandalone` obstacle branch in
   `homeassistant/www/apt.js`.
   *Superseded 2026-09-11 (later same day):* the `corner: center` trigger
   above was itself replaced by a dedicated `clock_placement: grouped |
   main` option (+ `clock_size` in px) under the Audubon clock section,
   independent of `corner` (which now only ever steers weather/calendar).
   Also this round: chimes dropped the `browser` output entirely (needed a
   tap-to-unlock gesture on every dashboard load - a non-starter for an
   unattended wall display) along with `clock_call_base`/
   `hour_call_overrides` - the call is now resolved from Xeno-Canto via
   `resolveReferenceCall()`, the same lookup the reference-call tap/modal
   button uses, and cast to `clock_chime_media_player` only. The hour hand
   also picked up a real bug fix: in `clock_hours: 24` it was still
   sweeping the standard twice-a-day 12-hour cycle while the 24 rim
   thumbnails are spaced once-around-per-day, so the hand pointing at "5
   o'clock" never lined up with the position actually holding hour 5's
   bird - it now sweeps `(hour + m/60) / 24` turns in 24-position mode.
   `#wwDialCenter`'s background is a soft radial paper-colour fade now
   instead of a hard-edged bordered circle.
   *Superseded 2026-09-11 (third pass, same day):* `clock_size` became a
   free-form CSS size string (`'42vmin'`, `'20rem'`, not just px) - set
   directly as `--ww-dial-size`, so relative units scale with the
   viewport/card. `clock_style: analog` now truly means dial-only: it also
   hides `#wwDialCenter` (`.ww-dial-only`), which `both` still shows -
   they'd become functionally identical after the hub redesign above, which
   didn't match their editor labels ("Analog dial only" vs "+ digital
   readout"). `#wwDialCenter`'s background dropped the radial-gradient fade
   for an 8-direction paper-coloured text-shadow outline on the time/
   weather text itself - no background shape at all now, just an outlined
   glyph. And a real gap closed: `assignHours` gained `opts.excludeSci` -
   species probed (HEAD requests against both the illustration and cutout
   URLs, `speciesHasArt()`) and found to have NEITHER available are now
   excluded from the rim assignment entirely, so a position can no longer
   end up holding a species whose thumbnail just renders invisible
   (`__birdImgErr`'s final fallback is `visibility: hidden`, not a broken-
   image glyph - previously indistinguishable from "not assigned" without
   inspecting the DOM). Pins still override exclusion. Tested end-to-end in
   `test-wall.js` scenario H and unit-tested in `test-clock-assign.js`.
