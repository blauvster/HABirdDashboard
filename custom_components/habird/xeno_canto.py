"""Async Xeno-Canto client for the chime's reference-call lookup.

Port of apt.js's `resolveReferenceCall` / `_xcFetchWithRetry` / candidate
ranking (homeassistant/www/apt.js lines 959-1036). The per-species "last
known good" localStorage memory (`_refSaveWorking`/`_refCallOrder`, apt.js
lines 4663-4666) is deliberately not ported: that exists in the browser to
fall through to a second candidate when an `<audio>` element fails to play,
and this integration has no equivalent signal for whether a `media_player`
actually played what it was asked to - it always casts the top-ranked
candidate.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp

XC_API = "https://xeno-canto.org/api/3/recordings"
MAX_RETRIES = 3
_CALL_SONG_RE = re.compile(r"\b(call|song)\b")


class XenoCantoError(Exception):
    """Raised when no usable Xeno-Canto recording can be resolved."""


@dataclass
class ReferenceCall:
    url: str
    page: str
    recordist: str
    license: str
    type: str
    quality: str
    id: str


def _len_seconds(value: Any) -> int:
    # XC `length` is "m:ss" (or occasionally bare seconds).
    if value is None:
        return 0
    text = str(value)
    if ":" in text:
        minutes, _, seconds = text.partition(":")
        try:
            return int(minutes or 0) * 60 + int(seconds or 0)
        except ValueError:
            return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def _https(url: str | None) -> str:
    # XC returns protocol-relative URLs (//xeno-canto.org/...).
    if not url:
        return ""
    return f"https:{url}" if url.startswith("//") else url


async def _fetch_with_retry(session: aiohttp.ClientSession, url: str, attempt: int = 0) -> dict:
    # Bounded retry on 429 (rate limit) + transient 5xx, honoring
    # Retry-After - XC throttles free keys.
    async with session.get(url) as resp:
        if (resp.status == 429 or 500 <= resp.status < 600) and attempt < MAX_RETRIES:
            retry_after = resp.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after else float(2**attempt)
            except ValueError:
                wait = float(2**attempt)
            await asyncio.sleep(wait)
            return await _fetch_with_retry(session, url, attempt + 1)
        if resp.status != 200:
            raise XenoCantoError(f"xc-http-{resp.status}")
        return await resp.json()


async def resolve_reference_call(
    session: aiohttp.ClientSession, scientific_name: str, api_key: str
) -> list[ReferenceCall]:
    """Query Xeno-Canto for `scientific_name`, ranked best-first."""
    parts = scientific_name.strip().split()
    query = f'gen:"{parts[0]}"' if parts else ""
    if len(parts) > 1:
        query += f' sp:"{parts[1]}"'
    url = f"{XC_API}?query={quote(query, safe='')}&key={quote(api_key, safe='')}"
    payload = await _fetch_with_retry(session, url)
    recordings = payload.get("recordings") or []

    def sort_key(rec: dict) -> tuple[int, int, str]:
        # Rank: call/song over other types, then short clips (<=30s), then
        # best quality (q 'A' beats 'E').
        rec_type = (rec.get("type") or "").lower()
        pref = 0 if _CALL_SONG_RE.search(rec_type) else 1
        length = _len_seconds(rec.get("length"))
        shortish = 0 if 0 < length <= 30 else 1
        quality = (rec.get("q") or "E")[:1].upper()
        return (pref, shortish, quality)

    candidates = sorted((rec for rec in recordings if rec.get("file")), key=sort_key)
    # Kept wide (15) for parity with the card, even though this integration
    # only ever plays the top candidate today.
    calls = [
        ReferenceCall(
            url=_https(rec.get("file")),
            page=_https(rec.get("url")),
            recordist=rec.get("rec") or "",
            license=_https(rec.get("lic")),
            type=rec.get("type") or "",
            quality=rec.get("q") or "",
            id=rec.get("id") or "",
        )
        for rec in candidates[:15]
    ]
    if not calls:
        raise XenoCantoError("no recording")
    return calls
