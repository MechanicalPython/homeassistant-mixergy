# Consts for the Mixergy integration
DOMAIN = "mixergy"

SERVICE_SET_CHARGE = "mixergy_set_charge"
SERVICE_SET_TARGET_TEMPERATURE = "mixergy_set_target_temperature"
SERVICE_SET_HOLIDAY_DATES = "mixergy_set_holiday_dates"
SERVICE_CLEAR_HOLIDAY_DATES = "mixergy_clear_holiday_dates"
SERVICE_SET_DEFAULT_HEAT_SOURCE = "mixergy_set_default_heat_source"

ATTR_CHARGE = "charge"
ATTR_TEMPERATURE = "temperature"
ATTR_START_DATE = "start_date"
ATTR_END_DATE = "end_date"
ATTR_HEAT_SOURCE = "heat_source"

# Mixergy API
MIXERGY_API_BASE = "https://www.mixergy.io/api/v2"

# Tank physical properties
WATER_SPECIFIC_HEAT = 4186      # J/(kg·K)
WATER_DENSITY = 1.0       # kg/litre (approx)
DEFAULT_TANK_LITRES = 180       # litres — override in config

# Tank surface area (m²) — used for U-value estimation
# A typical 180L cylinder is ~0.9m tall, ~0.47m dia → ~1.8 m²
DEFAULT_TANK_SURFACE_M2 = 1.8

# Polling / sampling
SCAN_INTERVAL_SECONDS = 60      # how often to poll Mixergy
IDLE_WINDOW_SECONDS   = 300     # minimum idle period before measuring heat loss
MIN_TEMP_DROP_K       = 0.1     # ignore noise below this threshold (Kelvin)

# Config entry keys
CONF_SERIAL           = "serial_number"
CONF_TANK_LITRES      = "tank_litres"
CONF_TANK_SURFACE_M2  = "tank_surface_m2"
CONF_AMBIENT_ENTITY   = "ambient_temp_entity"

# Attribute keys
ATTR_ROLLING_AVG_W    = "rolling_24h_avg_watts"
ATTR_U_VALUE          = "estimated_u_value_w_m2_k"
ATTR_LAST_IDLE_WINDOW = "last_idle_window_seconds"
ATTR_AMBIENT_TEMP_C   = "ambient_temp_c"