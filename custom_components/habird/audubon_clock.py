"""The Audubon clock: hour -> bird assignment, resolved reference calls, and
the on-the-hour chime cast - runs entirely inside Home Assistant, via
`async_track_time_change` / `async_track_time_interval`, independent of any
dashboard being open (or even installed).

Port of apt.js's analog-dial code (homeassistant/www/apt.js lines
6360-6486: `recompute()`, the tick loop, `inQuiet`, `playChime`) - the
browser-only version this integration exists to make dashboard-independent.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_change,
    async_track_time_interval,
)
import homeassistant.util.dt as dt_util

from .api import BirdNetGoClient, BirdNetGoError
from .assignment import assign_hours, clock_pos_of_hour
from .cache import async_cache_art, async_cache_audio
from .hourly import fetch_hourly_matrix
from .store import AssignmentStore
from .xeno_canto import ReferenceCall, XenoCantoError, resolve_reference_call

_LOGGER = logging.getLogger(__name__)

QUIET_HOURS_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")


def _parse_quiet_hours(spec: str | None) -> tuple[int, int] | None:
    if not spec:
        return None
    match = QUIET_HOURS_RE.match(spec.strip())
    if not match:
        return None
    start = int(match.group(1)) * 60 + int(match.group(2))
    end = int(match.group(3)) * 60 + int(match.group(4))
    return None if start == end else (start, end)


def _in_quiet_hours(quiet: tuple[int, int] | None, now: datetime) -> bool:
    if quiet is None:
        return False
    start, end = quiet
    minutes = now.hour * 60 + now.minute
    if start < end:
        return start <= minutes < end
    return minutes >= start or minutes < end  # overnight wraparound


class AudubonClock:
    """Owns the hour->bird assignment, resolved calls, and chime playback.

    Entities (sensor.py, switch.py) read `entries`/`enabled`/`is_playing`
    and register via `add_listener` for push updates - there's no
    DataUpdateCoordinator here since nothing polls on a fast cadence
    anymore; state only changes on a recompute (daily/hourly/manual) or an
    explicit play/stop.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        client: BirdNetGoClient,
        *,
        media_players: list[str],
        xeno_canto_key: str | None,
        quiet_hours: str | None,
        max_seconds: int,
        positions: int,
        window_days: int,
        reassign: str,
        pins: dict[int, str],
        min_confidence: float = 0,
    ) -> None:
        self._hass = hass
        self._client = client
        self._media_players = media_players
        self._xeno_canto_key = xeno_canto_key
        self._quiet = _parse_quiet_hours(quiet_hours)
        self._max_seconds = max_seconds
        self.positions = 24 if positions == 24 else 12
        self._window_days = window_days
        self._reassign = (reassign or "daily").lower()
        self._pins = pins
        self._min_confidence = min_confidence
        self._store = AssignmentStore(hass, entry_id)
        self._unsub: list[Callable[[], None]] = []
        self._stop_unsub: Callable[[], None] | None = None
        self._playing = False
        self._listeners: list[Callable[[], None]] = []

    # ---- entity plumbing (push updates, no polling) ----
    def add_listener(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @property
    def entries(self) -> dict[int, dict[str, Any]]:
        """{position: {sci, common_name, source, dim, art_url, audio_url,
        audio_page, audio_recordist, audio_license, audio_type,
        audio_quality}}."""
        return self._store.entries

    @property
    def enabled(self) -> bool:
        return self._store.chime_enabled

    @property
    def is_playing(self) -> bool:
        return self._playing

    # ---- lifecycle ----
    async def async_start(self) -> None:
        await self._store.async_load()
        await self.async_recompute()
        self._unsub.append(async_track_time_change(self._hass, self._on_tick, minute=0, second=0))
        interval = {"hourly": timedelta(hours=1), "manual": None}.get(self._reassign, timedelta(days=1))
        if interval:
            self._unsub.append(async_track_time_interval(self._hass, self._on_recompute_tick, interval))

    @callback
    def async_unload(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()
        if self._stop_unsub:
            self._stop_unsub()
            self._stop_unsub = None

    # ---- assignment ----
    async def _on_recompute_tick(self, _now: datetime) -> None:
        await self.async_recompute()

    async def async_recompute(self) -> None:
        try:
            matrix = await fetch_hourly_matrix(self._client, self._window_days, self._min_confidence)
        except BirdNetGoError as err:
            _LOGGER.debug("Skipping Audubon clock recompute: %s", err)
            return

        # Common names for display - the matrix itself is scientific-name
        # keyed only (matches apt.js's bgHourlyMatrixFromDaily, which
        # doesn't carry common_name either).
        names: dict[str, str] = {}
        try:
            for row in await self._client.species_summary():
                sci = row.get("scientific_name")
                if sci:
                    names[sci] = row.get("common_name") or sci
        except BirdNetGoError:
            pass  # names fall back to the scientific name below

        incumbents = {pos: info["sci"] for pos, info in self.entries.items() if info.get("sci")}
        assignment = assign_hours(matrix, positions=self.positions, pins=self._pins, incumbents=incumbents)

        entries: dict[int, dict[str, Any]] = {}
        for pos, result in assignment.items():
            sci = result.species
            call = await self._resolve_call(sci) if sci else None
            audio_url = await async_cache_audio(self._hass, sci, call) if call else None
            art_url = await async_cache_art(self._hass, sci) if sci else None
            entries[pos] = {
                "sci": sci,
                "common_name": (names.get(sci, sci) if sci else None),
                "source": result.source,
                "dim": result.dim,
                "art_url": art_url,
                "audio_url": audio_url,
                "audio_page": call.page if call else None,
                "audio_recordist": call.recordist if call else None,
                "audio_license": call.license if call else None,
                "audio_type": call.type if call else None,
                "audio_quality": call.quality if call else None,
            }
        await self._store.async_save_entries(self.positions, entries)
        self._notify()

    async def _resolve_call(self, sci: str) -> ReferenceCall | None:
        if not self._xeno_canto_key:
            return None
        session = async_get_clientsession(self._hass)
        try:
            calls = await resolve_reference_call(session, sci, self._xeno_canto_key)
        except XenoCantoError as err:
            _LOGGER.debug("No reference call for %s: %s", sci, err)
            return None
        return calls[0]

    # ---- playback ----
    async def async_set_enabled(self, enabled: bool) -> None:
        await self._store.async_save_enabled(enabled)
        self._notify()

    async def async_play_now(self) -> bool:
        """Cast the current hour's bird call now, to every configured chime
        player at once. Returns whether it started."""
        if not self._media_players:
            _LOGGER.debug("Audubon clock has no chime media players configured")
            return False
        pos = clock_pos_of_hour(dt_util.now().hour, self.positions)
        url = (self.entries.get(pos) or {}).get("audio_url")
        if not url:
            _LOGGER.debug("No resolved call yet for the current hour (position %s)", pos)
            return False
        await self._hass.services.async_call(
            "media_player",
            "play_media",
            {"entity_id": self._media_players, "media_content_id": url, "media_content_type": "music"},
            blocking=False,
        )
        self._playing = True
        self._notify()
        if self._stop_unsub:
            self._stop_unsub()
            self._stop_unsub = None
        if self._max_seconds > 0:
            self._stop_unsub = async_call_later(self._hass, self._max_seconds, self._async_auto_stop)
        return True

    async def async_stop_playback(self) -> None:
        if self._stop_unsub:
            self._stop_unsub()
            self._stop_unsub = None
        if self._media_players:
            await self._hass.services.async_call(
                "media_player", "media_stop", {"entity_id": self._media_players}, blocking=False
            )
        self._playing = False
        self._notify()

    async def _async_auto_stop(self, _now: datetime) -> None:
        self._stop_unsub = None
        await self.async_stop_playback()

    async def _on_tick(self, now: datetime) -> None:
        if not self.enabled or _in_quiet_hours(self._quiet, now):
            return
        await self.async_play_now()
