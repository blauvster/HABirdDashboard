"""Hour -> bird assignment for the Audubon-clock chime (pure; no HA imports).

Direct port of the JS algorithm in homeassistant/www/apt.js lines 1603-1849
(`assignHours` et al - that block is itself sliced out and unit-tested in
isolation by tests/test-clock-assign.js). Kept free of Home Assistant
imports for the same reason the JS block is kept free of DOM/hass
references: it's plain data in, plain data out, and testable with fixtures
alone (see tests/test_assignment.py, which mirrors the JS fixtures exactly).

Given a species x hour-of-day count matrix, assigns one bird to each of the
clock's 12 (or 24) hour positions, one-to-one, via max-weight bipartite
matching (Hungarian) over a score that rewards a bird being BOTH
concentrated at an hour (affinity) and dominant within it (dominance),
tie-broken by support - raw counts alone would hand every hour to the
single commonest backyard bird.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Matrix = dict[str, list[float]]


def clock_pos_of_hour(hour: int, positions: int) -> int:
    """Clock position (1..positions) for an hour-of-day.

    12-hour: position 12 sits at the top and covers hours 0 and 12.
    24-hour: position 24 is midnight.
    """
    hour = hour % 24
    if positions == 24:
        return 24 if hour == 0 else hour
    return ((hour + 11) % 12) + 1


def hours_for_position(position: int, positions: int) -> list[int]:
    """Inverse of clock_pos_of_hour: which hour(s)-of-day a position covers.

    24-hour mode: exactly one hour. 12-hour mode: two (h and h+12, folded
    together) - except positions with no such hour return an empty list.
    """
    return [hour for hour in range(24) if clock_pos_of_hour(hour, positions) == position]


def _hungarian_max_weight(weight: list[list[float]]) -> list[int]:
    """Max-weight perfect matching on a square weight matrix (n x n).

    O(n^3) Hungarian / Kuhn-Munkres shortest-augmenting-path form, run on
    cost = (maxWeight + 1) - weight. Returns row -> col (0-indexed).
    """
    n = len(weight)
    if not n:
        return []
    big = 0.0
    for row in weight:
        for value in row:
            if value > big:
                big = value
    big += 1
    a = [[0.0] * (n + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, n + 1):
            a[i][j] = big - weight[i - 1][j - 1]
    inf = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for row_idx in range(1, n + 1):
        p[0] = row_idx
        j0 = 0
        minv = [inf] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, -1
            for j in range(1, n + 1):
                if used[j]:
                    continue
                cur = a[i0][j] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j0_prev = way[j0]
            p[j0] = p[j0_prev]
            j0 = j0_prev
            if not j0:
                break
    res = [-1] * n
    for col in range(1, n + 1):
        if p[col] > 0:
            res[p[col] - 1] = col - 1
    return res


def _fold_matrix(matrix: Matrix, positions: int) -> Matrix:
    """{sci: number[24]} -> {sci: number[positions]}.

    Sums each hour into its clock position (12-hour mode adds hour h and
    hour h+12 together).
    """
    folded: Matrix = {}
    for sci, src in (matrix or {}).items():
        out = [0.0] * positions
        for hour in range(24):
            out[clock_pos_of_hour(hour, positions) - 1] += float(src[hour]) if hour < len(src) else 0.0
        folded[sci] = out
    return folded


@dataclass
class _ScoreResult:
    score: dict[str, list[float]]
    col_total: list[float]
    row_total: dict[str, float]


def _score_matrix(folded: Matrix, positions: int) -> _ScoreResult:
    """score[sci][pos] = sqrt(affinity * dominance) * support."""
    scis = list(folded.keys())
    col_total = [0.0] * positions
    row_total: dict[str, float] = {}
    for sci in scis:
        row = folded[sci]
        total = 0.0
        for pos in range(positions):
            total += row[pos]
            col_total[pos] += row[pos]
        row_total[sci] = total
    score: dict[str, list[float]] = {}
    for sci in scis:
        row = folded[sci]
        sr = [0.0] * positions
        for pos in range(positions):
            cnt = row[pos]
            if not cnt or not row_total[sci] or not col_total[pos]:
                continue
            affinity = cnt / row_total[sci]  # how characteristic this hour is of the bird
            dominance = cnt / col_total[pos]  # how much of this hour belongs to the bird
            support = math.log(1 + cnt)  # lean toward well-attested birds
            sr[pos] = math.sqrt(affinity * dominance) * support
        score[sci] = sr
    return _ScoreResult(score=score, col_total=col_total, row_total=row_total)


@dataclass
class Assignment:
    species: str | None
    source: str  # pinned | history | borrowed | fallback | reused
    score: float
    dim: bool


def assign_hours(
    matrix: Matrix,
    *,
    positions: int = 12,
    pins: dict[int, str] | None = None,
    incumbents: dict[int, str] | None = None,
    hysteresis: float = 0.25,
    exclude_sci: list[str] | None = None,
) -> dict[int, Assignment]:
    """matrix: {sci: number[24]} -> {pos: Assignment}.

    opts mirror apt.js's assignHours(matrix, opts):
      positions   12 | 24 (default 12; 12 folds hour h with h+12)
      pins        {pos: sci}  hard assignments
      incumbents  {pos: sci}  previous result -> hysteresis
      hysteresis  a challenger must beat the incumbent's score by this
                  fraction to unseat it (default 0.25)
      exclude_sci species left out of the automatic pool entirely
                  (matched/borrowed/fallback) - pins still win regardless
    """
    positions = 24 if positions == 24 else 12
    pins = pins or {}
    incumbents = incumbents or {}
    exclude = set(exclude_sci or [])

    out: dict[int, Assignment] = {}
    folded = _fold_matrix(matrix, positions)

    # 1. Pins first: fix the position and drop the species from the pool, so
    #    the solver structurally cannot double-assign it.
    pinned_sci: set[str] = set()
    open_pos: list[int] = []
    for pos in range(1, positions + 1):
        if pos in pins:
            out[pos] = Assignment(species=pins[pos], source="pinned", score=math.inf, dim=False)
            pinned_sci.add(pins[pos])
        else:
            open_pos.append(pos)

    pool_folded = {sci: row for sci, row in folded.items() if sci not in pinned_sci and sci not in exclude}
    pool = list(pool_folded.keys())

    # 2. Score over the remaining pool, then Hungarian over the open
    #    positions that actually have detections.
    sm = _score_matrix(pool_folded, positions)

    def pos_has_data(pos: int) -> bool:
        return sm.col_total[pos - 1] > 0

    data_pos = [pos for pos in open_pos if pos_has_data(pos)]
    empty_pos = [pos for pos in open_pos if not pos_has_data(pos)]

    used: set[str] = set()
    if data_pos and pool:
        r, k = len(data_pos), len(pool)
        n = max(r, k)
        weight = [[0.0] * n for _ in range(n)]
        for wi in range(n):
            if wi >= r:
                continue
            for wj in range(k):
                sc = sm.score[pool[wj]][data_pos[wi] - 1]
                # Hysteresis: inflate the incumbent's own cell so a
                # challenger has to clear it by `hysteresis` before the
                # matching prefers the swap.
                if incumbents.get(data_pos[wi]) == pool[wj] and sc > 0:
                    sc *= 1 + hysteresis
                weight[wi][wj] = sc
        match = _hungarian_max_weight(weight)
        for mi in range(r):
            mj = match[mi]
            mpos = data_pos[mi]
            if mj < 0 or mj >= k:
                empty_pos.append(mpos)
                continue
            msci = pool[mj]
            raw = sm.score[msci][mpos - 1]
            if raw > 0:
                out[mpos] = Assignment(species=msci, source="history", score=raw, dim=False)
                used.add(msci)
            else:
                empty_pos.append(mpos)  # matched only to a bird never heard here
    else:
        empty_pos = list(open_pos)

    # 3. Positions with no data (or left unfilled): borrow the best
    #    still-unused bird from the nearest position that DOES have data;
    #    then the global top bird; then, pool exhausted, reuse it (marked).
    seen: set[int] = set()
    filtered_empty: list[int] = []
    for pos in empty_pos:
        if pos in out or pos in seen:
            continue
        seen.add(pos)
        filtered_empty.append(pos)
    empty_pos = sorted(filtered_empty)

    global_order = sorted(pool, key=lambda sci: sm.row_total.get(sci, 0.0), reverse=True)

    def circ_dist(x: int, y: int) -> int:
        d = abs(x - y)
        return min(d, positions - d)

    for pos in empty_pos:
        borrow: str | None = None
        best_d = math.inf
        for q in range(1, positions + 1):
            if q == pos or sm.col_total[q - 1] <= 0:
                continue
            d = circ_dist(pos, q)
            if d >= best_d:
                continue
            cand: str | None = None
            cand_score = -1.0
            for sci in pool:
                if sci in used:
                    continue
                qs = sm.score[sci][q - 1]
                if qs > cand_score:
                    cand_score, cand = qs, sci
            if cand:
                borrow, best_d = cand, d
        if borrow:
            out[pos] = Assignment(species=borrow, source="borrowed", score=0, dim=True)
            used.add(borrow)
            continue
        top = next((sci for sci in global_order if sci not in used), None)
        if top:
            out[pos] = Assignment(species=top, source="fallback", score=0, dim=True)
            used.add(top)
            continue
        out[pos] = (
            Assignment(species=global_order[0], source="reused", score=0, dim=True)
            if global_order
            else Assignment(species=None, source="fallback", score=0, dim=True)
        )

    return out
