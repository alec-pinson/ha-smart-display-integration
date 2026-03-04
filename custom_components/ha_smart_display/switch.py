from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_base import HaSmartDisplayEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities([
        DoNotDisturbSwitch(hass, entry),
        ScreenOnSwitch(hass, entry),
        AmbientActiveSwitch(hass, entry),
        AlarmSoundingSwitch(hass, entry),
    ])


class DoNotDisturbSwitch(HaSmartDisplayEntity, SwitchEntity):
    _attr_name = "Do Not Disturb"
    _attr_icon = "mdi:do-not-disturb"

    @property
    def entity_description_key(self):
        return "do_not_disturb"

    @property
    def is_on(self):
        return self._current_state().get("do_not_disturb", False)

    def _handle_state_update(self, payload):
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        self._send_command({"do_not_disturb": True})

    async def async_turn_off(self, **kwargs):
        self._send_command({"do_not_disturb": False})


class ScreenOnSwitch(HaSmartDisplayEntity, SwitchEntity):
    _attr_name = "Screen"
    _attr_icon = "mdi:monitor"

    @property
    def entity_description_key(self):
        return "screen_on"

    @property
    def is_on(self):
        return self._current_state().get("screen_on", True)

    def _handle_state_update(self, payload):
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        self._send_command({"screen_on": True})

    async def async_turn_off(self, **kwargs):
        self._send_command({"screen_on": False})


class AmbientActiveSwitch(HaSmartDisplayEntity, SwitchEntity):
    _attr_name = "Ambient"
    _attr_icon = "mdi:weather-night"

    @property
    def entity_description_key(self):
        return "ambient_active"

    @property
    def is_on(self):
        return self._current_state().get("ambient_active", False)

    def _handle_state_update(self, payload):
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        self._send_command({"ambient_active": True})

    async def async_turn_off(self, **kwargs):
        self._send_command({"ambient_active": False})


class AlarmSoundingSwitch(HaSmartDisplayEntity, SwitchEntity):
    _attr_name = "Alarm"
    _attr_icon = "mdi:alarm-bell"
    _is_on: bool = False

    @property
    def entity_description_key(self):
        return "alarm_sounding"

    @property
    def is_on(self):
        return self._is_on

    def _handle_state_update(self, payload):
        pass  # state is driven by HA, not reported by device

    async def async_turn_on(self, **kwargs):
        self._is_on = True
        self.async_write_ha_state()
        self._send_command({"alarm_sounding": True})

    async def async_turn_off(self, **kwargs):
        self._is_on = False
        self.async_write_ha_state()
        self._send_command({"alarm_sounding": False})
