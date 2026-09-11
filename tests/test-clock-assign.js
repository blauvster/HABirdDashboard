// Audubon clock hour->bird assignment: slice the pure block out of apt.js and
// exercise it against synthetic count matrices. No jsdom, no hass, no DOM -
// the whole point of the module is that it's verifiable in isolation.
const path = require('path');
const fs = require('fs');
const assert = require('assert');

const src = fs.readFileSync(path.resolve(__dirname, '..', 'homeassistant/www/apt.js'), 'utf8');
const start = src.indexOf('  function clockPosOfHour(');
const end = src.indexOf('  // ===================== end Audubon clock assignment');
assert.ok(start > 0 && end > start, 'could not locate the clock-assignment block in apt.js');
const block = src.slice(start, end);

// eslint-disable-next-line no-new-func
const { assignHours, clockPosOfHour } = new Function(block + '\nreturn { assignHours, clockPosOfHour };')();

let passed = 0;
function ok(name, fn) {
  try { fn(); console.log('  ok  ' + name); passed++; }
  catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exit(1); }
}

// Helper: a 24-length hour row that is `base` everywhere and `spike` on `hours`.
function row(base, spike, hours) {
  const r = new Array(24).fill(base);
  (hours || []).forEach((h) => { r[h] = spike; });
  return r;
}
function speciesSet(out) { return Object.keys(out).map((p) => out[p].species); }
function uniqueNonNull(list) {
  const seen = new Set(); let dupes = 0;
  list.forEach((s) => { if (s == null) return; if (seen.has(s)) dupes++; seen.add(s); });
  return { count: seen.size, dupes };
}

// ---- hour -> position folding ----
ok('12-hour fold maps midnight and noon to position 12', () => {
  assert.strictEqual(clockPosOfHour(0, 12), 12);
  assert.strictEqual(clockPosOfHour(12, 12), 12);
  assert.strictEqual(clockPosOfHour(1, 12), 1);
  assert.strictEqual(clockPosOfHour(13, 12), 1);
  assert.strictEqual(clockPosOfHour(23, 12), 11);
});
ok('24-hour mode: midnight is position 24, the rest are the hour', () => {
  assert.strictEqual(clockPosOfHour(0, 24), 24);
  assert.strictEqual(clockPosOfHour(6, 24), 6);
  assert.strictEqual(clockPosOfHour(23, 24), 23);
});

// ---- dawn-chorus spike: the bird that owns the morning gets the morning ----
ok('dawn-chorus bird lands on its dawn position', () => {
  const matrix = {
    'Turdus migratorius': row(0, 40, [6]),           // robin: hour 6 only
    'Zenaida macroura':   row(3, 3, []),             // dove: flat all day
    'Corvus brachyrhynchos': row(0, 20, [16]),       // crow: hour 16 only
    'Haemorhous mexicanus': row(2, 2, []),
  };
  const out = assignHours(matrix, { positions: 12 });
  assert.strictEqual(out[6].species, 'Turdus migratorius', 'robin on position 6 (hour 6)');
  assert.strictEqual(out[6].source, 'history');
  assert.strictEqual(out[4].species, 'Corvus brachyrhynchos', 'crow on position 4 (hour 16)');
});

// ---- one dominant species must NOT sweep every hour ----
ok('a species common in every hour takes just one position, specialists win theirs', () => {
  const matrix = { 'Passer domesticus': new Array(24).fill(50) }; // everywhere, always
  // 11 single-hour specialists on hours 1..11 (positions 1..11).
  const names = ['Turdus migratorius', 'Bubo virginianus', 'Cathartes aura', 'Hirundo rustica',
    'Corvus corax', 'Cardinalis cardinalis', 'Cyanocitta cristata', 'Sitta carolinensis',
    'Poecile atricapillus', 'Zenaida macroura', 'Spinus tristis'];
  names.forEach((nm, i) => { matrix[nm] = row(0, 30, [i + 1]); });

  const out = assignHours(matrix, { positions: 12 });
  const sparrowPositions = Object.keys(out).filter((p) => out[p].species === 'Passer domesticus');
  assert.strictEqual(sparrowPositions.length, 1, 'house sparrow holds exactly one position');
  names.forEach((nm, i) => {
    assert.strictEqual(out[i + 1].species, nm, nm + ' wins its hour (position ' + (i + 1) + ')');
  });
  const u = uniqueNonNull(speciesSet(out));
  assert.strictEqual(u.dupes, 0, 'no species assigned twice (pool == positions)');
  assert.strictEqual(u.count, 12, '12 distinct species');
});

