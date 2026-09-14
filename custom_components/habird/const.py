"""Constants for the habird (BirdNET-Go Audubon Clock) integration."""

DOMAIN = "habird"

# Config entry (set once, at setup)
CONF_URL = "url"
CONF_VERIFY_SSL = "verify_ssl"
CONF_API_TOKEN = "api_token"

# Options (editable after setup)
CONF_XENO_CANTO_KEY = "xeno_canto_key"
CONF_MEDIA_PLAYERS = "chime_media_players"
CONF_QUIET_HOURS = "chime_quiet_hours"
CONF_MAX_SECONDS = "chime_max_seconds"
CONF_CLOCK_HOURS = "clock_hours"
CONF_WINDOW_DAYS = "clock_window_days"
CONF_REASSIGN = "clock_reassign"
CONF_HOUR_PINS = "hour_pins"

DEFAULT_WINDOW_DAYS = 30
DEFAULT_MAX_SECONDS = 5
DEFAULT_HYSTERESIS = 0.25
