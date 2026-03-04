DOMAIN = "ha_smart_display"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_PHOTO_URLS = "photo_urls"
CONF_CAMERA_ENTITIES = "camera_entities"

DEFAULT_PORT = 8472
PAIRING_TIMEOUT = 30

WAKE_WORD_OPTIONS = ["hey_alexa", "hey_jarvis", "hey_ziggy", "alexa"]
AMBIENT_MODE_OPTIONS = ["clock", "weather", "cameras"]

# Dispatcher signals
SIGNAL_STATE_UPDATED = f"{DOMAIN}_state_updated_{{device_id}}"
SIGNAL_AVAILABILITY_UPDATED = f"{DOMAIN}_availability_updated_{{device_id}}"

# Services
SERVICE_SET_TIMER = "set_timer"
SERVICE_DISMISS_TIMER = "dismiss_timer"
SERVICE_SET_ALARM = "set_alarm"
SERVICE_DISMISS_ALARM = "dismiss_alarm"
SERVICE_SET_PHOTOS = "set_photos"
SERVICE_SEND_NOTIFICATION = "send_notification"
SERVICE_OPEN_CAMERA = "open_camera"
