from __future__ import annotations

import logging
from datetime import timedelta, datetime
from typing import Optional

from homeassistant.const import UnitOfPower, UnitOfTemperature, PERCENTAGE, STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.components.integration.sensor import IntegrationSensor
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .tank import Tank
from .mixergy_entity import MixergyEntityBase
from .heat_loss import HeatLossCalculator, TankSample

from .const import (
    DOMAIN,
    ATTR_AMBIENT_TEMP_C,
    ATTR_LAST_IDLE_WINDOW,
    ATTR_ROLLING_AVG_W,
    ATTR_U_VALUE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    _LOGGER.info("Setting up sensor entry based on user config")

    entry              = hass.data[DOMAIN][config_entry.entry_id]
    tank               = entry["tank"]
    coordinator        = entry["coordinator"]
    hl_coordinator     = entry["heat_loss_coordinator"]

    serial = tank.serial_number

    new_entities = [
        # -- Temperature -------------------------------------------------
        HotWaterTemperatureSensor(coordinator, tank),
        ColdestWaterTemperatureSensor(coordinator, tank),
        TargetTemperatureSensor(coordinator, tank),
        # -- Charge ------------------------------------------------------
        ChargeSensor(coordinator, tank),
        TargetChargeSensor(coordinator, tank),
        # -- Heating state (binary) --------------------------------------
        ElectricHeatSensor(coordinator, tank),
        IndirectHeatSensor(coordinator, tank),
        HeatPumpHeatSensor(coordinator, tank),
        IsChargingSensor(coordinator, tank),
        # -- Charge level alerts (binary) --------------------------------
        LowChargeSensor(coordinator, tank),
        NoChargeSensor(coordinator, tank),
        # -- Power / energy ----------------------------------------------
        PowerSensor(coordinator, tank),
        EnergySensor(hass, tank),
        PVPowerSensor(coordinator, tank),
        PVEnergySensor(hass, tank),
        ClampPowerSensor(coordinator, tank),
        # -- Scheduling / mode -------------------------------------------
        HolidayModeSensor(coordinator, tank),
        HolidayStartDateSensor(coordinator, tank),
        HolidayEndDateSensor(coordinator, tank),
        DefaultHeatSourceSensor(coordinator, tank),
        # -- Heat loss ---------------------------------------------------
        MixergyHeatLossSensor(hl_coordinator, serial, config_entry),
        MixergyRollingHeatLossSensor(hl_coordinator, serial, config_entry),
        MixergyUValueSensor(hl_coordinator, serial, config_entry),
    ]

    async_add_entities(new_entities)


class SensorBase(MixergyEntityBase, SensorEntity):
    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)


class BinarySensorBase(MixergyEntityBase, BinarySensorEntity):
    def __init__(self, coordinator, tank: Tank):
        super().__init__(coordinator, tank)


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
        return "Hot Water Temperature"


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
        return "Coldest Water Temperature"


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
        return "Target Temperature"


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
        return "Current Charge"


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
        return "Target Charge"


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
        return "Indirect Heat"


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
        return "Electric Heat"


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
        return "HeatPump Heat"


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
        return "Is Charging"


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
        return "No Hot Water"


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
        return "Low Hot Water"


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
        return "Mixergy Electric Heat Power"


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
            max_sub_interval=None,
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
        return "Mixergy Electric PV Power"

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
            max_sub_interval=None,
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
        return "Clamp Power"

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
        return "Holiday Mode"


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
        return "Holiday Date Start"


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
        return "Holiday Date End"


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
        return "Default Heat Source"


class _HeatLossSensorBase(CoordinatorEntity, SensorEntity):
    """Base for sensors that read from the heat-loss coordinator."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        serial: str,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._serial = serial
        self._entry  = entry

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._serial)},
        }


class MixergyHeatLossSensor(_HeatLossSensorBase):
    """Instantaneous passive heat loss in Watts, computed over the most
    recent idle window."""

    _attr_name                       = "Mixergy Passive Heat Loss"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class               = SensorDeviceClass.POWER
    _attr_state_class                = SensorStateClass.MEASUREMENT
    _attr_icon                       = "mdi:water-thermometer-outline"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        serial: str,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, serial, entry)
        self._attr_unique_id = f"{DOMAIN}_{serial}_heat_loss_w"

    @property
    def native_value(self) -> Optional[float]:
        result = self.coordinator.data.get("result") if self.coordinator.data else None
        return result.power_watts if result else None

    @property
    def extra_state_attributes(self) -> dict:
        data   = self.coordinator.data or {}
        result = data.get("result")
        attrs  = {
            ATTR_ROLLING_AVG_W: data.get("rolling_avg"),
            ATTR_AMBIENT_TEMP_C: data.get("ambient_c"),
        }
        if result:
            attrs[ATTR_LAST_IDLE_WINDOW] = result.delta_time_s
            attrs[ATTR_U_VALUE]          = result.u_value_w_m2_k
        return attrs


class MixergyRollingHeatLossSensor(_HeatLossSensorBase):
    """24-hour rolling average of passive heat loss in Watts."""

    _attr_name                       = "Mixergy Heat Loss 24h Average"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class               = SensorDeviceClass.POWER
    _attr_state_class                = SensorStateClass.MEASUREMENT
    _attr_icon                       = "mdi:chart-bell-curve"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        serial: str,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, serial, entry)
        self._attr_unique_id = f"{DOMAIN}_{serial}_heat_loss_rolling_avg_w"

    @property
    def native_value(self) -> Optional[float]:
        data = self.coordinator.data or {}
        return data.get("rolling_avg")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {ATTR_AMBIENT_TEMP_C: data.get("ambient_c")}


class MixergyUValueSensor(_HeatLossSensorBase):
    """Estimated effective tank insulation U-value in W/m²·K.

    Only available when an ambient temperature entity has been configured.
    """

    _attr_name                       = "Mixergy Tank U-value"
    _attr_native_unit_of_measurement = "W/m²·K"
    _attr_state_class                = SensorStateClass.MEASUREMENT
    _attr_icon                       = "mdi:thermometer-lines"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        serial: str,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, serial, entry)
        self._attr_unique_id = f"{DOMAIN}_{serial}_u_value"

    @property
    def native_value(self) -> Optional[float]:
        data   = self.coordinator.data or {}
        result = data.get("result")
        return result.u_value_w_m2_k if result else None

    @property
    def extra_state_attributes(self) -> dict:
        data   = self.coordinator.data or {}
        result = data.get("result")
        attrs  = {ATTR_AMBIENT_TEMP_C: data.get("ambient_c")}
        if result:
            attrs[ATTR_LAST_IDLE_WINDOW] = result.delta_time_s
        return attrs