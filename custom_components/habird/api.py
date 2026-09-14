"""Async client for BirdNET-Go's public REST API v2.

Mirrors the subset of endpoints the card's own adapter already calls from
the browser (homeassistant/www/apt.js, the `bg*` functions) - same paths,
same query params - so this integration's server-side polling matches the
card's behavior exactly.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import aiohttp

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)


class BirdNetGoError(Exception):
    """Raised when a BirdNET-Go request fails."""


class BirdNetGoClient:
    """Thin async wrapper around BirdNET-Go's `/api/v2` routes."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        api_token: str | None = None,
        verify_ssl: bool = True,
    ) -> None:
        self._session = session
        self._base = base_url.rstrip("/")
        self._token = api_token
        # aiohttp's per-request `ssl` kwarg: False disables verification,
        # None (default) uses the session's own verified context.
        self._ssl: bool | None = None if verify_ssl else False

    def _headers(self) -> dict[str, str]:
        # BirdNET-Go's "Private Mode" locks the whole v2 API behind a
        # personal token - see apt.js's bgFetch (apt.js line ~191) for the
        # same header, added only for BirdNET-Go requests.
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self._base}/api/v2{path}"
        try:
            async with self._session.get(
                url,
                headers=self._headers(),
                params=params,
                timeout=REQUEST_TIMEOUT,
                ssl=self._ssl,
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise BirdNetGoError(f"{url}: {err}") from err

    @staticmethod
    def _date_str(value: date) -> str:
        return value.strftime("%Y-%m-%d")

    async def species_summary(self, start: date | None = None, end: date | None = None) -> list[dict]:
        """GET /analytics/species/summary - lifelist, or a start/end window."""
        params = None
        if start and end:
            params = {"start_date": self._date_str(start), "end_date": self._date_str(end)}
        result = await self._get("/analytics/species/summary", params)
        return result or []

    async def species_daily(self, day: date) -> list[dict]:
        """GET /analytics/species/daily?date= - one day's per-species hourly buckets."""
        result = await self._get("/analytics/species/daily", {"date": self._date_str(day)})
        return result or []

    async def hourly_batch(self, start: date, end: date, min_confidence: float = 0) -> Any:
        """GET /analytics/time/hourly/batch - species x hour matrix in one call.

        Response shape has drifted across BirdNET-Go builds (and the route
        may not exist on older ones); callers should treat a parse failure
        or error here as "fall back to summing species_daily per day".
        """
        params: dict[str, Any] = {
            "start_date": self._date_str(start),
            "end_date": self._date_str(end),
        }
        if min_confidence:
            params["min_confidence"] = min_confidence
        return await self._get("/analytics/time/hourly/batch", params)
