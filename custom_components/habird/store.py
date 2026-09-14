"""Persistence for the Audubon clock's per-position bird/call assignment and
the chime-enabled flag.

Replaces apt.js's per-browser `localStorage['bird:clockAssign']` (apt.js
line 6386) with Home Assistant's Store helper, keyed per config entry - the
assignment (and the hysteresis incumbents it seeds) is now durable and
shared, instead of living in one browser. `chime_enabled` persists here too
(rather than relying on entity state restore) so the scheduler's own hourly
tick can check it without depending on the switch entity having been added.
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1


class AssignmentStore:
    """Wraps a Store holding positions, per-position entries, and settings."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry_id}_assignment")
        self._data: dict[str, Any] = {}

    async def async_load(self) -> None:
        self._data = await self._store.async_load() or {}

    @property
    def positions(self) -> int:
        return int(self._data.get("positions", 12))

    @property
    def entries(self) -> dict[int, dict[str, Any]]:
        """{position: {sci, common_name, source, dim, art_url, audio_url,
        audio_page, audio_recordist, audio_license, audio_type,
        audio_quality}}."""
        raw = self._data.get("entries") or {}
        return {int(pos): info for pos, info in raw.items()}

    @property
    def chime_enabled(self) -> bool:
        return bool(self._data.get("chime_enabled", True))

    async def async_save_entries(self, positions: int, entries: dict[int, dict[str, Any]]) -> None:
        self._data = {
            **self._data,
            "positions": positions,
            "entries": {str(pos): info for pos, info in entries.items()},
        }
        await self._store.async_save(self._data)

    async def async_save_enabled(self, enabled: bool) -> None:
        self._data = {**self._data, "chime_enabled": enabled}
        await self._store.async_save(self._data)
