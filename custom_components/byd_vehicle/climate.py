"""Climate control for BYD Vehicle."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pybyd.models.vehicle import Vehicle

from .const import (
    CONF_CLIMATE_DURATION,
    DEFAULT_CLIMATE_DURATION,
    DOMAIN,
)
from .coordinator import BydDataUpdateCoordinator
from .entity import BydActionEntity

# controlParamsMap ``cycleMode``: 1 = fresh (outside) air, 2 = recirculate.
_CYCLE_FRESH_AIR = 1
_CYCLE_RECIRCULATE = 2


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BYD climate entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[str, BydDataUpdateCoordinator] = data["coordinators"]
    climate_duration = entry.options.get(
        CONF_CLIMATE_DURATION,
        DEFAULT_CLIMATE_DURATION,
    )

    entities: list[ClimateEntity] = []

    for vin, coordinator in coordinators.items():
        if not coordinator.capability_available("climate"):
            continue
        entities.append(
            BydClimate(coordinator, vin, coordinator.vehicle, climate_duration)
        )

    async_add_entities(entities)


class BydClimate(BydActionEntity, ClimateEntity):
    """Representation of BYD climate control.

    Reads state from ``VehicleSnapshot.hvac``.  Commands go through
    ``car.hvac.start()`` / ``car.hvac.stop()`` which handle
    projections, guard windows, and reconcile internally.
    """

    # fallback when the car hasn't reported its range, see pyBYD#74
    _DEFAULT_TEMP_RANGE_C = (15.0, 31.0)
    _PRESET_MAX_HEAT = "max_heat"
    _PRESET_MAX_COOL = "max_cool"
    _DEFAULT_TEMP_C = 21.0

    _attr_has_entity_name = True
    _attr_translation_key = "climate"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    # pre-2026.11 HA only reads the non-native names; HA 2026.11 serves the
    # native ones without a deprecation warning when a class sets both
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
    )
    _attr_target_temperature_step = 1
    _attr_preset_modes = [_PRESET_MAX_HEAT, _PRESET_MAX_COOL]

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
        climate_duration: int = DEFAULT_CLIMATE_DURATION,
    ) -> None:
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle = vehicle
        self._climate_duration = climate_duration
        self._attr_unique_id = f"{vin}_climate"

    @property
    def _temp_range(self) -> tuple[float, float]:
        """Settable range in °C, as reported by the car (eg 17-33 on the HAN)."""
        car = self.coordinator.car
        if car is None:
            return self._DEFAULT_TEMP_RANGE_C
        return car.hvac.temp_range

    @property
    def min_temp(self) -> float:
        """Return the minimum settable temperature."""
        return self._temp_range[0]

    @property
    def max_temp(self) -> float:
        """Return the maximum settable temperature."""
        return self._temp_range[1]

    def _clamp_temp(self, temp_c: float | int | None) -> float | None:
        """Return the temperature if it's within the valid range, else None."""
        if temp_c is None:
            return None
        val = float(temp_c)
        temp_min, temp_max = self._temp_range
        if temp_min <= val <= temp_max:
            return val
        return None

    def _preset_from_temp(self, temp_c: float | None) -> str | None:
        """Return a preset name if the temperature matches a boundary."""
        if temp_c is None:
            return None
        rounded = round(temp_c)
        temp_min, temp_max = self._temp_range
        if rounded >= temp_max:
            return self._PRESET_MAX_HEAT
        if rounded <= temp_min:
            return self._PRESET_MAX_COOL
        return None

    # ------------------------------------------------------------------
    # State properties — read from VehicleSnapshot
    # ------------------------------------------------------------------

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode."""
        hvac = self._get_hvac_status()
        if hvac is not None:
            return HVACMode.HEAT_COOL if hvac.is_ac_on else HVACMode.OFF
        return HVACMode.OFF

    @property
    def assumed_state(self) -> bool:
        """Return True when state is assumed (no HVAC data)."""
        return self._get_hvac_status() is None

    @property
    def native_current_temperature(self) -> float | None:
        """Return the current interior temperature."""
        hvac = self._get_hvac_status()
        if hvac is not None and hvac.interior_temp_available:
            return hvac.temp_in_car
        realtime = self._get_realtime()
        if realtime is not None:
            temp = getattr(realtime, "temp_in_car", None)
            if temp is not None:
                return temp
        return None

    @property
    def native_target_temperature(self) -> float | None:
        """Return the target temperature."""
        hvac = self._get_hvac_status()
        if hvac is not None:
            temp_c = self._clamp_temp(hvac.main_setting_temp_new)
            if temp_c is not None:
                return temp_c
        temp_min, temp_max = self._temp_range
        return max(temp_min, min(temp_max, self._DEFAULT_TEMP_C))

    current_temperature = native_current_temperature
    target_temperature = native_target_temperature

    @property
    def preset_mode(self) -> str | None:
        """Return the active preset mode, if any."""
        hvac = self._get_hvac_status()
        if hvac is not None and hvac.is_ac_on:
            temp_c = self._clamp_temp(hvac.main_setting_temp_new)
            if temp_c is not None:
                return self._preset_from_temp(temp_c)
        return None

    # ------------------------------------------------------------------
    # Commands — delegate to BydCar.hvac
    # ------------------------------------------------------------------

    def _start_climate(self, car: Any, temperature: float) -> Any:
        """Return the coroutine that starts climate with our air source.

        Fresh air (the fresh-air switch) helps clear fogged windows; BYD's
        remote start otherwise recirculates.  Older pyBYD versions have no
        ``cycle_mode`` argument, so they always recirculate.
        """
        cycle_mode = (
            _CYCLE_FRESH_AIR
            if getattr(self.coordinator, "climate_fresh_air", False)
            else _CYCLE_RECIRCULATE
        )
        try:
            return car.hvac.start(
                temperature=temperature,
                duration=self._climate_duration,
                cycle_mode=cycle_mode,
            )
        except TypeError:
            if cycle_mode == _CYCLE_RECIRCULATE:
                return car.hvac.start(
                    temperature=temperature,
                    duration=self._climate_duration,
                )
            return _start_with_cycle_mode(
                car.hvac, temperature, self._climate_duration, cycle_mode
            )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode (on/off)."""
        car = self.coordinator.car
        if car is None:
            return
        if hvac_mode == HVACMode.OFF:
            await self._execute_car_command(
                car.hvac.stop(),
                command="stop_climate",
            )
        else:
            temp = self.target_temperature or self._DEFAULT_TEMP_C
            await self._execute_car_command(
                self._start_climate(car, temp),
                command="start_climate",
            )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        self._ensure_action_allowed()
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        temp_min, temp_max = self._temp_range
        clamped = max(temp_min, min(temp_max, float(temp)))

        # If climate is currently on, send the update immediately
        if self.hvac_mode != HVACMode.OFF:
            car = self.coordinator.car
            if car is None:
                return
            await self._execute_car_command(
                self._start_climate(car, clamped),
                command="start_climate",
            )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Activate a preset mode."""
        self._ensure_action_allowed()
        if preset_mode not in self._attr_preset_modes:
            raise HomeAssistantError(f"Unsupported preset mode: {preset_mode}")
        temp_min, temp_max = self._temp_range
        temp_c = temp_max if preset_mode == self._PRESET_MAX_HEAT else temp_min
        car = self.coordinator.car
        if car is None:
            return
        await self._execute_car_command(
            self._start_climate(car, temp_c),
            command="start_climate",
        )

    # ------------------------------------------------------------------
    # Extra attributes
    # ------------------------------------------------------------------

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional HVAC attributes."""
        attrs = {**super().extra_state_attributes}
        hvac = self._get_hvac_status()
        if hvac is not None:
            attrs["exterior_temperature"] = hvac.temp_out_car
            attrs["passenger_set_temperature"] = hvac.copilot_setting_temp_new
            attrs["fan_speed"] = hvac.wind_position
            attrs["airflow_direction"] = hvac.wind_mode
            attrs["recirculation"] = hvac.cycle_choice
            attrs["front_defrost"] = hvac.front_defrost_status
            attrs["rear_defrost"] = hvac.electric_defrost_status
            attrs["wiper_heat"] = hvac.wiper_heat_status
            attrs["pm25"] = hvac.pm
            attrs["pm25_exterior_state"] = hvac.pm25_state_out_car
            attrs["rapid_heating"] = hvac.rapid_increase_temp_state
            attrs["rapid_cooling"] = hvac.rapid_decrease_temp_state
        return attrs


async def _start_with_cycle_mode(
    hvac: Any, temperature: float, duration: int, cycle_mode: int
) -> None:
    """``HvacCapability.start`` with a ``cycleMode``, for pyBYD <= 0.0.79.

    Same steps as pyBYD's own ``start`` (availability check, projections,
    command through ``_execute``); only ``cycle_mode`` is added to the
    params.  Drop this once pyBYD's ``start`` takes ``cycle_mode``.
    """
    from pybyd._constants import minutes_to_time_span
    from pybyd._state_engine import ProjectionSpec
    from pybyd.models.control import ClimateStartParams
    from pybyd.models.hvac import HvacOverallStatus

    hvac._ensure_available()
    params = ClimateStartParams(
        temperature=temperature,
        time_span=minutes_to_time_span(duration),
        temp_offset=hvac.temp_offset,
        cycle_mode=cycle_mode,
    )
    specs = [
        ProjectionSpec("hvac", "status", HvacOverallStatus.ON),
        ProjectionSpec("hvac", "main_setting_temp_new", temperature),
    ]

    async def _cmd() -> Any:
        return await hvac._start_fn(hvac._vin, params=params)

    await hvac._execute(_cmd, specs)
