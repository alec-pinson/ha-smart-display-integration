import asyncio
import json
import logging

import voluptuous as vol
import websockets

from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import DOMAIN, CONF_DEVICE_ID, CONF_DEVICE_NAME, CONF_HOST, CONF_PORT, CONF_WEATHER_ENTITY, CONF_PHOTO_URLS, CONF_CAMERA_ENTITIES, CONF_CLIMATE_ENTITY, CONF_TEMPERATURE_SENSOR, CONF_HUMIDITY_SENSOR, CONF_AUTO_AMBIENT_LUX, CONF_MA_MEDIA_PLAYER, CONF_DOOR_ENTITIES, CONF_MOTION_ENTITIES, CONF_IMMICH_URL, CONF_IMMICH_API_KEY, CONF_IMMICH_ALBUM_IDS, CONF_IMMICH_REFRESH_INTERVAL, CONF_IMMICH_BATCH_SIZE, CONF_SLIDESHOW_INTERVAL, DEFAULT_PORT

_LOGGER = logging.getLogger(__name__)


class HaSmartDisplayConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._host: str | None = None
        self._port: int = DEFAULT_PORT
        self._device_name: str = "HA Smart Display"
        self._last_error_detail: str = ""

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> config_entries.FlowResult:
        self._host = discovery_info.host
        self._port = discovery_info.port or DEFAULT_PORT
        name = discovery_info.name.replace(f"._{DOMAIN}._tcp.local.", "")
        self._device_name = name or "HA Smart Display"

        device_id = discovery_info.properties.get("device_id", "")
        _LOGGER.info("ha_smart_display: discovered device '%s' at %s:%s", name or "unknown", self._host, self._port)
        if device_id:
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured(
                updates={CONF_HOST: self._host, CONF_PORT: self._port}
            )

        self.context["title_placeholders"] = {"name": self._device_name}
        return await self.async_step_pairing()

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST]
            self._port = user_input.get(CONF_PORT, DEFAULT_PORT)
            return await self.async_step_pairing()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
            }),
            errors=errors,
        )

    async def async_step_pairing(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors = {}

        if user_input is not None:
            code = user_input.get("pairing_code", "").strip()
            result = await self._try_pair(code)
            if result is None:
                errors["base"] = "cannot_connect"
            elif result is False:
                errors["pairing_code"] = "invalid_code"
            else:
                device_id = result["device_id"]
                device_name = result.get("device_name", self._device_name)
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=device_name,
                    data={
                        CONF_DEVICE_ID: device_id,
                        CONF_DEVICE_NAME: device_name,
                        CONF_HOST: self._host,
                        CONF_PORT: self._port,
                    },
                )

        return self.async_show_form(
            step_id="pairing",
            data_schema=vol.Schema({vol.Required("pairing_code"): str}),
            description_placeholders={
                "device_name": self._device_name,
                "host": self._host,
            },
            errors=errors,
        )

    async def _try_pair(self, code: str) -> dict | bool | None:
        uri = f"ws://{self._host}:{self._port}"
        _LOGGER.debug("ha_smart_display: attempting to connect to %s", uri)
        try:
            async with websockets.connect(uri, open_timeout=10) as ws:
                await ws.send(json.dumps({"type": "pair", "code": code}))
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                msg = json.loads(raw)
                if msg.get("type") == "pair_ok":
                    _LOGGER.info("ha_smart_display: pairing successful with %s", self._host)
                    return {
                        "device_id": msg["device_id"],
                        "device_name": msg.get("device_name", self._device_name),
                    }
                elif msg.get("type") == "pair_error":
                    return False
        except asyncio.TimeoutError:
            self._last_error_detail = f"Timed out connecting to {uri}"
            _LOGGER.warning("ha_smart_display: timed out connecting to %s", uri)
            return None
        except OSError as e:
            self._last_error_detail = f"Cannot reach {uri}: {e.strerror}"
            _LOGGER.warning("ha_smart_display: cannot reach %s: %s", uri, e)
            return None
        except Exception as e:
            self._last_error_detail = str(e)
            _LOGGER.warning("ha_smart_display: pairing connection failed: %s", e)
            return None
        _LOGGER.warning("ha_smart_display: unexpected pairing response: %s", msg.get("type"))
        return False

    @staticmethod
    def async_get_options_flow(config_entry):
        return HaSmartDisplayOptionsFlow(config_entry)


async def _fetch_immich_albums(url: str, api_key: str) -> list[dict]:
    """Fetch album list from Immich. Returns list of {id, albumName}. Raises on failure."""
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{url.rstrip('/')}/api/albums",
            headers={"x-api-key": api_key},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                raise Exception(f"HTTP {resp.status}")
            data = await resp.json()
            return [{"id": a["id"], "albumName": a["albumName"]} for a in data if "id" in a]


class HaSmartDisplayOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self._config_entry = config_entry
        self._pending_options: dict = {}
        self._pending_albums: list[dict] = []

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors = {}

        if user_input is not None:
            # Strip empty/None values for optional entity fields so clearing them works
            data = {k: v for k, v in user_input.items() if v not in (None, "", [])}
            immich_url = data.get(CONF_IMMICH_URL, "").strip()
            immich_api_key = data.get(CONF_IMMICH_API_KEY, "").strip()

            if immich_url and immich_api_key:
                # Validate Immich credentials and fetch album list
                try:
                    albums = await _fetch_immich_albums(immich_url, immich_api_key)
                except Exception:
                    errors["base"] = "immich_connection_failed"
                else:
                    self._pending_options = data
                    self._pending_albums = albums
                    return await self.async_step_immich_albums()
            else:
                # Immich disabled — drop any previously saved album IDs and save
                data.pop(CONF_IMMICH_ALBUM_IDS, None)
                return self.async_create_entry(title="", data=data)

        schema = vol.Schema({
            vol.Optional(CONF_WEATHER_ENTITY): selector.selector({
                "entity": {"domain": "weather"}
            }),
            vol.Optional(CONF_CLIMATE_ENTITY): selector.selector({
                "entity": {"domain": "climate"}
            }),
            vol.Optional(CONF_TEMPERATURE_SENSOR): selector.selector({
                "entity": {"device_class": "temperature"}
            }),
            vol.Optional(CONF_HUMIDITY_SENSOR): selector.selector({
                "entity": {"device_class": "humidity"}
            }),
            vol.Optional(CONF_PHOTO_URLS): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
            vol.Optional(CONF_CAMERA_ENTITIES): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="camera", multiple=True)
            ),
            vol.Optional(CONF_AUTO_AMBIENT_LUX): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=10000, step=1, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_MA_MEDIA_PLAYER): selector.selector({
                "entity": {"domain": "media_player"}
            }),
            vol.Optional(CONF_DOOR_ENTITIES): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            vol.Optional(CONF_MOTION_ENTITIES): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            vol.Optional(CONF_IMMICH_URL): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
            ),
            vol.Optional(CONF_IMMICH_API_KEY): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_IMMICH_REFRESH_INTERVAL): selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=1440, step=1, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_IMMICH_BATCH_SIZE): selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=100, step=1, unit_of_measurement="photos", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_SLIDESHOW_INTERVAL): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=60, step=1, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX)
            ),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    CONF_WEATHER_ENTITY: self._config_entry.options.get(CONF_WEATHER_ENTITY, ""),
                    CONF_CLIMATE_ENTITY: self._config_entry.options.get(CONF_CLIMATE_ENTITY, ""),
                    CONF_TEMPERATURE_SENSOR: self._config_entry.options.get(CONF_TEMPERATURE_SENSOR, ""),
                    CONF_HUMIDITY_SENSOR: self._config_entry.options.get(CONF_HUMIDITY_SENSOR, ""),
                    CONF_PHOTO_URLS: self._config_entry.options.get(CONF_PHOTO_URLS, ""),
                    CONF_CAMERA_ENTITIES: self._config_entry.options.get(CONF_CAMERA_ENTITIES, []),
                    CONF_AUTO_AMBIENT_LUX: self._config_entry.options.get(CONF_AUTO_AMBIENT_LUX),
                    CONF_MA_MEDIA_PLAYER: self._config_entry.options.get(CONF_MA_MEDIA_PLAYER, ""),
                    CONF_DOOR_ENTITIES: self._config_entry.options.get(CONF_DOOR_ENTITIES, []),
                    CONF_MOTION_ENTITIES: self._config_entry.options.get(CONF_MOTION_ENTITIES, []),
                    CONF_IMMICH_URL: self._config_entry.options.get(CONF_IMMICH_URL, ""),
                    CONF_IMMICH_API_KEY: self._config_entry.options.get(CONF_IMMICH_API_KEY, ""),
                    CONF_IMMICH_REFRESH_INTERVAL: self._config_entry.options.get(CONF_IMMICH_REFRESH_INTERVAL, 60),
                    CONF_IMMICH_BATCH_SIZE: self._config_entry.options.get(CONF_IMMICH_BATCH_SIZE, 30),
                    CONF_SLIDESHOW_INTERVAL: self._config_entry.options.get(CONF_SLIDESHOW_INTERVAL, 1),
                },
            ),
            errors=errors,
        )

    async def async_step_immich_albums(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            album_ids = user_input.get(CONF_IMMICH_ALBUM_IDS, [])
            data = {**self._pending_options}
            if album_ids:
                data[CONF_IMMICH_ALBUM_IDS] = album_ids
            else:
                data.pop(CONF_IMMICH_ALBUM_IDS, None)
            return self.async_create_entry(title="", data=data)

        existing_ids = self._config_entry.options.get(CONF_IMMICH_ALBUM_IDS, [])
        schema = vol.Schema({
            vol.Optional(CONF_IMMICH_ALBUM_IDS): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=a["id"], label=a["albumName"])
                        for a in self._pending_albums
                    ],
                    multiple=True,
                )
            ),
        })

        return self.async_show_form(
            step_id="immich_albums",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {CONF_IMMICH_ALBUM_IDS: existing_ids},
            ),
        )
