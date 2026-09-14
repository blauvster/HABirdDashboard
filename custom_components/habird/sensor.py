"""Sensor entities for the BirdNET-Go Audubon Clock integration.

One sensor per clock position (12 or 24, per the `clock_hours` option) -
what the card's analog dial shows on its rim, but as an HA entity usable
with no card/dashboard at all: the bird assigned to that hour, its cached
artwork (`art_url`), and the cached chime file that hour will play
(`audio_url`) plus the licensing attribution Xeno-Canto's CC license
requires (`audio_recordist`/`audio_license`/`audio_page`), all as
attributes on the one entity.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .assignment import hours_for_position
from .audubon_clock import AudubonClock
from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    clock: AudubonClock = data["clock"]
    device_info: DeviceInfo = data["device_info"]
    async_add_entities(
        [AudubonClockPositionSensor(clock, entry, device_info, pos) for pos in range(1, clock.positions + 1)]
    )


class AudubonClockPositionSensor(SensorEntity):
    """The bird assigned to one clock position, and its art/chime file."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:bird"

    def __init__(self, clock: AudubonClock, entry: ConfigEntry, device_info: DeviceInfo, position: int) -> None:
        self._clock = clock
        self._position = position
        self._attr_name = f"Position {position}"
        self._attr_unique_id = f"{entry.entry_id}_position_{position}"
        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        self._clock.add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        self._clock.remove_listener(self.async_write_ha_state)

    @property
    def _entry(self) -> dict:
        return self._clock.entries.get(self._position) or {}

    @property
    def native_value(self) -> str | None:
        return self._entry.get("common_name")

    @property
    def extra_state_attributes(self) -> dict:
        info = self._entry
        return {
            "scientific_name": info.get("sci"),
            "source": info.get("source"),
            "dim": info.get("dim"),
            "hours": hours_for_position(self._position, self._clock.positions),
            "art_url": info.get("art_url"),
            "audio_url": info.get("audio_url"),
            "audio_page": info.get("audio_page"),
            "audio_recordist": info.get("audio_recordist"),
            "audio_license": info.get("audio_license"),
            "audio_type": info.get("audio_type"),
            "audio_quality": info.get("audio_quality"),
        }
