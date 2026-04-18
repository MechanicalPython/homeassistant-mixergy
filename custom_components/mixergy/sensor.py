from __future__ import annotations

import logging
import asyncio
from typing import Optional
import aiohttp
from datetime import timedelta, datetime
from homeassistant.const import UnitOfPower, UnitOfTemperature, PERCENTAGE, STATE_OFF
from homeassistant.core import HomeAssistant, callback
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.components.integration.sensor import IntegrationSensor
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator, UpdateFailed

from .tank import Tank
from .mixergy_entity import MixergyEntityBase
from .heat_loss import HeatLossCalculator, TankSample

from .const import (
    DOMAIN,
    ATTR_AMBIENT_TEMP_C,
    ATTR_LAST_IDLE_WINDOW,
    ATTR_ROLLING_AVG_W,
    ATTR_U_VALUE,
    CONF_AMBIENT_ENTITY,
    CONF_SERIAL,
    CONF_TANK_LITRES,
    CONF_TANK_SURFACE_M2,
    DEFAULT_TANK_LITRES,
    DEFAULT_TANK_SURFACE_M2,
    DOMAIN,
    IDLE_WINDOW_SECONDS,
    MIN_TEMP_DROP_K,
    MIXERGY_API_BASE,
    SCAN_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    _LOGGER.info("Setting up entry based on user config")

    entry = hass.data[DOMAIN][config_entry.entry_id]
    tank = entry["tank"]
    coordinator = entry["coordinator"]

    new_entities = []

    new_entities.append(HotWaterTemperatureSensor(coordinator, tank))
    new_entities.append(ColdestWaterTemperatureSensor(coordinator, tank))
    new_entities.append(ChargeSensor(coordinator, tank))
    new_entities.append(TargetChargeSensor(coordinator, tank))
    new_entities.append(ElectricHeatSensor(coordinator, tank))
    new_entities.append(IndirectHeatSensor(coordinator, tank))
    new_entities.append(HeatPumpHeatSensor(coordinator, tank))
    new_entities.append(LowChargeSensor(coordinator, tank))
    new_entities.append(NoChargeSensor(coordinator, tank))
    new_entities.append(PowerSensor(coordinator, tank))
    new_entities.append(EnergySensor(hass, tank))
    new_entities.append(TargetTemperatureSensor(coordinator, tank))
    new_entities.append(HolidayModeSensor(coordinator, tank))
    new_entities.append(PVPowerSensor(coordinator, tank))
    new_entities.append(PVEnergySensor(hass, tank))
    new_entities.append(ClampPowerSensor(coordinator, tank))
    new_entities.append(IsChargingSensor(coordinator, tank))
    new_entities.append(HolidayStartDateSensor(coordinator, tank))
    new_entities.append(HolidayEndDateSensor(coordinator, tank))
    new_entities.append(DefaultHeatSourceSensor(coordinator, tank))

    async_add_entities(new_entities)


class SensorBase(MixergyEntityBase, SensorEntity):

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)


class BinarySensorBase(MixergyEntityBase, BinarySensorEntity):

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)


class ChargeSensor(SensorBase):

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.serial_number}_charge"

    @property
    def unit_of_measurement(self):
        return PERCENTAGE

    @property
    def state(self):
        return self._tank.charge

    @property
    def icon(self):
        return "hass:water-percent"

    @property
    def name(self):
        return f"Current Charge"


class TargetChargeSensor(SensorBase):

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.serial_number}_target_charge"

    @property
    def unit_of_measurement(self):
        return PERCENTAGE

    @property
    def state(self):
        return self._tank.target_charge

    @property
    def icon(self):
        return "hass:water-percent"

    @property
    def name(self):
        return f"Target Charge"


class HotWaterTemperatureSensor(SensorBase):
    device_class = SensorDeviceClass.TEMPERATURE

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.serial_number}_hot_water_temperature"

    @property
    def state(self):
        return self._tank.hot_water_temperature

    @property
    def unit_of_measurement(self):
        return UnitOfTemperature.CELSIUS

    @property
    def name(self):
        return f"Hot Water Temperature"


