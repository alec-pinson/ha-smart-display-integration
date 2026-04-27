import asyncio
import sys
import os
from types import ModuleType
from unittest.mock import MagicMock

# Stub out homeassistant modules before importing our code
def _make_module(name):
    mod = ModuleType(name)
    sys.modules[name] = mod
    return mod

# Third-party stubs needed by __init__.py / entity_base.py etc.
sys.modules.setdefault("websockets", _make_module("websockets"))
sys.modules.setdefault("voluptuous", _make_module("voluptuous"))

_ha = _make_module("homeassistant")
_ha_core = _make_module("homeassistant.core")
_ha_core.HomeAssistant = MagicMock
_ha_core.ServiceCall = MagicMock
_ha_core.ServiceResponse = MagicMock
_ha_core.SupportsResponse = MagicMock
_ha_core.callback = lambda f: f
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

from unittest.mock import AsyncMock
from custom_components.ha_smart_display.updater import GitHubUpdater


def run(coro):
    return asyncio.run(coro)


def _make_session(status, json_body):
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_body)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=resp)
    return session


def test_parses_version_and_url():
    hass = MagicMock()
    updater = GitHubUpdater(hass)
    session = _make_session(200, {
        "tag_name": "v1.2.3",
        "html_url": "https://github.com/alec-pinson/ha-smart-display-app/releases/tag/v1.2.3",
        "assets": [{"name": "app-release.apk", "browser_download_url": "https://example.com/app-release.apk"}],
    })
    run(updater.async_check(session=session))
    assert updater.latest_version == "1.2.3"
    assert updater.latest_apk_url == "https://example.com/app-release.apk"
    assert updater.release_html_url == "https://github.com/alec-pinson/ha-smart-display-app/releases/tag/v1.2.3"


def test_retains_cached_version_on_api_failure():
    hass = MagicMock()
    updater = GitHubUpdater(hass)
    updater.latest_version = "1.0.0"
    updater.latest_apk_url = "https://example.com/app-release.apk"
    session = _make_session(500, {})
    run(updater.async_check(session=session))
    assert updater.latest_version == "1.0.0"
    assert updater.latest_apk_url == "https://example.com/app-release.apk"


def test_strips_v_prefix_from_tag():
    hass = MagicMock()
    updater = GitHubUpdater(hass)
    session = _make_session(200, {
        "tag_name": "v2.0.0",
        "html_url": "https://example.com",
        "assets": [{"name": "app-release.apk", "browser_download_url": "https://example.com/app-release.apk"}],
    })
    run(updater.async_check(session=session))
    assert updater.latest_version == "2.0.0"


def test_handles_tag_without_v_prefix():
    hass = MagicMock()
    updater = GitHubUpdater(hass)
    session = _make_session(200, {
        "tag_name": "1.0.0",
        "html_url": "https://example.com",
        "assets": [{"name": "app-release.apk", "browser_download_url": "https://example.com/app-release.apk"}],
    })
    run(updater.async_check(session=session))
    assert updater.latest_version == "1.0.0"


def test_no_apk_asset_leaves_url_none():
    hass = MagicMock()
    updater = GitHubUpdater(hass)
    session = _make_session(200, {
        "tag_name": "v1.0.0",
        "html_url": "https://example.com",
        "assets": [{"name": "source.zip", "browser_download_url": "https://example.com/source.zip"}],
    })
    run(updater.async_check(session=session))
    assert updater.latest_version == "1.0.0"
    assert updater.latest_apk_url is None
