import asyncio
import base64
import json
import logging
import random
from datetime import datetime, timedelta

import websockets

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_PORT,
    CONF_WEATHER_ENTITY,
    CONF_PHOTO_URLS,
    CONF_CAMERA_ENTITIES,
    CONF_CLIMATE_ENTITY,
    CONF_TEMPERATURE_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_AUTO_AMBIENT_LUX,
    CONF_MA_MEDIA_PLAYER,
    CONF_IMMICH_URL,
    CONF_IMMICH_API_KEY,
    CONF_IMMICH_ALBUM_IDS,
    CONF_IMMICH_REFRESH_INTERVAL,
    CONF_IMMICH_BATCH_SIZE,
    CONF_SLIDESHOW_INTERVAL,
    CONF_FRIGATE_URL,
    CONF_GO2RTC_URL,
    IMMICH_RECENT_PHOTOS_ID,
    STREAM_TYPE_SNAPSHOT,
    STREAM_TYPES,
    SIGNAL_STATE_UPDATED,
    SIGNAL_AVAILABILITY_UPDATED,
    SERVICE_SET_TIMER,
    SERVICE_DISMISS_TIMER,
    SERVICE_SET_ALARM,
    SERVICE_DISMISS_ALARM,
    SERVICE_SET_PHOTOS,
    SERVICE_SEND_NOTIFICATION,
    SERVICE_OPEN_CAMERA,
    SERVICE_ADD_PILL,
    SERVICE_REMOVE_PILL,
    SERVICE_DISMISS_ALL_PILLS,
    SERVICE_GET_PILLS,
    SERVICE_GET_TIMERS,
    SERVICE_DISMISS_ALL_TIMERS,
    SERVICE_GET_ALARMS,
    SERVICE_DISMISS_ALL_ALARMS,
    SERVICE_CLOSE_CAMERA,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["select", "switch", "number", "button", "sensor", "media_player", "assist_satellite"]


