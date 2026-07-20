import asyncio
import base64
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

DEVICE_ID = "echo_show_kitchen"
PNG = b"\x89PNG\r\n\x1a\n fake image bytes"


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
    conn._device_id = DEVICE_ID
    # MagicMock does not support subscripting, so give hass.data a real dict.
    conn._hass.data = {DOMAIN: {DEVICE_ID: {}}}
    return conn


def _slot(conn):
    return conn._hass.data[DOMAIN][DEVICE_ID]


def test_screenshot_is_stored_with_timestamp():
    conn = _make_connection()
    ws = FakeWebSocket([json.dumps({
        "type": "event",
        "event": "screenshot",
        "data": base64.b64encode(PNG).decode(),
    })])

    asyncio.run(conn._listen(ws))

    assert _slot(conn)["screenshot"] == PNG
    assert _slot(conn)["screenshot_at"] is not None


def test_screenshot_error_keeps_previous_image():
    conn = _make_connection()
    _slot(conn)["screenshot"] = PNG
    ws = FakeWebSocket([json.dumps({
        "type": "event",
        "event": "screenshot",
        "error": "Capture failed: no image produced",
    })])

    asyncio.run(conn._listen(ws))

    assert _slot(conn)["screenshot"] == PNG


def test_undecodable_screenshot_keeps_previous_image():
    conn = _make_connection()
    _slot(conn)["screenshot"] = PNG
    ws = FakeWebSocket([json.dumps({
        "type": "event",
        "event": "screenshot",
        "data": "!!!not base64!!!",
    })])

    asyncio.run(conn._listen(ws))

    assert _slot(conn)["screenshot"] == PNG


def test_screenshot_sets_waiting_event():
    conn = _make_connection()

    async def run():
        waiter = asyncio.Event()
        _slot(conn)["screenshot_event"] = waiter
        ws = FakeWebSocket([json.dumps({
            "type": "event",
            "event": "screenshot",
            "data": base64.b64encode(PNG).decode(),
        })])
        await conn._listen(ws)
        return waiter.is_set()

    assert asyncio.run(run()) is True


def test_screenshot_dispatch_does_not_blank_device_state():
    """Subscribers (e.g. media_player) read the payload unconditionally, so
    dispatching an empty dict would wipe their state on every capture."""
    from custom_components import ha_smart_display

    conn = _make_connection()
    state = {"media_state": "playing", "media_track": {"title": "Song"}}
    _slot(conn)["state"] = state
    ws = FakeWebSocket([json.dumps({
        "type": "event",
        "event": "screenshot",
        "data": base64.b64encode(PNG).decode(),
    })])

    ha_smart_display.async_dispatcher_send.reset_mock()
    asyncio.run(conn._listen(ws))

    assert ha_smart_display.async_dispatcher_send.call_count == 1
    assert ha_smart_display.async_dispatcher_send.call_args.args[2] == state


def test_screenshot_error_also_releases_waiter():
    """A failed capture must not leave the service hanging until timeout."""
    conn = _make_connection()

    async def run():
        waiter = asyncio.Event()
        _slot(conn)["screenshot_event"] = waiter
        ws = FakeWebSocket([json.dumps({
            "type": "event",
            "event": "screenshot",
            "error": "Capture failed",
        })])
        await conn._listen(ws)
        return waiter.is_set()

    assert asyncio.run(run()) is True