// ---- only a few hours have data: borrow fills the rest, still one-to-one ----
ok('sparse data: borrow fills empty hours with no duplicates', () => {
  const matrix = {
    'Turdus migratorius': row(0, 20, [6]),
    'Cardinalis cardinalis': row(0, 18, [7]),
    'Cyanocitta cristata': row(0, 15, [8]),
    'Sitta carolinensis': row(0, 12, [9]),
    'Poecile atricapillus': row(0, 9, [6, 7]),
    'Zenaida macroura': row(0, 6, [8, 9]),
    'Spinus tristis': row(0, 4, [7, 8]),
    'Melospiza melodia': row(0, 3, [6, 9]),
    'Baeolophus bicolor': row(0, 2, [7]),
    'Junco hyemalis': row(0, 2, [8]),
    'Haemorhous mexicanus': row(0, 1, [9]),
    'Dryobates pubescens': row(0, 1, [6]),
  };
  const out = assignHours(matrix, { positions: 12 });
  assert.strictEqual(Object.keys(out).length, 12, 'all 12 positions filled');
  const u = uniqueNonNull(speciesSet(out));
  assert.strictEqual(u.dupes, 0, 'no duplicates across 12 positions');
  assert.strictEqual(u.count, 12, '12 distinct species');
  // Positions with no detections at all are marked thin.
  const borrowed = Object.keys(out).filter((p) => out[p].source === 'borrowed');
  assert.ok(borrowed.length > 0, 'some positions were borrowed');
  borrowed.forEach((p) => assert.strictEqual(out[p].dim, true, 'borrowed position ' + p + ' is dimmed'));
});

// ---- all empty: fall back, no dupes until the pool is exhausted ----
ok('empty matrix with a small pool: fallback, unique until exhausted then reused', () => {
  const matrix = {
    'Turdus migratorius': new Array(24).fill(0),
    'Cardinalis cardinalis': new Array(24).fill(0),
    'Cyanocitta cristata': new Array(24).fill(0),
  };
  // give them nonzero totals so globalOrder has a ranking
  matrix['Turdus migratorius'][6] = 5;
  matrix['Cardinalis cardinalis'][6] = 3;
  matrix['Cyanocitta cristata'][6] = 1;
  const out = assignHours(matrix, { positions: 12 });
  assert.strictEqual(Object.keys(out).length, 12);
  const species = speciesSet(out);
  const firstThree = new Set(species.slice(0, 3));
  assert.strictEqual(firstThree.size, 3, 'first three positions distinct while pool lasts');
  const reused = Object.keys(out).filter((p) => out[p].source === 'reused');
  assert.ok(reused.length >= 9, 'the rest reuse the top bird, marked "reused"');
  reused.forEach((p) => assert.strictEqual(out[p].dim, true));
});

ok('truly empty matrix: every position resolves to null/fallback, no throw', () => {
  const out = assignHours({}, { positions: 12 });
  assert.strictEqual(Object.keys(out).length, 12);
  Object.keys(out).forEach((p) => {
    assert.strictEqual(out[p].species, null);
    assert.strictEqual(out[p].source, 'fallback');
  });
});

// ---- pins: removed from the pool AND the position list before solving ----
ok('pins are honored and never double-assigned elsewhere', () => {
  const matrix = {
    'Strix varia':        row(0, 30, [18, 19, 20]),   // would naturally win pos 6/7
    'Turdus migratorius': row(0, 25, [6, 7]),
    'Cardinalis cardinalis': row(0, 20, [6, 7, 8]),
    'Cyanocitta cristata': row(0, 12, [9, 10]),
    'Sitta carolinensis': row(0, 8, [11, 12]),
  };
  const out = assignHours(matrix, {
    positions: 12,
    pins: { 6: 'Turdus migratorius', 7: 'Strix varia' },
  });
  assert.strictEqual(out[6].species, 'Turdus migratorius');
  assert.strictEqual(out[6].source, 'pinned');
  assert.strictEqual(out[7].species, 'Strix varia');
  assert.strictEqual(out[7].source, 'pinned');
  // Neither pinned species appears again anywhere.
  Object.keys(out).forEach((p) => {
    if (p === '6' || p === '7') return;
    assert.notStrictEqual(out[p].species, 'Turdus migratorius', 'robin not re-used at ' + p);
    assert.notStrictEqual(out[p].species, 'Strix varia', 'owl not re-used at ' + p);
  });
});

