DOMAIN = "ha_smart_display"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_PHOTO_URLS = "photo_urls"
CONF_CAMERA_ENTITIES = "camera_entities"
CONF_CLIMATE_ENTITY = "climate_entity"
CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_HUMIDITY_SENSOR = "humidity_sensor"
CONF_AUTO_AMBIENT_LUX = "auto_ambient_lux"
CONF_MA_MEDIA_PLAYER = "ma_media_player"
CONF_IMMICH_URL = "immich_url"
CONF_IMMICH_API_KEY = "immich_api_key"
CONF_IMMICH_ALBUM_IDS = "immich_album_ids"
CONF_IMMICH_REFRESH_INTERVAL = "immich_refresh_interval"  # minutes, default 60
CONF_IMMICH_BATCH_SIZE = "immich_batch_size"              # photos per refresh, default 30
CONF_SLIDESHOW_INTERVAL = "slideshow_interval"            # minutes, default 1

DEFAULT_PORT = 8472
PAIRING_TIMEOUT = 30

WAKE_WORD_OPTIONS = ["alexa", "hey_jarvis", "okay_nabu", "hey_mycroft"]
WAKE_WORD_SENSITIVITY_OPTIONS = ["low", "medium", "high"]
VAD_SENSITIVITY_OPTIONS = ["default", "relaxed", "aggressive"]
AMBIENT_MODE_OPTIONS = ["clock", "weather", "cameras", "music"]

# Dispatcher signals
SIGNAL_STATE_UPDATED = f"{DOMAIN}_state_updated_{{device_id}}"
SIGNAL_AVAILABILITY_UPDATED = f"{DOMAIN}_availability_updated_{{device_id}}"
SIGNAL_ASSIST_STATE_UPDATED = f"{DOMAIN}_assist_state_updated_{{device_id}}"

# Media player states (as reported by device)
MEDIA_STATE_IDLE = "idle"
MEDIA_STATE_BUFFERING = "buffering"
MEDIA_STATE_PLAYING = "playing"
MEDIA_STATE_PAUSED = "paused"

# Services
SERVICE_SET_TIMER = "set_timer"
SERVICE_DISMISS_TIMER = "dismiss_timer"
SERVICE_SET_ALARM = "set_alarm"
SERVICE_DISMISS_ALARM = "dismiss_alarm"
SERVICE_SET_PHOTOS = "set_photos"
SERVICE_SEND_NOTIFICATION = "send_notification"
SERVICE_OPEN_CAMERA = "show_camera_stream"
SERVICE_CLOSE_CAMERA = "close_camera_stream"
SERVICE_ADD_PILL = "add_pill"
SERVICE_REMOVE_PILL = "remove_pill"
SERVICE_DISMISS_ALL_PILLS = "dismiss_all_pills"
SERVICE_GET_PILLS = "get_pills"
SERVICE_GET_TIMERS = "get_timers"
SERVICE_DISMISS_ALL_TIMERS = "dismiss_all_timers"
SERVICE_GET_ALARMS = "get_alarms"
SERVICE_DISMISS_ALL_ALARMS = "dismiss_all_alarms"