class ColdestWaterTemperatureSensor(SensorBase):
    device_class = SensorDeviceClass.TEMPERATURE

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.serial_number}_coldest_water_temperature"

    @property
    def state(self):
        return self._tank.coldest_water_temperature

    @property
    def unit_of_measurement(self):
        return UnitOfTemperature.CELSIUS

    @property
    def name(self):
        return f"Coldest Water Temperature"


class TargetTemperatureSensor(SensorBase):
    device_class = SensorDeviceClass.TEMPERATURE

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.serial_number}_target_temperature"

    @property
    def state(self):
        return self._tank.target_temperature

    @property
    def unit_of_measurement(self):
        return UnitOfTemperature.CELSIUS

    @property
    def name(self):
        return f"Target Temperature"


class IndirectHeatSensor(BinarySensorBase):
    device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.serial_number}_indirect_heat"

    @property
    def is_on(self):
        return self._tank.indirect_heat_source

    @property
    def icon(self):
        return "mdi:fire"

    @property
    def name(self):
        return f"Indirect Heat"


class ElectricHeatSensor(BinarySensorBase):
    device_class = SensorDeviceClass.ENERGY

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)
        self._state = STATE_OFF

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.tank_id}_electic_heat"

    @property
    def is_on(self):
        return self._tank.electic_heat_source

    @property
    def name(self):
        return f"Electric Heat"


class HeatPumpHeatSensor(BinarySensorBase):
    device_class = SensorDeviceClass.ENERGY

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)
        self._state = STATE_OFF

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.tank_id}_heatpump_heat"

    @property
    def is_on(self):
        return self._tank.heatpump_heat_source

    @property
    def name(self):
        return f"HeatPump Heat"


class NoChargeSensor(BinarySensorBase):

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)
        self._state = STATE_OFF

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.tank_id}_no_charge"

    @property
    def is_on(self):
        return self._tank.charge < 0.5

    @property
    def icon(self):
        return "hass:water-remove-outline"

    @property
    def name(self):
        return f"No Hot Water"


class LowChargeSensor(BinarySensorBase):

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)
        self._state = STATE_OFF

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.tank_id}_low_charge"

    @property
    def is_on(self):
        return self._tank.charge < 5

    @property
    def icon(self):
        return "hass:water-percent-alert"

    @property
    def name(self):
        return f"Low Hot Water"


class IsChargingSensor(BinarySensorBase):

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)
        self._state = STATE_OFF

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.tank_id}_charging"

    @property
    def is_on(self):
        return self._tank.target_charge > 0

    @property
    def icon(self):
        return "hass:water-percent-alert"

    @property
    def name(self):
        return f"Is Charging"


class PowerSensor(SensorBase):
    device_class = SensorDeviceClass.POWER
    state_class = "measurement"

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)
        self._state = 0

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.tank_id}_power"

    @property
    def state(self):
        return 3300 if self._tank.electic_heat_source else 0

    @property
    def unit_of_measurement(self):
        return UnitOfPower.WATT

    @property
    def name(self):
        return f"Mixergy Electric Heat Power"


class EnergySensor(IntegrationSensor):

    def __init__(self, hass: HomeAssistant, tank: Tank):
        super().__init__(
            hass=hass,
            name="Mixergy Electric Heat Energy",
            source_entity="sensor.mixergy_electric_heat_power",
            round_digits=2,
            unit_prefix="k",
            unit_time="h",
            integration_method="left",
            unique_id=f"mixergy_{tank.tank_id}_energy",
            max_sub_interval=None
        )

    @property
    def icon(self):
        return "mdi:lightning-bolt"


class PVPowerSensor(SensorBase):
    device_class = SensorDeviceClass.POWER
    state_class = "measurement"

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)
        self._state = 0

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.tank_id}_pv_power"

    @property
    def state(self):
        return self._tank.pv_power

    @property
    def unit_of_measurement(self):
        return UnitOfPower.KILO_WATT

    @property
    def name(self):
        return f"Mixergy Electric PV Power"

    @property
    def available(self):
        return super().available and self._tank.has_pv_diverter


