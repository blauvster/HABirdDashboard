"""Species x hour-of-day count matrix, for the Audubon-clock chime assignment.

Port of apt.js's bgHourlyMatrix / _hourlyBatchParse / _hourly24 /
bgHourlyMatrixFromDaily (homeassistant/www/apt.js lines ~635-718): try
BirdNET-Go's hourly-batch analytics endpoint first (one request for every
species), and fall back to summing each day's `species/daily` hourly_counts
when the batch response shape isn't recognised - it has drifted across
BirdNET-Go builds, and older servers don't have the route at all.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .api import BirdNetGoClient, BirdNetGoError

Matrix = dict[str, list[int]]


def _hourly_24(value: Any) -> list[int]:
    out = [0] * 24
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            for row in value:
                hour = int(row.get("hour", row.get("h", -1)) or -1)
                if 0 <= hour < 24:
                    out[hour] += int(row.get("count", row.get("value", 0)) or 0)
        else:
            for hour, item in enumerate(value[:24]):
                out[hour] = int(item or 0)
    elif isinstance(value, dict):
        for hour in range(24):
            out[hour] = int(value.get(hour, value.get(str(hour), 0)) or 0)
    return out


def _parse_hourly_batch(payload: Any) -> Matrix | None:
    if not payload:
        return None
    body = payload.get("data", payload) if isinstance(payload, dict) else payload
    matrix: Matrix = {}
    if isinstance(body, list):
        for row in body:
            if not isinstance(row, dict):
                continue
            sci = row.get("scientific_name") or row.get("species") or row.get("sci") or row.get("name")
            if not sci:
                continue
            matrix[sci] = _hourly_24(
                row.get("hourly")
                or row.get("hourly_counts")
                or row.get("counts")
                or row.get("distribution")
                or row.get("data")
            )
    elif isinstance(body, dict):
        for sci, value in body.items():
            matrix[sci] = _hourly_24(value)
    if not matrix or not any(any(row) for row in matrix.values()):
        return None
    return matrix


async def _matrix_from_daily(client: BirdNetGoClient, start: date, end: date) -> Matrix:
    matrix: Matrix = {}
    day = start
    while day <= end:
        try:
            rows = await client.species_daily(day)
        except BirdNetGoError:
            rows = []
        for row in rows:
            sci = row.get("scientific_name")
            if not sci:
                continue
            mrow = matrix.setdefault(sci, [0] * 24)
            counts = row.get("hourly_counts") or []
            for hour in range(24):
                if hour < len(counts) and counts[hour]:
                    mrow[hour] += int(counts[hour])
        day += timedelta(days=1)
    return matrix


async def fetch_hourly_matrix(client: BirdNetGoClient, window_days: int, min_confidence: float = 0) -> Matrix:
    end = date.today()
    start = end - timedelta(days=max(1, window_days) - 1)
    try:
        payload = await client.hourly_batch(start, end, min_confidence)
    except BirdNetGoError:
        payload = None
    if payload is not None:
        matrix = _parse_hourly_batch(payload)
        if matrix is not None:
            return matrix
    return await _matrix_from_daily(client, start, end)
