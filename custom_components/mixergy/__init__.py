from .const import (
    ATTR_CHARGE,
    ATTR_TEMPERATURE,
    ATTR_HEAT_SOURCE,
    ATTR_START_DATE,
    ATTR_END_DATE,
    SERVICE_SET_HOLIDAY_DATES,
    SERVICE_CLEAR_HOLIDAY_DATES,
    SERVICE_SET_DEFAULT_HEAT_SOURCE,
    SERVICE_SET_TARGET_TEMPERATURE,
    SERVICE_SET_CHARGE,
    CONF_AMBIENT_ENTITY,
    CONF_TANK_LITRES,
    CONF_TANK_SURFACE_M2,
    DEFAULT_TANK_LITRES,
    DEFAULT_TANK_SURFACE_M2,
    IDLE_WINDOW_SECONDS,
    MIN_TEMP_DROP_K,
    DOMAIN,
)
from datetime import datetime, timedelta, timezone
import logging
import asyncio
import voluptuous as vol
from homeassistant import core
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.config_validation import make_entity_service_schema
from homeassistant.helpers.service import verify_domain_control
from homeassistant.helpers.event import async_track_state_change_event
from .tank import Tank
from .heat_loss import HeatLossCalculator, TankSample
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config):
    _LOGGER.info("Setting up mixergy tank...")
    hass.data[DOMAIN] = {}
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a tank from a config entry."""

    tank = Tank(
        hass,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data["serial_number"],
    )

    # ------------------------------------------------------------------
    # Main data coordinator — polls the Mixergy API every 30 s
    # ------------------------------------------------------------------

    async def async_update_data():
        _LOGGER.info("Fetching data from Mixergy...")
        await tank.fetch_data()

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Mixergy",
        update_method=async_update_data,
        update_interval=timedelta(seconds=30),
    )
    await coordinator.async_config_entry_first_refresh()

    # ------------------------------------------------------------------
    # Heat-loss calculator — one instance per config entry
    # ------------------------------------------------------------------

    tank_litres     = entry.data.get(CONF_TANK_LITRES,     DEFAULT_TANK_LITRES)
    tank_surface_m2 = entry.data.get(CONF_TANK_SURFACE_M2, DEFAULT_TANK_SURFACE_M2)
    ambient_entity  = entry.data.get(CONF_AMBIENT_ENTITY,  "")

    heat_loss_calc = HeatLossCalculator(
        tank_litres=tank_litres,
        tank_surface_m2=tank_surface_m2,
    )

    def _get_ambient_temp() -> float | None:
        """Read the current ambient temperature from a HA sensor entity."""
        if not ambient_entity:
            return None
        state = hass.states.get(ambient_entity)
        if state is None:
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    # Heat-loss coordinator — runs after every main coordinator refresh
    async def async_update_heat_loss():
        """Feed the latest sample into the calculator and return results."""
        # Only calculate when the tank has valid temperature readings
        if tank.hot_water_temperature < 0 or tank.coldest_water_temperature < 0:
            _LOGGER.debug("Skipping heat-loss calculation: temperatures not yet available")
            return {"result": None, "rolling_avg": None, "ambient_c": None}

        sample = TankSample(
            timestamp     = datetime.now(tz=timezone.utc),
            temp_top_c    = tank.hot_water_temperature,
            temp_bottom_c = tank.coldest_water_temperature,
            charge_pct    = tank.charge,
        )
        heat_loss_calc.add_sample(sample)

        ambient_c = _get_ambient_temp()

        result = heat_loss_calc.calculate(
            idle_window_seconds=IDLE_WINDOW_SECONDS,
            min_temp_drop_k=MIN_TEMP_DROP_K,
            ambient_temp_c=ambient_c,
        )

        return {
            "result":      result,
            "rolling_avg": heat_loss_calc.rolling_average_watts,
            "ambient_c":   ambient_c,
        }

    heat_loss_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Mixergy Heat Loss",
        update_method=async_update_heat_loss,
        # Run slightly after the main coordinator so data is fresh
        update_interval=timedelta(seconds=32),
    )

    # Trigger the heat-loss coordinator whenever the main one finishes
    async def _on_main_coordinator_update(event=None):
        await heat_loss_coordinator.async_refresh()

    entry.async_on_unload(
        coordinator.async_add_listener(_on_main_coordinator_update)
    )

    await heat_loss_coordinator.async_config_entry_first_refresh()

    # ------------------------------------------------------------------
    # Store everything in hass.data for the platform modules to access
    # ------------------------------------------------------------------

    hass.data[DOMAIN][entry.entry_id] = {
        "tank":                  tank,
        "coordinator":           coordinator,
        "heat_loss_coordinator": heat_loss_coordinator,
        "heat_loss_calc":        heat_loss_calc,
    }

    _register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


# ---------------------------------------------------------------------------
# Service registration
# ---------------------------------------------------------------------------

@core.callback
def _register_services(hass):
    """Register all Mixergy custom services with Home Assistant."""

    @verify_domain_control(DOMAIN)
    async def mixergy_set_charge(call):
        charge = call.data[ATTR_CHARGE]
        tasks = [
            tank.set_target_charge(charge)
            for tank in [d["tank"] for d in hass.data[DOMAIN].values()]
            if isinstance(tank, Tank)
        ]
        results = await asyncio.gather(*tasks)
        if None not in results:
            _LOGGER.warning("The request to charge the tank did not succeed")

    @verify_domain_control(DOMAIN)
    async def mixergy_set_target_temperature(call):
        temperature = call.data[ATTR_TEMPERATURE]
        tasks = [
            tank.set_target_temperature(temperature)
            for tank in [d["tank"] for d in hass.data[DOMAIN].values()]
            if isinstance(tank, Tank)
        ]
        results = await asyncio.gather(*tasks)
        if None not in results:
            _LOGGER.warning(
                "The request to change the target temperature of the tank did not succeed"
            )

    @verify_domain_control(DOMAIN)
    async def mixergy_set_holiday_dates(call):
        start_date = call.data[ATTR_START_DATE]
        end_date   = call.data[ATTR_END_DATE]
        tasks = [
            tank.set_holiday_dates(start_date, end_date)
            for tank in [d["tank"] for d in hass.data[DOMAIN].values()]
            if isinstance(tank, Tank)
        ]
        results = await asyncio.gather(*tasks)
        if None not in results:
            _LOGGER.warning(
                "The request to change the holiday dates of the tank did not succeed"
            )

    @verify_domain_control(DOMAIN)
    async def mixergy_clear_holiday_dates(call):
        tasks = [
            tank.clear_holiday_dates()
            for tank in [d["tank"] for d in hass.data[DOMAIN].values()]
            if isinstance(tank, Tank)
        ]
        results = await asyncio.gather(*tasks)
        if None not in results:
            _LOGGER.warning(
                "The request to clear the holiday dates of the tank did not succeed"
            )

    @verify_domain_control(DOMAIN)
    async def mixergy_set_default_heat_source(call):
        heat_source = call.data[ATTR_HEAT_SOURCE]
        tasks = [
            tank.set_default_heat_source(heat_source)
            for tank in [d["tank"] for d in hass.data[DOMAIN].values()]
            if isinstance(tank, Tank)
        ]
        results = await asyncio.gather(*tasks)
        if None not in results:
            _LOGGER.warning(
                "The request to set the default heat source of the tank did not succeed"
            )

    if not hass.services.has_service(DOMAIN, SERVICE_SET_CHARGE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_CHARGE,
            mixergy_set_charge,
            schema=vol.Schema({vol.Required(ATTR_CHARGE): cv.positive_int}),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_SET_TARGET_TEMPERATURE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_TARGET_TEMPERATURE,
            mixergy_set_target_temperature,
            schema=vol.Schema({vol.Required(ATTR_TEMPERATURE): cv.positive_int}),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_SET_HOLIDAY_DATES):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_HOLIDAY_DATES,
            mixergy_set_holiday_dates,
            schema=vol.Schema(
                {
                    vol.Required(ATTR_START_DATE): cv.datetime,
                    vol.Required(ATTR_END_DATE):   cv.datetime,
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_CLEAR_HOLIDAY_DATES):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_HOLIDAY_DATES,
            mixergy_clear_holiday_dates,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_SET_DEFAULT_HEAT_SOURCE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_DEFAULT_HEAT_SOURCE,
            mixergy_set_default_heat_source,
            schema=vol.Schema({vol.Required(ATTR_HEAT_SOURCE): cv.string}),
        )