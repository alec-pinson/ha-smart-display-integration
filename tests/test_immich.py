"""Tests for ImmichProvider.

Immich v3.0.0 removed the `assets` property from `AlbumResponseDto`, so
`GET /api/albums/{id}` no longer carries the album's photos. Album assets now
come from `POST /api/search/random`; the album endpoint is still used for the
album name, which drives the slideshow caption.
"""
import asyncio
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

from custom_components.ha_smart_display import ImmichProvider
from custom_components.ha_smart_display.const import IMMICH_RECENT_PHOTOS_ID

URL = "https://immich.example.com"
API_KEY = "secret-key"
ALBUM_ID = "0f7d1a2b-3c4d-4e5f-8a9b-0c1d2e3f4a5b"


# --------------------------------------------------------------------------
# Fake aiohttp
# --------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Records requests and replays canned responses keyed by (method, path)."""

    def __init__(self, routes, headers=None):
        self._routes = routes
        self.headers = headers or {}
        self.requests = []

    def _respond(self, method, url, **kwargs):
        path = url[len(URL):] if url.startswith(URL) else url
        self.requests.append({"method": method, "path": path, **kwargs})
        status, payload = self._routes.get((method, path), (404, None))
        return FakeResponse(status, payload)

    def get(self, url, **kwargs):
        return self._respond("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._respond("POST", url, **kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _install_fake_aiohttp(routes):
    """Replace the aiohttp module fetch_photos imports. Returns the session."""
    session = FakeSession(routes)
    mod = ModuleType("aiohttp")
    mod.ClientTimeout = lambda **kwargs: kwargs

    def _client_session(headers=None):
        session.headers = headers or {}
        return session

    mod.ClientSession = _client_session
    sys.modules["aiohttp"] = mod
    return session


def _asset(asset_id, city=None, country=None, taken="2024-06-15T10:30:00.000Z"):
    return {
        "id": asset_id,
        "type": "IMAGE",
        "exifInfo": {"city": city, "country": country, "dateTimeOriginal": taken},
    }


def _provider(album_ids=None, batch_size=30):
    return ImmichProvider(URL, API_KEY, album_ids or [ALBUM_ID], batch_size)


def _search_request(session):
    return next(r for r in session.requests if r["path"] == "/api/search/random")


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def test_album_photos_are_fetched_from_search_random():
    """v3 albums no longer embed assets, so photos must come from search."""
    session = _install_fake_aiohttp({
        ("GET", f"/api/albums/{ALBUM_ID}"): (200, {"albumName": "Holidays"}),
        ("POST", "/api/search/random"): (200, [_asset("asset-1"), _asset("asset-2")]),
    })

    photos = asyncio.run(_provider().fetch_photos())

    assert {p["url"] for p in photos} == {
        f"{URL}/api/assets/asset-1/thumbnail?size=preview",
        f"{URL}/api/assets/asset-2/thumbnail?size=preview",
    }
    assert session is not None


def test_search_random_is_scoped_to_the_configured_album():
    session = _install_fake_aiohttp({
        ("GET", f"/api/albums/{ALBUM_ID}"): (200, {"albumName": "Holidays"}),
        ("POST", "/api/search/random"): (200, [_asset("asset-1")]),
    })

    asyncio.run(_provider().fetch_photos())

    assert _search_request(session)["json"]["albumIds"] == [ALBUM_ID]


def test_search_random_requests_images_with_exif():
    """EXIF drives the location/date caption, and videos must not be shown."""
    session = _install_fake_aiohttp({
        ("GET", f"/api/albums/{ALBUM_ID}"): (200, {"albumName": "Holidays"}),
        ("POST", "/api/search/random"): (200, [_asset("asset-1")]),
    })

    asyncio.run(_provider().fetch_photos())

    body = _search_request(session)["json"]
    assert body["type"] == "IMAGE"
    assert body["withExif"] is True


def test_search_random_excludes_archived_photos():
    """v3 defaults to any visibility, which would leak archived photos in."""
    session = _install_fake_aiohttp({
        ("GET", f"/api/albums/{ALBUM_ID}"): (200, {"albumName": "Holidays"}),
        ("POST", "/api/search/random"): (200, [_asset("asset-1")]),
    })

    asyncio.run(_provider().fetch_photos())

    assert _search_request(session)["json"]["visibility"] == "timeline"


def test_batch_size_above_the_api_maximum_is_clamped():
    """Immich rejects size > 1000, which would fail the whole request."""
    session = _install_fake_aiohttp({
        ("GET", f"/api/albums/{ALBUM_ID}"): (200, {"albumName": "Holidays"}),
        ("POST", "/api/search/random"): (200, [_asset("asset-1")]),
    })

    asyncio.run(_provider(batch_size=5000).fetch_photos())

    assert _search_request(session)["json"]["size"] == 1000


def test_album_name_and_exif_populate_the_caption():
    _install_fake_aiohttp({
        ("GET", f"/api/albums/{ALBUM_ID}"): (200, {"albumName": "Holidays"}),
        ("POST", "/api/search/random"): (200, [_asset("asset-1", city="Porto")]),
    })

    photos = asyncio.run(_provider().fetch_photos())

    assert photos[0]["album"] == "Holidays"
    assert photos[0]["location"] == "Porto"
    assert photos[0]["date"] == "June 2024"


def test_photos_still_returned_when_the_album_name_lookup_fails():
    """The name is cosmetic — losing it must not blank the slideshow."""
    _install_fake_aiohttp({
        ("GET", f"/api/albums/{ALBUM_ID}"): (500, None),
        ("POST", "/api/search/random"): (200, [_asset("asset-1")]),
    })

    photos = asyncio.run(_provider().fetch_photos())

    assert len(photos) == 1
    assert photos[0]["album"] is None


def test_recent_photos_searches_the_whole_library():
    """The '__recent__' pseudo-album is not a real album ID."""
    session = _install_fake_aiohttp({
        ("POST", "/api/search/random"): (200, [_asset("asset-1")]),
    })

    photos = asyncio.run(_provider(album_ids=[IMMICH_RECENT_PHOTOS_ID]).fetch_photos())

    assert len(photos) == 1
    body = _search_request(session)["json"]
    assert "albumIds" not in body
    assert not any(IMMICH_RECENT_PHOTOS_ID in r["path"] for r in session.requests)


def test_returned_photos_are_capped_at_the_batch_size():
    _install_fake_aiohttp({
        ("GET", f"/api/albums/{ALBUM_ID}"): (200, {"albumName": "Holidays"}),
        ("POST", "/api/search/random"): (
            200, [_asset(f"asset-{i}") for i in range(10)],
        ),
    })

    photos = asyncio.run(_provider(batch_size=3).fetch_photos())

    assert len(photos) == 3


def test_search_failure_returns_no_photos_without_raising():
    _install_fake_aiohttp({
        ("GET", f"/api/albums/{ALBUM_ID}"): (200, {"albumName": "Holidays"}),
        ("POST", "/api/search/random"): (401, None),
    })

    assert asyncio.run(_provider().fetch_photos()) == []


def test_one_failing_album_does_not_lose_the_others():
    good_album = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
    session = _install_fake_aiohttp({
        ("GET", f"/api/albums/{ALBUM_ID}"): (200, {"albumName": "Holidays"}),
        ("GET", f"/api/albums/{good_album}"): (200, {"albumName": "Family"}),
    })
    # search succeeds only for the second album
    routes = session._routes

    def _post(url, **kwargs):
        path = url[len(URL):]
        session.requests.append({"method": "POST", "path": path, **kwargs})
        if kwargs["json"].get("albumIds") == [good_album]:
            return FakeResponse(200, [_asset("asset-1")])
        return FakeResponse(500, None)

    session.post = _post
    assert routes is not None

    photos = asyncio.run(_provider(album_ids=[ALBUM_ID, good_album]).fetch_photos())

    assert len(photos) == 1
    assert photos[0]["album"] == "Family"


def test_api_key_is_sent_on_every_request():
    session = _install_fake_aiohttp({
        ("GET", f"/api/albums/{ALBUM_ID}"): (200, {"albumName": "Holidays"}),
        ("POST", "/api/search/random"): (200, [_asset("asset-1")]),
    })

    asyncio.run(_provider().fetch_photos())

    assert session.headers["x-api-key"] == API_KEY
