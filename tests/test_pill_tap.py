import asyncio
import json
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

# Stub out homeassistant modules before importing our code
def _make_module(name):
    mod = ModuleType(name)
    sys.modules[name] = mod
    return mod

sys.modules.setdefault("websockets", _make_module("websockets"))
sys.modules.setdefault("voluptuous", _make_module("voluptuous"))

_ha = _make_module("homeassistant")
_ha_core = _make_module("homeassistant.core")
_ha_core.HomeAssistant = MagicMock
_ha_core.ServiceCall = MagicMock
_ha_core.ServiceResponse = MagicMock
_ha_core.SupportsResponse = MagicMock
_ha_core.callback = lambda f: f
_ha_exceptions = _make_module("homeassistant.exceptions")
_ha_exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
_ha_helpers = _make_module("homeassistant.helpers")
_ha_aiohttp = _make_module("homeassistant.helpers.aiohttp_client")
_ha_aiohttp.async_get_clientsession = MagicMock()
_ha_event = _make_module("homeassistant.helpers.event")
_ha_event.async_track_time_interval = MagicMock()
_ha_event.async_call_later = MagicMock()
_ha_event.async_track_state_change_event = MagicMock()
_ha_dispatcher = _make_module("homeassistant.helpers.dispatcher")
_ha_dispatcher.async_dispatcher_send = MagicMock()
_ha_dispatcher.async_dispatcher_connect = MagicMock()
_ha_storage = _make_module("homeassistant.helpers.storage")
_ha_storage.Store = MagicMock
_ha_entity = _make_module("homeassistant.helpers.entity")
_ha_entity.Entity = object
_ha_config_entries = _make_module("homeassistant.config_entries")
_ha_config_entries.ConfigEntry = MagicMock
_ha_util = _make_module("homeassistant.util")
_ha_util_dt = _make_module("homeassistant.util.dt")
from datetime import datetime, timezone
_ha_util_dt.now = lambda: datetime.now(tz=timezone.utc)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.ha_smart_display import DeviceConnection
from custom_components.ha_smart_display.const import DOMAIN


class FakeWebSocket:
    """Async-iterable stand-in for a websockets connection."""

    def __init__(self, messages):
        self._messages = messages

    def __aiter__(self):
        async def gen():
            for m in self._messages:
                yield m
        return gen()


def _make_connection():
    """Build a DeviceConnection without running its heavy __init__."""
    conn = object.__new__(DeviceConnection)
    conn._hass = MagicMock()
    conn._device_id = "echo_show_kitchen"
    return conn


def test_pill_tap_fires_bus_event():
    conn = _make_connection()
    ws = FakeWebSocket([json.dumps({
        "type": "event",
        "event": "pill_tap",
        "pill_id": "front_door",
    })])

    asyncio.run(conn._listen(ws))

    conn._hass.bus.async_fire.assert_called_once_with(
        f"{DOMAIN}_pill_tap",
        {"device_id": "echo_show_kitchen", "pill_id": "front_door"},
    )


def test_pill_tap_without_pill_id_fires_with_none():
    conn = _make_connection()
    ws = FakeWebSocket([json.dumps({
        "type": "event",
        "event": "pill_tap",
    })])

    asyncio.run(conn._listen(ws))

    conn._hass.bus.async_fire.assert_called_once_with(
        f"{DOMAIN}_pill_tap",
        {"device_id": "echo_show_kitchen", "pill_id": None},
    )


def test_unknown_event_does_not_fire_pill_tap():
    conn = _make_connection()
    ws = FakeWebSocket([json.dumps({
        "type": "event",
        "event": "something_else",
    })])

    asyncio.run(conn._listen(ws))

    for call in conn._hass.bus.async_fire.call_args_list:
        assert call.args[0] != f"{DOMAIN}_pill_tap"