class ImmichProvider:
    """Fetches a shuffled batch of photo thumbnail URLs from Immich albums."""

    def __init__(self, url: str, api_key: str, album_ids: list[str], batch_size: int):
        self._url = url.rstrip("/")
        self._api_key = api_key
        self._album_ids = album_ids
        self._batch_size = batch_size

    @staticmethod
    def _parse_asset_meta(asset: dict, album_name: str | None = None) -> tuple[str | None, str | None]:
        """Extract location and date_display from an Immich asset's EXIF data."""
        exif = asset.get("exifInfo") or {}
        city = exif.get("city") or ""
        country = exif.get("country") or ""
        location = city or country or None
        if album_name and location and location.lower() in album_name.lower():
            location = None
        date_str = (
            (exif.get("dateTimeOriginal") or "").split(".")[0]
            or (asset.get("localDateTime") or "").split(".")[0]
            or (asset.get("fileCreatedAt") or "").split(".")[0]
        )
        date_display = None
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                if album_name and str(dt.year) in album_name:
                    date_display = None
                else:
                    date_display = dt.strftime("%B %Y")
            except Exception:
                pass
        return location, date_display

    async def fetch_photos(self) -> list[dict]:
        """Return a shuffled batch of photo dicts (url, album, location, date) from the configured albums."""
        import aiohttp
        assets: list[dict] = []  # {id, album, location, date}
        try:
            async with aiohttp.ClientSession(headers={"x-api-key": self._api_key}) as session:
                if IMMICH_RECENT_PHOTOS_ID in self._album_ids:
                    try:
                        async with session.get(
                            f"{self._url}/api/assets",
                            params={"size": self._batch_size, "page": 1},
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                for asset in (data if isinstance(data, list) else data.get("assets", [])):
                                    if asset.get("type") == "IMAGE":
                                        location, date_display = self._parse_asset_meta(asset)
                                        assets.append({
                                            "id": asset["id"],
                                            "album": None,
                                            "location": location,
                                            "date": date_display,
                                        })
                    except Exception as e:
                        _LOGGER.debug("ha_smart_display: Immich recent photos fetch failed: %s", e)
                for album_id in self._album_ids:
                    if album_id == IMMICH_RECENT_PHOTOS_ID:
                        continue
                    try:
                        async with session.get(
                            f"{self._url}/api/albums/{album_id}",
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                album_name = data.get("albumName") or data.get("name") or ""
                                for asset in data.get("assets", []):
                                    if asset.get("type") == "IMAGE":
                                        location, date_display = self._parse_asset_meta(asset, album_name)
                                        assets.append({
                                            "id": asset["id"],
                                            "album": album_name or None,
                                            "location": location,
                                            "date": date_display,
                                        })
                    except Exception as e:
                        _LOGGER.debug("ha_smart_display: Immich album %s fetch failed: %s", album_id, e)
        except Exception as e:
            _LOGGER.warning("ha_smart_display: Immich fetch_photos failed: %s", e)
            return []
        random.shuffle(assets)
        batch = assets[: self._batch_size]
        return [
            {
                "url": f"{self._url}/api/assets/{a['id']}/thumbnail?size=preview",
                "album": a["album"],
                "location": a["location"],
                "date": a["date"],
            }
            for a in batch
        ]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    device_id = entry.data[CONF_DEVICE_ID]
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    weather_entity = entry.options.get(CONF_WEATHER_ENTITY) or entry.data.get(CONF_WEATHER_ENTITY)
    photo_urls = _parse_photo_urls(entry.options.get(CONF_PHOTO_URLS, ""))
    camera_entities = entry.options.get(CONF_CAMERA_ENTITIES, [])
    climate_entity = entry.options.get(CONF_CLIMATE_ENTITY) or entry.data.get(CONF_CLIMATE_ENTITY)
    temperature_sensor = entry.options.get(CONF_TEMPERATURE_SENSOR) or None
    humidity_sensor = entry.options.get(CONF_HUMIDITY_SENSOR) or None
    auto_ambient_lux = entry.options.get(CONF_AUTO_AMBIENT_LUX) or None
    ma_media_player = entry.options.get(CONF_MA_MEDIA_PLAYER) or None
    immich_url = entry.options.get(CONF_IMMICH_URL, "")
    immich_api_key = entry.options.get(CONF_IMMICH_API_KEY, "")
    immich_album_ids = entry.options.get(CONF_IMMICH_ALBUM_IDS, [])
    immich_refresh_interval = int(entry.options.get(CONF_IMMICH_REFRESH_INTERVAL, 60))
    immich_batch_size = int(entry.options.get(CONF_IMMICH_BATCH_SIZE, 30))
    slideshow_interval = int(entry.options.get(CONF_SLIDESHOW_INTERVAL, 1)) * 60  # convert minutes → seconds
    frigate_url = (entry.options.get(CONF_FRIGATE_URL) or "").strip().rstrip("/")
    go2rtc_url = (entry.options.get(CONF_GO2RTC_URL) or "").strip().rstrip("/")

    pill_store = Store(hass, 1, f"{DOMAIN}.{device_id}.pills")
    persisted_pills = await pill_store.async_load() or {}

    hass.data.setdefault(DOMAIN, {})[device_id] = {
        "state": {},
        "available": False,
        "connection": None,
        "timers": {},
        "alarms": {},
        "photos": photo_urls,
        "pills": persisted_pills,
        "pill_timers": {},
        "pill_store": pill_store,
        "satellite_entity": None,
    }

    connection = DeviceConnection(hass, entry, device_id, host, port, weather_entity, camera_entities, climate_entity, temperature_sensor, humidity_sensor, auto_ambient_lux, ma_media_player, immich_url, immich_api_key, immich_album_ids, immich_refresh_interval, immich_batch_size, slideshow_interval, frigate_url, go2rtc_url)
    hass.data[DOMAIN][device_id]["connection"] = connection
    entry.async_on_unload(connection.stop)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_create_background_task(
        hass, connection.run(), f"ha_smart_display_{device_id}"
    )

    # Register services
    _register_services(hass)

    # Listen for options updates (weather entity change)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — reconnect with new weather entity."""
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant) -> None:
    import voluptuous as vol
    import homeassistant.helpers.config_validation as cv

    if hass.services.has_service(DOMAIN, SERVICE_SET_TIMER):
        return

    async def handle_set_timer(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        conn = get_connection(hass, device_id)
        if not conn:
            return
        duration = call.data["duration_seconds"]
        ends_at = int(datetime.now().timestamp()) + duration
        timer = {
            "id": call.data["timer_id"],
            "label": call.data.get("label", "Timer"),
            "duration_seconds": duration,
            "ends_at": ends_at,
        }
        hass.data[DOMAIN][device_id]["timers"][timer["id"]] = timer
        now = int(datetime.now().timestamp())
        timers_with_remaining = [
            {**t, "remaining_seconds": max(0, t["ends_at"] - now)}
            for t in hass.data[DOMAIN][device_id]["timers"].values()
        ]
        await conn.send_command({"timers": timers_with_remaining})

    async def handle_dismiss_timer(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        timer_id = call.data["timer_id"]
        conn = get_connection(hass, device_id)
        hass.data[DOMAIN][device_id]["timers"].pop(timer_id, None)
        if conn:
            await conn.send_command({"timers": list(hass.data[DOMAIN][device_id]["timers"].values())})

    async def handle_set_alarm(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        conn = get_connection(hass, device_id)
        if not conn:
            return
        alarm = {
            "id": call.data["alarm_id"],
            "label": call.data.get("label", "Alarm"),
            "time": call.data["time"],  # "HH:MM"
        }
        hass.data[DOMAIN][device_id]["alarms"][alarm["id"]] = alarm
        await conn.send_command({"alarms": list(hass.data[DOMAIN][device_id]["alarms"].values())})

    async def handle_dismiss_alarm(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        alarm_id = call.data["alarm_id"]
        conn = get_connection(hass, device_id)
        hass.data[DOMAIN][device_id]["alarms"].pop(alarm_id, None)
        if conn:
            await conn.send_command({"alarms": list(hass.data[DOMAIN][device_id]["alarms"].values())})

    hass.services.async_register(
        DOMAIN, SERVICE_SET_TIMER, handle_set_timer,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("timer_id"): cv.string,
            vol.Required("duration_seconds"): vol.Coerce(int),
            vol.Optional("label", default="Timer"): cv.string,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISMISS_TIMER, handle_dismiss_timer,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("timer_id"): cv.string,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_ALARM, handle_set_alarm,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("alarm_id"): cv.string,
            vol.Required("time"): cv.string,
            vol.Optional("label", default="Alarm"): cv.string,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISMISS_ALARM, handle_dismiss_alarm,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("alarm_id"): cv.string,
        }),
    )

    async def handle_set_photos(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        urls = call.data.get("urls", [])
        conn = get_connection(hass, device_id)
        hass.data[DOMAIN][device_id]["photos"] = urls
        if conn:
            await conn.send_command({"photos": urls})

    async def handle_send_notification(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        conn = get_connection(hass, device_id)
        if not conn:
            return
        notification = {
            "title": call.data.get("title", ""),
            "message": call.data.get("message", ""),
            "image_url": call.data.get("image_url"),
            "duration": call.data.get("duration", 10),
            "buttons": call.data.get("buttons", []),
            "style": call.data.get("style", "dialog"),
            "tap_action": call.data.get("tap_action"),
            "position": call.data.get("position", "center"),
            "sound": call.data.get("sound", True),
        }
        await conn.send_command({"notification": notification})

    hass.services.async_register(
        DOMAIN, SERVICE_SET_PHOTOS, handle_set_photos,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("urls"): vol.All(cv.ensure_list, [cv.string]),
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_NOTIFICATION, handle_send_notification,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Optional("title", default=""): cv.string,
            vol.Optional("message", default=""): cv.string,
            vol.Optional("image_url"): cv.string,
            vol.Optional("duration", default=10): vol.Coerce(int),
            vol.Optional("buttons", default=[]): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("style", default="dialog"): vol.In(["dialog", "toast", "banner"]),
            vol.Optional("tap_action"): cv.string,
            vol.Optional("position", default="center"): vol.In(["center", "top_left", "top_center", "top_right", "bottom_left", "bottom_center", "bottom_right"]),
            vol.Optional("sound", default=True): cv.boolean,
        }),
    )

    async def handle_open_camera(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        conn = get_connection(hass, device_id)
        if not conn:
            return
        entity_id = call.data["camera_entity"]
        state = hass.states.get(entity_id)
        name = state.attributes.get("friendly_name", entity_id) if state else entity_id
        stream_type = call.data.get("stream_type", STREAM_TYPE_SNAPSHOT)

        # For video stream types, at least one streaming URL must be configured
        if stream_type != STREAM_TYPE_SNAPSHOT and not conn._frigate_url and not conn._go2rtc_url:
            _LOGGER.warning("ha_smart_display: stream_type '%s' requested but no Frigate or go2rtc URL configured — falling back to snapshot", stream_type)
            stream_type = STREAM_TYPE_SNAPSHOT

        conn._focused_camera_stream_type = stream_type
        payload: dict = {"id": entity_id, "name": name, "stream_type": stream_type}
        if stream_type != STREAM_TYPE_SNAPSHOT:
            if conn._frigate_url:
                payload["frigate_url"] = conn._frigate_url
            if conn._go2rtc_url:
                payload["go2rtc_url"] = conn._go2rtc_url
        if "duration" in call.data:
            payload["duration"] = call.data["duration"]
        await conn.send_command({"open_camera": payload})

    hass.services.async_register(
        DOMAIN, SERVICE_OPEN_CAMERA, handle_open_camera,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("camera_entity"): cv.entity_id,
            vol.Optional("stream_type", default=STREAM_TYPE_SNAPSHOT): vol.In(STREAM_TYPES),
            vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        }),
    )

    async def handle_close_camera(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        conn = get_connection(hass, device_id)
        if not conn:
            return
        conn._focused_camera_stream_type = STREAM_TYPE_SNAPSHOT
        await conn.send_command({"close_camera": True})

    hass.services.async_register(
        DOMAIN, SERVICE_CLOSE_CAMERA, handle_close_camera,
        schema=vol.Schema({vol.Required("device_id"): cv.string}),
    )

    _pill_positions = ["under_clock", "top_left", "top_center", "top_right", "center_left", "center", "center_right", "bottom_left", "bottom_center", "bottom_right"]
    _pill_icons = ["door", "motion", "warning", "info", "check", "alert", "camera", "lock", "temperature", "person"]
    _device_id_schema = vol.Schema({vol.Required("device_id"): cv.string})

    def _cancel_pill_timer(device_id: str, pill_id: str) -> None:
        cancel = hass.data[DOMAIN][device_id]["pill_timers"].pop(pill_id, None)
        if cancel:
            cancel()

    def _cancel_all_pill_timers(device_id: str) -> None:
        for pill_id in list(hass.data[DOMAIN][device_id]["pill_timers"]):
            _cancel_pill_timer(device_id, pill_id)

    async def _save_pills(device_id: str) -> None:
        await hass.data[DOMAIN][device_id]["pill_store"].async_save(
            hass.data[DOMAIN][device_id]["pills"]
        )

    async def _remove_pill_and_push(device_id: str, pill_id: str) -> None:
        hass.data[DOMAIN][device_id]["pills"].pop(pill_id, None)
        hass.data[DOMAIN][device_id]["pill_timers"].pop(pill_id, None)
        await _save_pills(device_id)
        conn = get_connection(hass, device_id)
        if conn:
            await conn.send_command({"pills": list(hass.data[DOMAIN][device_id]["pills"].values())})

    async def handle_add_pill(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        conn = get_connection(hass, device_id)
        pill_id = call.data["pill_id"]
        pill = {
            "id": pill_id,
            "text": call.data["text"],
        }
        if call.data.get("icon"):
            pill["icon"] = call.data["icon"]
        if call.data.get("color"):
            pill["color"] = call.data["color"]
        pill["position"] = call.data.get("position", "under_clock")
        _cancel_pill_timer(device_id, pill_id)
        hass.data[DOMAIN][device_id]["pills"][pill_id] = pill
        await _save_pills(device_id)
        duration = call.data.get("duration")
        if duration:
            @callback
            def _auto_remove(_now, _device_id=device_id, _pill_id=pill_id):
                hass.async_create_task(_remove_pill_and_push(_device_id, _pill_id))
            hass.data[DOMAIN][device_id]["pill_timers"][pill_id] = async_call_later(hass, duration, _auto_remove)
        if conn:
            await conn.send_command({"pills": list(hass.data[DOMAIN][device_id]["pills"].values())})

    async def handle_remove_pill(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        _cancel_pill_timer(device_id, call.data["pill_id"])
        await _remove_pill_and_push(device_id, call.data["pill_id"])

    async def handle_dismiss_all_pills(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        _cancel_all_pill_timers(device_id)
        hass.data[DOMAIN][device_id]["pills"].clear()
        await _save_pills(device_id)
        conn = get_connection(hass, device_id)
        if conn:
            await conn.send_command({"pills": []})

    async def handle_get_pills(call: ServiceCall) -> ServiceResponse:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return {"pills": []}
        return {"pills": list(hass.data[DOMAIN][device_id]["pills"].values())}

    async def handle_get_timers(call: ServiceCall) -> ServiceResponse:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return {"timers": []}
        return {"timers": list(hass.data[DOMAIN][device_id]["timers"].values())}

    async def handle_dismiss_all_timers(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        hass.data[DOMAIN][device_id]["timers"].clear()
        conn = get_connection(hass, device_id)
        if conn:
            await conn.send_command({"timers": []})

    async def handle_get_alarms(call: ServiceCall) -> ServiceResponse:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return {"alarms": []}
        return {"alarms": list(hass.data[DOMAIN][device_id]["alarms"].values())}

    async def handle_dismiss_all_alarms(call: ServiceCall) -> None:
        device_id = resolve_device_id(hass, call.data["device_id"])
        if not device_id:
            return
        hass.data[DOMAIN][device_id]["alarms"].clear()
        conn = get_connection(hass, device_id)
        if conn:
            await conn.send_command({"alarms": []})

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_PILL, handle_add_pill,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("pill_id"): cv.string,
            vol.Required("text"): cv.string,
            vol.Optional("icon"): vol.In(_pill_icons),
            vol.Optional("color"): cv.string,
            vol.Optional("position", default="under_clock"): vol.In(_pill_positions),
            vol.Optional("duration"): vol.Coerce(int),
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_PILL, handle_remove_pill,
        schema=vol.Schema({vol.Required("device_id"): cv.string, vol.Required("pill_id"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISMISS_ALL_PILLS, handle_dismiss_all_pills,
        schema=_device_id_schema,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_GET_PILLS, handle_get_pills,
        schema=_device_id_schema,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_GET_TIMERS, handle_get_timers,
        schema=_device_id_schema,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISMISS_ALL_TIMERS, handle_dismiss_all_timers,
        schema=_device_id_schema,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_GET_ALARMS, handle_get_alarms,
        schema=_device_id_schema,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISMISS_ALL_ALARMS, handle_dismiss_all_alarms,
        schema=_device_id_schema,
    )


def _parse_photo_urls(raw: str) -> list[str]:
    """Split comma- or newline-separated URL string into a clean list."""
    import re
    return [u.strip() for u in re.split(r'[,\n]+', raw) if u.strip()]


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    device_id = entry.data[CONF_DEVICE_ID]
    conn = hass.data[DOMAIN].get(device_id, {}).get("connection")
    if conn:
        await conn.stop()

    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(device_id, None)
    return ok


class DeviceConnection:
    """Persistent WebSocket connection from HA to the display device."""

    def __init__(self, hass, entry, device_id, host, port, weather_entity, camera_entities, climate_entity=None, temperature_sensor=None, humidity_sensor=None, auto_ambient_lux=None, ma_media_player=None, immich_url="", immich_api_key="", immich_album_ids=None, immich_refresh_interval=60, immich_batch_size=30, slideshow_interval=60, frigate_url="", go2rtc_url=""):
        self._hass = hass
        self._entry = entry
        self._device_id = device_id
        self._host = host
        self._port = port
        self._weather_entity = weather_entity
        self._camera_entities = camera_entities or []
        self._climate_entity = climate_entity
        self._temperature_sensor = temperature_sensor
        self._humidity_sensor = humidity_sensor
        self._auto_ambient_lux = auto_ambient_lux
        self._ma_media_player = ma_media_player
        self._auto_ambient_active: bool | None = None
        self._ws = None
        self._running = True
        self._reconnect_delay = 5
        self._unsub_weather = None
        self._unsub_climate = None
        self._unsub_ma = None
        self._ma_push_task = None
        self._last_ma_title: str | None = None
        self._last_ma_artist: str | None = None
        self._unsub_immich_refresh = None
        self._camera_task = None
        self._focused_camera: str | None = None
        self._focused_camera_stream_type: str = STREAM_TYPE_SNAPSHOT
        self._fast_camera_task = None
        self._frigate_url = frigate_url
        self._go2rtc_url = go2rtc_url
        self._go2rtc_streams: set[str] | None = None  # cached go2rtc stream names
        self._immich_refresh_interval = immich_refresh_interval
        self._slideshow_interval = slideshow_interval
        self._immich_provider = (
            ImmichProvider(immich_url, immich_api_key, immich_album_ids or [], immich_batch_size)
            if (immich_url and immich_api_key and immich_album_ids)
            else None
        )

    async def run(self):
        while self._running:
            try:
                uri = f"ws://{self._host}:{self._port}"
                _LOGGER.info("ha_smart_display: connecting to %s", uri)
                async with websockets.connect(uri, open_timeout=10) as ws:
                    self._ws = ws
                    self._reconnect_delay = 5
                    self._go2rtc_streams = None  # re-fetch on next use
                    _LOGGER.info("ha_smart_display: connected to %s", self._device_id)

                    # Subscribe to weather changes
                    if self._weather_entity:
                        self._unsub_weather = async_track_state_change_event(
                            self._hass,
                            [self._weather_entity],
                            self._on_weather_change,
                        )
                        # Push current weather immediately
                        await self._push_weather()

                    # Subscribe to climate / sensor changes
                    climate_sensor_entities = []
                    if self._climate_entity:
                        climate_sensor_entities.append(self._climate_entity)
                    if self._temperature_sensor:
                        climate_sensor_entities.append(self._temperature_sensor)
                    if self._humidity_sensor:
                        climate_sensor_entities.append(self._humidity_sensor)
                    if climate_sensor_entities:
                        self._unsub_climate = async_track_state_change_event(
                            self._hass,
                            climate_sensor_entities,
                            self._on_climate_change,
                        )
                        await self._push_climate()

                    # Subscribe to MA media player state changes
                    if self._ma_media_player:
                        self._unsub_ma = async_track_state_change_event(
                            self._hass,
                            [self._ma_media_player],
                            self._on_ma_state_change,
                        )
                        # Reset cache so first push on connect always goes through
                        self._last_ma_title = None
                        self._last_ma_artist = None
                        await self._push_ma_track()

                    # Push any persisted pills
                    await self._push_pills()

                    # Send Immich config + push photos and timers/alarms
                    if self._immich_provider:
                        await self._send_immich_config()
                        self._unsub_immich_refresh = async_track_time_interval(
                            self._hass,
                            self._on_immich_refresh,
                            timedelta(minutes=self._immich_refresh_interval),
                        )
                    await self.send_command({"display_modes": self._available_modes()})
                    await self.send_command({"slideshow_interval": self._slideshow_interval})
                    await self._push_photos()
                    await self._push_timers_alarms()

                    # Start camera snapshot loop
                    if self._camera_entities:
                        self._camera_task = self._hass.async_create_task(
                            self._camera_loop()
                        )

                    await self._listen(ws)
            except (OSError, websockets.WebSocketException) as e:
                _LOGGER.warning(
                    "ha_smart_display: connection lost (%s), retrying in %ds",
                    e, self._reconnect_delay,
                )
            finally:
                self._ws = None
                self._set_available(False)
                self._auto_ambient_active = None
                if self._unsub_weather:
                    self._unsub_weather()
                    self._unsub_weather = None
                if self._unsub_climate:
                    self._unsub_climate()
                    self._unsub_climate = None
                if self._unsub_ma:
                    self._unsub_ma()
                    self._unsub_ma = None
                if self._unsub_immich_refresh:
                    self._unsub_immich_refresh()
                    self._unsub_immich_refresh = None
                if self._camera_task:
                    self._camera_task.cancel()
                    self._camera_task = None
                if self._fast_camera_task:
                    self._fast_camera_task.cancel()
                    self._fast_camera_task = None
                self._focused_camera = None

            if self._running:
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)

    async def _listen(self, ws):
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                _LOGGER.warning("ha_smart_display: received malformed JSON: %s", raw[:200])
                continue

            msg_type = msg.get("type")

            if msg_type == "state":
                payload = msg.get("state", {})
                self._hass.data[DOMAIN][self._device_id]["state"] = payload
                self._set_available(True)
                async_dispatcher_send(
                    self._hass,
                    SIGNAL_STATE_UPDATED.format(device_id=self._device_id),
                    payload,
                )
                # Handle dismissed timers/alarms reported by device
                if "dismissed_timer" in payload:
                    self._hass.data[DOMAIN][self._device_id]["timers"].pop(
                        payload["dismissed_timer"], None
                    )
                if "dismissed_alarm" in payload:
                    self._hass.data[DOMAIN][self._device_id]["alarms"].pop(
                        payload["dismissed_alarm"], None
                    )
                # Auto-ambient: switch ambient on/off based on lux threshold
                if self._auto_ambient_lux is not None and "lux" in payload:
                    lux = payload["lux"]
                    if lux is not None:
                        should_be_ambient = lux < self._auto_ambient_lux
                        if should_be_ambient != self._auto_ambient_active:
                            self._auto_ambient_active = should_be_ambient
                            await self.send_command({"ambient_active": should_be_ambient})

                # Handle focused camera — start/stop fast snapshot loop
                # For video stream types, app streams directly from Frigate — no JPEG loop needed
                if "focused_camera" in payload:
                    focused = payload.get("focused_camera")
                    if focused != self._focused_camera:
                        self._focused_camera = focused
                        if self._fast_camera_task:
                            self._fast_camera_task.cancel()
                            self._fast_camera_task = None
                        if focused and focused in self._camera_entities and self._focused_camera_stream_type == STREAM_TYPE_SNAPSHOT:
                            self._fast_camera_task = self._hass.async_create_task(
                                self._focused_camera_loop(focused)
                            )

            elif msg_type == "ping":
                await ws.send(json.dumps({"type": "pong"}))

            elif msg_type == "event":
                if msg.get("event") == "voice_command_audio":
                    audio_b64 = msg.get("audio")
                    satellite = self._hass.data.get(DOMAIN, {}).get(self._device_id, {}).get("satellite_entity")
                    if audio_b64 and satellite:
                        audio_bytes = base64.b64decode(audio_b64)
                        self._hass.async_create_task(
                            self._run_pipeline_via_satellite(satellite, audio_bytes)
                        )
                elif msg.get("event") == "tts_finished":
                    satellite = self._hass.data.get(DOMAIN, {}).get(self._device_id, {}).get("satellite_entity")
                    if satellite:
                        satellite.on_tts_finished()
                elif msg.get("event") == "notification_action":
                    self._hass.bus.async_fire(
                        f"{DOMAIN}_notification_action",
                        {
                            "device_id": self._device_id,
                            "button": msg.get("button"),
                            "index": msg.get("index"),
                        },
                    )
                elif msg.get("event") == "media_command":
                    command = msg.get("command")
                    self._hass.bus.async_fire(
                        f"{DOMAIN}_media_command",
                        {
                            "device_id": self._device_id,
                            "command": command,
                        },
                    )
                    # Forward next/previous to the configured MA media player
                    if self._ma_media_player and command in ("next", "previous"):
                        service = "media_next_track" if command == "next" else "media_previous_track"
                        self._hass.async_create_task(
                            self._hass.services.async_call(
                                "media_player", service,
                                {"entity_id": self._ma_media_player},
                            )
                        )
                    elif self._ma_media_player and command == "shuffle":
                        self._hass.async_create_task(self._handle_shuffle_toggle())
                elif msg.get("event") == "browse_media":
                    category = msg.get("category", "")
                    self._hass.async_create_task(self._handle_browse_request(category))
                elif msg.get("event") == "play_media_item":
                    media_content_id = msg.get("media_content_id", "")
                    media_content_type = msg.get("media_content_type", "")
                    if self._ma_media_player and media_content_id:
                        self._hass.async_create_task(
                            self._hass.services.async_call(
                                "media_player",
                                "play_media",
                                {
                                    "entity_id": self._ma_media_player,
                                    "media_content_id": media_content_id,
                                    "media_content_type": media_content_type,
                                },
                            )
                        )
                elif msg.get("event") == "climate_set_temperature" and self._climate_entity:
                    temperature = msg.get("temperature")
                    if temperature is not None:
                        climate_state = self._hass.states.get(self._climate_entity)
                        if climate_state and climate_state.state == "heat_cool":
                            # heat_cool mode requires target_temp_high + target_temp_low
                            attrs = climate_state.attributes
                            min_t = attrs.get("min_temp", 7)
                            max_t = attrs.get("max_temp", 35)
                            current_high = attrs.get("target_temp_high")
                            current_low = attrs.get("target_temp_low")
                            if current_high is not None and current_low is not None:
                                half_spread = (current_high - current_low) / 2
                                new_high = max(min_t, min(max_t, temperature + half_spread))
                                new_low = max(min_t, min(max_t, temperature - half_spread))
                                service_data = {
                                    "entity_id": self._climate_entity,
                                    "target_temp_high": new_high,
                                    "target_temp_low": new_low,
                                }
                            else:
                                service_data = {
                                    "entity_id": self._climate_entity,
                                    "target_temp_high": max(min_t, min(max_t, temperature + 1)),
                                    "target_temp_low": max(min_t, min(max_t, temperature - 1)),
                                }
                        else:
                            service_data = {
                                "entity_id": self._climate_entity,
                                "temperature": temperature,
                            }
                        await self._hass.services.async_call(
                            "climate", "set_temperature", service_data,
                        )
                elif msg.get("event") == "climate_set_hvac_mode" and self._climate_entity:
                    hvac_mode = msg.get("hvac_mode")
                    if hvac_mode is not None:
                        await self._hass.services.async_call(
                            "climate", "set_hvac_mode",
                            {"entity_id": self._climate_entity, "hvac_mode": hvac_mode},
                        )

    @callback
    def _on_weather_change(self, event) -> None:
        """Called when weather entity state changes."""
        self._hass.async_create_task(self._push_weather())

    @callback
    def _on_climate_change(self, event) -> None:
        """Called when climate entity state changes."""
        self._hass.async_create_task(self._push_climate())

    @callback
    def _on_ma_state_change(self, event) -> None:
        """Called when the MA media player entity state changes.
        Debounced: MA fires state changes for position updates and intermediate
        states during track transitions. Only push after 500ms of silence so
        the metadata has settled before sending to the device."""
        if self._ma_push_task and not self._ma_push_task.done():
            self._ma_push_task.cancel()
        self._ma_push_task = self._hass.async_create_task(
            self._debounced_push_ma_track()
        )

    async def _debounced_push_ma_track(self):
        import asyncio
        await asyncio.sleep(2.0)
        await self._push_ma_track()

    async def _push_pills(self):
        if not self._ws:
            return
        pills = list(self._hass.data[DOMAIN][self._device_id]["pills"].values())
        await self.send_command({"pills": pills})

    async def _handle_shuffle_toggle(self) -> None:
        """Toggle shuffle on the configured MA media player."""
        if not self._ws or not self._ma_media_player:
            return
        state = self._hass.states.get(self._ma_media_player)
        current = bool(state.attributes.get("shuffle", False)) if state else False
        new_shuffle = not current
        try:
            await self._hass.services.async_call(
                "media_player",
                "shuffle_set",
                {"entity_id": self._ma_media_player, "shuffle": new_shuffle},
            )
            await self.send_command({"shuffle_enabled": new_shuffle})
        except Exception as e:
            _LOGGER.warning("ha_smart_display: shuffle_set failed: %s", e)

    async def _handle_browse_request(self, category: str) -> None:
        """Browse MA media library for a category and push results to device."""
        if not self._ws or not self._ma_media_player:
            return
        # Titles MA uses for each root-level category (matched case-insensitively)
        category_keywords = {
            "artists": ["artist"],
            "albums": ["album"],
            "tracks": ["track", "song"],
            "playlists": ["playlist"],
            "radio": ["radio"],
        }
        keywords = category_keywords.get(category, [category])
        try:
            from homeassistant.components.media_player import DOMAIN as MP_DOMAIN
            entity_comp = self._hass.data.get(MP_DOMAIN)
            if not entity_comp:
                _LOGGER.warning("ha_smart_display: media_player component not found for browse")
                await self.send_command({"browse_result": {"category": category, "items": []}})
                return
            entity = entity_comp.get_entity(self._ma_media_player)
            if not entity or not hasattr(entity, "async_browse_media"):
                _LOGGER.warning("ha_smart_display: MA entity not found or doesn't support browse")
                await self.send_command({"browse_result": {"category": category, "items": []}})
                return

            # Browse root to discover the real content IDs MA uses for each category
            root = await entity.async_browse_media(None, None)
            category_item = None
            for child in (root.children or []):
                title_lower = (child.title or "").lower()
                if any(kw in title_lower for kw in keywords):
                    category_item = child
                    break

            if not category_item:
                _LOGGER.warning(
                    "ha_smart_display: category '%s' not found in MA root browse (children: %s)",
                    category,
                    [c.title for c in (root.children or [])],
                )
                await self.send_command({"browse_result": {"category": category, "items": []}})
                return

            # Browse into the matched category to get actual items
            result = await entity.async_browse_media(
                category_item.media_content_type,
                category_item.media_content_id,
            )
            items = []
            for child in (result.children or []):
                thumbnail = child.thumbnail
                if thumbnail and thumbnail.startswith("/"):
                    try:
                        from homeassistant.helpers.network import get_url
                        base = get_url(self._hass, allow_internal=True, prefer_external=False)
                        thumbnail = f"{base.rstrip('/')}{thumbnail}"
                    except Exception as e:
                        _LOGGER.debug("ha_smart_display: could not resolve thumbnail URL: %s", e)
                subtitle = getattr(child, "media_artist", None) or getattr(child, "media_album_name", None)
                items.append({
                    "title": child.title or "",
                    "subtitle": subtitle,
                    "thumbnail": thumbnail,
                    "media_content_id": child.media_content_id or "",
                    "media_content_type": child.media_content_type or "",
                    "can_play": child.can_play,
                    "can_expand": child.can_expand,
                })
            await self.send_command({"browse_result": {"category": category, "items": items}})
        except Exception as e:
            _LOGGER.warning("ha_smart_display: browse_media failed for '%s': %s", category, e)
            await self.send_command({"browse_result": {"category": category, "items": []}})

    async def _push_ma_track(self):
        if not self._ws or not self._ma_media_player:
            return
        state = self._hass.states.get(self._ma_media_player)
        if not state or state.state in ("unavailable", "unknown", "idle", "off"):
            return
        title = state.attributes.get("media_title") or ""
        artist = state.attributes.get("media_artist")
        # Skip push if metadata hasn't changed — avoids re-sending during
        # position-only MA state changes and brief intermediate states during
        # track transitions where title hasn't settled to the new track yet.
        if title == self._last_ma_title and artist == self._last_ma_artist and title:
            return
        self._last_ma_title = title
        self._last_ma_artist = artist
        art_url = state.attributes.get("entity_picture")
        # Resolve relative art URL to absolute so the device can fetch it
        if art_url and art_url.startswith("/"):
            try:
                from homeassistant.helpers.network import get_url
                base = get_url(self._hass, allow_internal=True, prefer_external=False)
                art_url = f"{base.rstrip('/')}{art_url}"
            except Exception as e:
                _LOGGER.debug("ha_smart_display: could not resolve art URL: %s", e)
        duration = state.attributes.get("media_duration") or 0
        track = {
            "title": title,
            "artist": artist,
            "album": state.attributes.get("media_album_name"),
            "art_url": art_url,
            "duration_ms": int(duration * 1000),
        }
        shuffle = bool(state.attributes.get("shuffle", False))
        await self.send_command({"media_track": track, "shuffle_enabled": shuffle})

    async def _push_climate(self):
        if not self._ws:
            return
        has_climate = bool(self._climate_entity)
        has_sensors = bool(self._temperature_sensor or self._humidity_sensor)
        if not has_climate and not has_sensors:
            return

        unit = self._hass.config.units.temperature_unit

        if has_climate:
            state = self._hass.states.get(self._climate_entity)
            if not state:
                return
            attrs = state.attributes
            unit = attrs.get("temperature_unit") or unit
            target_temp = attrs.get("temperature")
            if state.state == "heat_cool":
                high = attrs.get("target_temp_high")
                low = attrs.get("target_temp_low")
                if high is not None and low is not None:
                    target_temp = (high + low) / 2
            current_temp = attrs.get("current_temperature")
            humidity = attrs.get("current_humidity")
            name = attrs.get("friendly_name", self._climate_entity)
            hvac_mode = state.state
            hvac_modes = attrs.get("hvac_modes", [])
            min_temp = attrs.get("min_temp", 7)
            max_temp = attrs.get("max_temp", 35)
        else:
            # Sensor-only — read-only, no climate control
            current_temp = None
            humidity = None
            name = None
            hvac_mode = "off"
            hvac_modes = []
            target_temp = None
            min_temp = 7
            max_temp = 35

        # Sensor values override climate entity's built-in readings if configured
        if self._temperature_sensor:
            temp_state = self._hass.states.get(self._temperature_sensor)
            if temp_state and temp_state.state not in ("unknown", "unavailable"):
                try:
                    current_temp = float(temp_state.state)
                    unit = temp_state.attributes.get("unit_of_measurement") or unit
                    if name is None:
                        name = temp_state.attributes.get("friendly_name", self._temperature_sensor)
                except ValueError:
                    pass

        if self._humidity_sensor:
            hum_state = self._hass.states.get(self._humidity_sensor)
            if hum_state and hum_state.state not in ("unknown", "unavailable"):
                try:
                    humidity = int(float(hum_state.state))
                    if name is None:
                        name = hum_state.attributes.get("friendly_name", self._humidity_sensor)
                except ValueError:
                    pass

        if name is None:
            name = "Room Sensor"

        climate_payload = {
            "name": name,
            "current_temperature": current_temp,
            "humidity": humidity,
            "target_temperature": target_temp,
            "hvac_mode": hvac_mode,
            "hvac_modes": hvac_modes,
            "min_temp": min_temp,
            "max_temp": max_temp,
            "unit": unit,
        }
        await self.send_command({"climate": climate_payload})

    async def _push_weather(self):
        if not self._weather_entity or not self._ws:
            return
        state = self._hass.states.get(self._weather_entity)
        if not state:
            return
        attrs = state.attributes
        unit = self._hass.config.units.temperature_unit

        # Fetch hourly forecast via modern HA service call
        forecast = []
        for forecast_type in ("hourly", "daily"):
            try:
                response = await self._hass.services.async_call(
                    "weather",
                    "get_forecasts",
                    {"entity_id": self._weather_entity, "type": forecast_type},
                    blocking=True,
                    return_response=True,
                )
                periods = response.get(self._weather_entity, {}).get("forecast", [])
                if periods:
                    forecast = periods[:24]
                    break
            except Exception as e:
                _LOGGER.debug("ha_smart_display: forecast type %s failed: %s", forecast_type, e)

        weather_payload = {
            "condition": state.state,
            "temperature": attrs.get("temperature"),
            "temperature_unit": unit,
            "humidity": attrs.get("humidity"),
            "wind_speed": attrs.get("wind_speed"),
            "forecast": forecast,
        }
        await self.send_command({"weather": weather_payload})

    async def _send_immich_config(self):
        if self._immich_provider:
            await self.send_command({
                "immich_config": {
                    "url": self._immich_provider._url,
                    "api_key": self._immich_provider._api_key,
                }
            })

    @callback
    def _on_immich_refresh(self, now=None) -> None:
        """Periodic Immich photo refresh."""
        if self._ws:
            self._hass.async_create_task(self._push_photos())

    async def _push_photos(self):
        static_urls = self._hass.data[DOMAIN].get(self._device_id, {}).get("photos", [])
        static_photos = [{"url": u} for u in static_urls]
        immich_photos = await self._immich_provider.fetch_photos() if self._immich_provider else []
        merged = static_photos + immich_photos
        random.shuffle(merged)
        await self.send_command({"photos": merged})

    async def _check_go2rtc_stream(self, camera_name: str) -> bool:
        """Check if a camera has a go2rtc stream available in Frigate."""
        if not self._frigate_url:
            return False
        if self._go2rtc_streams is None:
            import aiohttp
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{self._frigate_url}/api/go2rtc/api/streams",
                        timeout=aiohttp.ClientTimeout(total=5),
                        ssl=False,
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            self._go2rtc_streams = set(data.keys())
                        else:
                            _LOGGER.warning("ha_smart_display: go2rtc streams API returned %s", resp.status)
                            return False
            except Exception as e:
                _LOGGER.warning("ha_smart_display: failed to query go2rtc streams: %s", e)
                return False
        return camera_name in self._go2rtc_streams

    async def _camera_loop(self):
        """Push camera snapshots while connected — 2s when visible, 60s otherwise."""
        while self._ws is not None:
            start = asyncio.get_event_loop().time()
            device_state = self._hass.data[DOMAIN].get(self._device_id, {}).get("state", {})
            ambient_active = device_state.get("ambient_active", False)
            cameras_visible = (
                device_state.get("ambient_mode") == "cameras"
                and not ambient_active
            )
            if not ambient_active:
                await self._push_camera_snapshots()
            elapsed = asyncio.get_event_loop().time() - start
            interval = 2.0 if cameras_visible else 60.0
            await asyncio.sleep(max(0.0, interval - elapsed))

    async def _push_camera_snapshots(self):
        from homeassistant.components.camera import async_get_image

        async def _fetch_one(entity_id: str) -> dict | None:
            try:
                image = await async_get_image(self._hass, entity_id, timeout=5)
                b64 = base64.b64encode(image.content).decode()
                state = self._hass.states.get(entity_id)
                name = (state.attributes.get("friendly_name", entity_id) if state else entity_id)
                return {"id": entity_id, "name": name, "data": b64}
            except Exception as e:
                _LOGGER.debug("ha_smart_display: camera snapshot failed for %s: %s", entity_id, e)
                return None

        results = await asyncio.gather(*[_fetch_one(eid) for eid in self._camera_entities])
        cameras = [r for r in results if r is not None]
        if cameras:
            await self.send_command({"cameras": cameras})

    async def _focused_camera_loop(self, entity_id: str):
        """Push snapshots for a focused camera at ~1fps."""
        from homeassistant.components.camera import async_get_image
        while self._ws is not None and self._focused_camera == entity_id:
            start = asyncio.get_event_loop().time()
            try:
                image = await async_get_image(self._hass, entity_id, timeout=5)
                b64 = base64.b64encode(image.content).decode()
                state = self._hass.states.get(entity_id)
                name = state.attributes.get("friendly_name", entity_id) if state else entity_id
                await self.send_command({"focused_camera_data": {"id": entity_id, "name": name, "data": b64}})
            except Exception as e:
                _LOGGER.debug("ha_smart_display: focused camera snapshot failed: %s", e)
            elapsed = asyncio.get_event_loop().time() - start
            await asyncio.sleep(max(0.0, 1.0 - elapsed))

    async def _push_timers_alarms(self):
        data = self._hass.data[DOMAIN].get(self._device_id, {})
        now = int(datetime.now().timestamp())
        # Add remaining_seconds so Flutter can compute ends_at locally,
        # avoiding clock drift and correctly handling reconnect.
        timers = [
            {**t, "remaining_seconds": max(0, t["ends_at"] - now)}
            for t in data.get("timers", {}).values()
        ]
        alarms = list(data.get("alarms", {}).values())
        await self.send_command({"timers": timers, "alarms": alarms})

    async def _run_pipeline_via_satellite(self, satellite, audio_bytes: bytes) -> None:
        """Run HA Assist pipeline via the AssistSatelliteEntity."""
        async def audio_stream():
            chunk_size = 8000
            for i in range(0, len(audio_bytes), chunk_size):
                yield audio_bytes[i:i + chunk_size]

        await satellite.async_accept_pipeline_from_satellite(audio_stream=audio_stream())

    def _set_available(self, available: bool):
        data = self._hass.data.get(DOMAIN, {}).get(self._device_id)
        if data and data.get("available") != available:
            data["available"] = available
            async_dispatcher_send(
                self._hass,
                SIGNAL_AVAILABILITY_UPDATED.format(device_id=self._device_id),
                available,
            )

    def _available_modes(self) -> list[str]:
        modes = ["clock"]
        if self._weather_entity:
            modes.append("weather")
        if self._camera_entities:
            modes.append("cameras")
        if self._ma_media_player:
            modes.append("music")
        return modes

    async def send_command(self, payload: dict):
        if self._ws is None:
            _LOGGER.debug(
                "ha_smart_display: cannot send command, not connected (%s)",
                self._device_id,
            )
            return
        try:
            await self._ws.send(json.dumps({"type": "command", "payload": payload}))
        except Exception as e:
            _LOGGER.warning("ha_smart_display: send failed: %s", e)

    async def stop(self):
        self._running = False
        if self._fast_camera_task:
            self._fast_camera_task.cancel()
            self._fast_camera_task = None
        if self._ws:
            await self._ws.close()


def get_connection(hass: HomeAssistant, device_id: str) -> "DeviceConnection | None":
    return hass.data.get(DOMAIN, {}).get(device_id, {}).get("connection")


def resolve_device_id(hass: HomeAssistant, ha_device_id: str) -> str | None:
    """Convert an HA device registry ID to our internal device_id."""
    from homeassistant.helpers import device_registry as dr
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get(ha_device_id)
    if not device:
        return None
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == DOMAIN:
            return entry.data.get(CONF_DEVICE_ID)
    return None
