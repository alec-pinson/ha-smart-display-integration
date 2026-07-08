import sys
import os
from types import ModuleType
from unittest.mock import MagicMock

# Stub third-party + homeassistant modules imported by __init__.py at import time.
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
_make_module("homeassistant.helpers")
_ha_aiohttp = _make_module("homeassistant.helpers.aiohttp_client")
_ha_aiohttp.async_get_clientsession = MagicMock()
_ha_event = _make_module("homeassistant.helpers.event")
_ha_event.async_track_time_interval = MagicMock()
_ha_event.async_call_later = MagicMock()
_ha_event.async_track_state_change_event = MagicMock()
_ha_dispatcher = _make_module("homeassistant.helpers.dispatcher")
_ha_dispatcher.async_dispatcher_send = MagicMock()
_ha_storage = _make_module("homeassistant.helpers.storage")
_ha_storage.Store = MagicMock
_ha_config_entries = _make_module("homeassistant.config_entries")
_ha_config_entries.ConfigEntry = MagicMock
_ha_util = _make_module("homeassistant.util")
_ha_util_dt = _make_module("homeassistant.util.dt")
from datetime import datetime, timezone
_ha_util_dt.now = lambda: datetime.now(tz=timezone.utc)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.ha_smart_display import build_hello


def test_build_hello_includes_type_id_and_name():
    msg = build_hello("inst-123", "Home")
    assert msg == {"type": "hello", "instance_id": "inst-123", "name": "Home"}


def test_build_hello_includes_host_when_given():
    msg = build_hello("inst-123", "Home-Test", host="192.168.1.42")
    assert msg["host"] == "192.168.1.42"


def test_build_hello_omits_empty_host():
    msg = build_hello("inst-123", "Home", host="")
    assert "host" not in msg
