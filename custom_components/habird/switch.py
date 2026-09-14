"""Switch entities for the BirdNET-Go Audubon Clock integration.

Two switches, both meant to let the chime be run and tested with no card
or dashboard involved at all:
  - "Chime enabled": turns the automatic on-the-hour cast on/off.
  - "Play now": a manual trigger - turning it on casts the CURRENT hour's
    bird call immediately; turning it off (or toggling again while it's on)
    stops playback. Its own state reflects whether a chime is in progress,
    so it's also the answer to "is a chime currently playing?".
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .audubon_clock import AudubonClock
from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    clock: AudubonClock = data["clock"]
    device_info: DeviceInfo = data["device_info"]
    async_add_entities(
        [
            AudubonClockEnabledSwitch(clock, entry, device_info),
            AudubonClockPlayNowSwitch(clock, entry, device_info),
        ]
    )


class _BaseSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, clock: AudubonClock, entry: ConfigEntry, device_info: DeviceInfo, key: str, name: str) -> None:
        self._clock = clock
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        self._clock.add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        self._clock.remove_listener(self.async_write_ha_state)


class AudubonClockEnabledSwitch(_BaseSwitch):
    """Enables/disables the automatic on-the-hour chime."""

    _attr_icon = "mdi:bell-ring-outline"

    def __init__(self, clock: AudubonClock, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        super().__init__(clock, entry, device_info, "chime_enabled", "Chime enabled")

    @property
    def is_on(self) -> bool:
        return self._clock.enabled

    async def async_turn_on(self, **kwargs) -> None:
        await self._clock.async_set_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._clock.async_set_enabled(False)


class AudubonClockPlayNowSwitch(_BaseSwitch):
    """On: cast the current hour's call now. Off: stop playback."""

    _attr_icon = "mdi:volume-high"

    def __init__(self, clock: AudubonClock, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        super().__init__(clock, entry, device_info, "play_now", "Play now")

    @property
    def is_on(self) -> bool:
        return self._clock.is_playing

    async def async_turn_on(self, **kwargs) -> None:
        await self._clock.async_play_now()

    async def async_turn_off(self, **kwargs) -> None:
        await self._clock.async_stop_playback()
