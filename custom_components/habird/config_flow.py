"""Config flow for the BirdNET-Go Audubon Clock integration."""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BirdNetGoClient, BirdNetGoError
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


class BirdNetConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a BirdNET-Go Audubon Clock, pointed at a BirdNET-Go server."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            session = async_get_clientsession(self.hass, verify_ssl=user_input[CONF_VERIFY_SSL])
            client = BirdNetGoClient(
                session, url, user_input.get(CONF_API_TOKEN) or None, user_input[CONF_VERIFY_SSL]
            )
            try:
                await client.species_summary()
            except BirdNetGoError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                host = urlparse(url).netloc or url
                data = dict(user_input)
                data[CONF_URL] = url
                return self.async_create_entry(title=f"BirdNET-Go Audubon Clock ({host})", data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default="http://homeassistant.local:8080"): str,
                vol.Required(CONF_VERIFY_SSL, default=True): bool,
                vol.Optional(CONF_API_TOKEN): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BirdNetOptionsFlow(config_entry)


class BirdNetOptionsFlow(OptionsFlow):
    """Chime + Audubon-clock options, editable after setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        errors: dict[str, str] = {}
        if user_input is not None:
            pins_raw = (user_input.get(CONF_HOUR_PINS) or "").strip()
            if pins_raw:
                try:
                    parsed = json.loads(pins_raw)
                    if not isinstance(parsed, dict):
                        raise ValueError("hour_pins must be a JSON object")
                except (ValueError, TypeError):
                    errors[CONF_HOUR_PINS] = "invalid_pins"
            if not errors:
                return self.async_create_entry(title="", data=user_input)

        options = self._entry.options
        schema = vol.Schema(
            {
                vol.Optional(CONF_XENO_CANTO_KEY, default=options.get(CONF_XENO_CANTO_KEY, "")): str,
                vol.Optional(
                    CONF_MEDIA_PLAYERS, default=options.get(CONF_MEDIA_PLAYERS, [])
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="media_player", multiple=True)),
                vol.Optional(CONF_QUIET_HOURS, default=options.get(CONF_QUIET_HOURS, "")): str,
                vol.Optional(
                    CONF_MAX_SECONDS, default=options.get(CONF_MAX_SECONDS, DEFAULT_MAX_SECONDS)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=300, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_CLOCK_HOURS, default=str(options.get(CONF_CLOCK_HOURS, 12))
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=["12", "24"], mode=selector.SelectSelectorMode.DROPDOWN)
                ),
                vol.Optional(
                    CONF_WINDOW_DAYS, default=options.get(CONF_WINDOW_DAYS, DEFAULT_WINDOW_DAYS)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=365, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_REASSIGN, default=options.get(CONF_REASSIGN, "daily")): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["daily", "hourly", "manual"], mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Optional(CONF_HOUR_PINS, default=options.get(CONF_HOUR_PINS, "")): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
