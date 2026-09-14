"""The BirdNET-Go Audubon Clock integration.

Runs the Audubon-clock hour->bird assignment and its on-the-hour chime cast
entirely inside Home Assistant, independent of the Bird Card dashboard - the
whole point being that the chime can be set up on its own, with no card
installed at all. See homeassistant/www/apt.js's `initAnalogDial` for the
browser-only version this ports from (unchanged by this integration; see
the project README for how the two relate).
"""
from __future__ import annotations

import json
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo

from .api import BirdNetGoClient
from .audubon_clock import AudubonClock
from .const import (
    CONF_API_TOKEN,
    CONF_CLOCK_HOURS,
    CONF_HOUR_PINS,
    CONF_MAX_SECONDS,
    CONF_MEDIA_PLAYERS,
    CONF_QUIET_HOURS,
    CONF_REASSIGN,
    CONF_URL,
    CONF_VERIFY_SSL,
    CONF_WINDOW_DAYS,
    CONF_XENO_CANTO_KEY,
    DEFAULT_MAX_SECONDS,
    DEFAULT_WINDOW_DAYS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "switch"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, True))
    client = BirdNetGoClient(
        session,
        entry.data[CONF_URL],
        entry.data.get(CONF_API_TOKEN) or None,
        entry.data.get(CONF_VERIFY_SSL, True),
    )

    pins: dict[int, str] = {}
    raw_pins = (entry.options.get(CONF_HOUR_PINS) or "").strip()
    if raw_pins:
        try:
            pins = {int(pos): sci for pos, sci in json.loads(raw_pins).items()}
        except (ValueError, AttributeError, TypeError):
            _LOGGER.warning("Ignoring invalid hour_pins option for %s", entry.title)

    clock = AudubonClock(
        hass,
        entry.entry_id,
        client,
        media_players=list(entry.options.get(CONF_MEDIA_PLAYERS) or []),
        xeno_canto_key=entry.options.get(CONF_XENO_CANTO_KEY) or None,
        quiet_hours=entry.options.get(CONF_QUIET_HOURS),
        max_seconds=int(entry.options.get(CONF_MAX_SECONDS, DEFAULT_MAX_SECONDS)),
        positions=int(entry.options.get(CONF_CLOCK_HOURS, 12)),
        window_days=int(entry.options.get(CONF_WINDOW_DAYS, DEFAULT_WINDOW_DAYS)),
        reassign=entry.options.get(CONF_REASSIGN, "daily"),
        pins=pins,
    )
    await clock.async_start()

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="BirdNET-Go",
        configuration_url=entry.data[CONF_URL],
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"client": client, "clock": clock, "device_info": device_info}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data:
            data["clock"].async_unload()
    return unload_ok
