"""Local caching of Xeno-Canto audio and CDN artwork under `/config/www`.

Both are fetched once and re-served locally afterward - "if it's in the
cache, point to that; if not, download it" - so repeat recomputes (and
every hourly chime) for the same recording/species don't keep hitting
Xeno-Canto or the artwork CDN, and `media_player.play_media` gets a URL
that keeps working even if the upstream host is briefly unreachable later.
Anything under `/config/www` is served by Home Assistant itself at
`/local/...` with no extra setup.

Caching is best-effort: any failure (no HA base URL configured yet, a
download error, a disk error) falls back to the original remote URL rather
than breaking the chime or leaving a position with no data.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .xeno_canto import ReferenceCall

_LOGGER = logging.getLogger(__name__)

# www/community/ is where HACS itself lands frontend resources (e.g.
# www/community/HABirdDashboard/habird-card.js) - putting the cache there
# too, rather than loose in www/, keeps it grouped with the rest of this
# integration's/HACS-managed footprint instead of cluttering www/'s root.
CACHE_DIRNAME = "community/habird_cache"
AUDIO_SUBDIR = "audio"
ART_SUBDIR = "art"

# Same CDN the card falls back to by default - a jsDelivr view of this
# repo's bundled illustrations (homeassistant/card/build.js's
# HABIRD_CDN_ASSETS).
ART_CDN_BASE = "https://cdn.jsdelivr.net/gh/adamoberley/HABirdDashboard@HABirdDashboard/avian/assets/"

DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30)


def slugify(sci: str) -> str:
    """Match apt.js's slugify() exactly - the CDN's filenames depend on it."""
    return re.sub(r"[^a-z0-9]+", "-", sci.lower()).strip("-")


def _cache_root(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("www", CACHE_DIRNAME))


async def _exists(hass: HomeAssistant, path: Path) -> bool:
    return await hass.async_add_executor_job(path.exists)


async def _write(hass: HomeAssistant, path: Path, data: bytes) -> None:
    def _do() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    await hass.async_add_executor_job(_do)


async def _download(hass: HomeAssistant, url: str) -> bytes | None:
    session = async_get_clientsession(hass)
    try:
        async with session.get(url, timeout=DOWNLOAD_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            return await resp.read()
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.debug("Download failed for %s: %s", url, err)
        return None


def _local_url(hass: HomeAssistant, *parts: str) -> str | None:
    # Prefer HA's external URL (reachable from anywhere - the internet, a
    # cloud-connected media_player, another network) so the cached path
    # keeps working for whatever's fetching it; fall back to the internal
    # URL when no external one is configured.
    try:
        base = get_url(hass, prefer_external=True)
    except NoURLAvailableError:
        return None
    return "/".join([base.rstrip("/"), "local", CACHE_DIRNAME, *parts])


async def async_cache_audio(hass: HomeAssistant, sci: str, call: ReferenceCall) -> str:
    """Return a locally-cached URL for `call`, downloading it if needed.

    The cache key includes the Xeno-Canto recording id, so a later
    recompute that resolves a *different* recording for the same species
    caches under a new filename rather than serving stale audio; the same
    recording (the common case) is a pure cache hit.
    """
    if not call.id:
        return call.url  # no stable key to cache under - just play it directly
    # Xeno-Canto recordings are served as mp3 in practice.
    filename = f"{slugify(sci)}-{call.id}.mp3"
    path = _cache_root(hass) / AUDIO_SUBDIR / filename
    if not await _exists(hass, path):
        data = await _download(hass, call.url)
        if data is None:
            return call.url
        try:
            await _write(hass, path, data)
        except OSError as err:
            _LOGGER.debug("Could not cache audio for %s: %s", sci, err)
            return call.url
    return _local_url(hass, AUDIO_SUBDIR, filename) or call.url


async def async_cache_art(hass: HomeAssistant, sci: str) -> str | None:
    """Return a locally-cached URL for the species' artwork, or None.

    Tries the perched illustration first, then the photo-cutout fallback -
    the same 2-step order the card uses before it gives up and hides the
    species entirely (apt.js's `__birdImgErr`). None means the bundled
    library has neither (an uncovered species/region).
    """
    filename = f"{slugify(sci)}.png"
    path = _cache_root(hass) / ART_SUBDIR / filename
    if await _exists(hass, path):
        return _local_url(hass, ART_SUBDIR, filename) or f"{ART_CDN_BASE}illustrations/{filename}"

    for remote in (f"{ART_CDN_BASE}illustrations/{filename}", f"{ART_CDN_BASE}cutouts/{filename}"):
        data = await _download(hass, remote)
        if data is None:
            continue
        try:
            await _write(hass, path, data)
        except OSError as err:
            _LOGGER.debug("Could not cache artwork for %s: %s", sci, err)
            return remote  # still something showable, just not cached
        return _local_url(hass, ART_SUBDIR, filename) or remote
    return None