class PVEnergySensor(IntegrationSensor):

    def __init__(self, hass: HomeAssistant, tank: Tank):
        super().__init__(
            hass=hass,
            name="Mixergy Electric PV Energy",
            source_entity="sensor.mixergy_electric_pv_power",
            round_digits=2,
            unit_prefix=None,  # PVPowerSensor is already in kW
            unit_time="h",
            integration_method="left",
            unique_id=f"mixergy_{tank.tank_id}_pv_energy",
            max_sub_interval=None
        )
        self._tank = tank

    @property
    def icon(self):
        return "mdi:lightning-bolt"

    @property
    def available(self):
        return self._tank.online and self._tank.has_pv_diverter


class ClampPowerSensor(SensorBase):
    device_class = SensorDeviceClass.POWER
    state_class = "measurement"

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)
        self._state = 0

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.tank_id}_clamp_power"

    @property
    def state(self):
        return self._tank.clamp_power

    @property
    def unit_of_measurement(self):
        return UnitOfPower.WATT

    @property
    def name(self):
        return f"Clamp Power"

    @property
    def available(self):
        return super().available and self._tank.has_pv_diverter


class HolidayModeSensor(BinarySensorBase):

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)
        self._state = STATE_OFF

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.tank_id}_holiday_mode"

    @property
    def is_on(self):
        return self._tank.in_holiday_mode

    @property
    def icon(self):
        return "mdi:airplane-takeoff"

    @property
    def name(self):
        return f"Holiday Mode"


class HolidayStartDateSensor(SensorBase):
    device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)
        self._state = None

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.tank_id}_holiday_date_start"

    @property
    def state(self):
        return self._tank.holiday_date_start

    @property
    def name(self):
        return f"Holiday Date Start"


class HolidayEndDateSensor(SensorBase):
    device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)
        self._state = None

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.tank_id}_holiday_date_end"

    @property
    def state(self):
        return self._tank.holiday_date_end

    @property
    def name(self):
        return f"Holiday Date End"


class DefaultHeatSourceSensor(SensorBase):
    device_class = SensorDeviceClass.ENUM

    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)
        self._state = None

    @property
    def unique_id(self):
        return f"mixergy_{self._tank.tank_id}_default_heat_source"

    @property
    def state(self):
        return self._tank.default_heat_source

    @property
    def name(self):
        return f"Default Heat Source"


class MixergyHeatLossSensor(CoordinatorEntity, SensorEntity):
    """Instantaneous passive heat loss in Watts."""

    _attr_name = "Mixergy Passive Heat Loss"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-thermometer-outline"

    def __init__(self, coordinator, serial: str, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._serial = serial
        self._attr_unique_id = f"{DOMAIN}_{serial}_heat_loss_w"

    @property
    def native_value(self):
        result = self.coordinator.data.get("result")
        return result.power_watts if result else None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        result = data.get("result")
        attrs = {
            ATTR_ROLLING_AVG_W: data.get("rolling_avg"),
            ATTR_AMBIENT_TEMP_C: data.get("ambient_c"),
        }
        if result:
            attrs[ATTR_LAST_IDLE_WINDOW] = result.delta_time_s
            attrs[ATTR_U_VALUE] = result.u_value_w_m2_k
        return attrs


class MixergyUValueSensor(CoordinatorEntity, SensorEntity):
    """Estimated tank insulation U-value (W/m²·K)."""

    _attr_name = "Mixergy Tank U-value"
    _attr_native_unit_of_measurement = "W/m²·K"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer-lines"

    def __init__(self, coordinator, serial: str, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._serial = serial
        self._attr_unique_id = f"{DOMAIN}_{serial}_u_value"

    @property
    def native_value(self):
        result = self.coordinator.data.get("result")
        return result.u_value_w_m2_k if result else None