// ---- excludeSci: never matched, borrowed, or used as a fallback ----
ok('excludeSci keeps an art-less species out of every code path', () => {
  const matrix = {
    'Strix varia':        row(0, 30, [6]),      // would win position 6 outright
    'Turdus migratorius': row(0, 5, [6]),        // weaker at hour 6
    'Cardinalis cardinalis': row(0, 20, [7]),
    'Cyanocitta cristata': row(0, 12, [8]),
  };
  const out = assignHours(matrix, { positions: 12, excludeSci: ['Strix varia'] });
  assert.notStrictEqual(out[6].species, 'Strix varia', 'excluded species does not win its natural hour');
  assert.strictEqual(out[6].species, 'Turdus migratorius', 'next-best species wins instead');
  Object.keys(out).forEach((p) => {
    assert.notStrictEqual(out[p].species, 'Strix varia', 'excluded species never appears (position ' + p + ')');
  });
});
ok('excludeSci does not override an explicit pin', () => {
  const matrix = { 'Strix varia': row(0, 30, [6]), 'Turdus migratorius': row(0, 5, [7]) };
  const out = assignHours(matrix, {
    positions: 12,
    pins: { 6: 'Strix varia' },
    excludeSci: ['Strix varia'],
  });
  assert.strictEqual(out[6].species, 'Strix varia', 'a pin still wins even if also excluded');
  assert.strictEqual(out[6].source, 'pinned');
});

// ---- hysteresis: an incumbent within 25% keeps its slot ----
ok('hysteresis holds an incumbent when the challenger is only ~10% better', () => {
  // position 6 (hour 6): incumbent robin at 20, challenger cardinal at 22.
  const matrix = {
    'Turdus migratorius': row(0, 20, [6]),
    'Cardinalis cardinalis': row(0, 22, [6]),
    'Cyanocitta cristata': row(0, 30, [7]),
    'Sitta carolinensis': row(0, 10, [8]),
  };
  const held = assignHours(matrix, {
    positions: 12,
    incumbents: { 6: 'Turdus migratorius' },
    hysteresis: 0.25,
  });
  assert.strictEqual(held[6].species, 'Turdus migratorius', 'incumbent robin held within 25%');

  // Now make the challenger clearly better (2x) - it should take the slot.
  matrix['Cardinalis cardinalis'] = row(0, 200, [6]);
  const unseated = assignHours(matrix, {
    positions: 12,
    incumbents: { 6: 'Turdus migratorius' },
    hysteresis: 0.25,
  });
  assert.strictEqual(unseated[6].species, 'Cardinalis cardinalis', 'a 2x-stronger challenger unseats the incumbent');
});

// ---- 12-mode fold produces 12 unique; 24-mode 24 unique with enough pool ----
ok('12-mode with a rich pool: 12 distinct species', () => {
  const matrix = {};
  for (let h = 0; h < 12; h++) matrix['sp' + h] = row(0, 10 + h, [h, h + 12]);
  const out = assignHours(matrix, { positions: 12 });
  const u = uniqueNonNull(speciesSet(out));
  assert.strictEqual(u.count, 12);
  assert.strictEqual(u.dupes, 0);
});
ok('24-mode with 24 distinct hour specialists: 24 distinct species', () => {
  const matrix = {};
  for (let h = 0; h < 24; h++) matrix['sp' + h] = row(0, 10, [h]);
  const out = assignHours(matrix, { positions: 24 });
  assert.strictEqual(Object.keys(out).length, 24);
  const u = uniqueNonNull(speciesSet(out));
  assert.strictEqual(u.count, 24, '24 distinct');
  for (let h = 0; h < 24; h++) {
    const pos = clockPosOfHour(h, 24);
    assert.strictEqual(out[pos].species, 'sp' + h, 'hour ' + h + ' specialist on position ' + pos);
  }
});

console.log('\nCLOCK-ASSIGN TESTS PASSED (' + passed + ' checks)');
process.exit(0);
