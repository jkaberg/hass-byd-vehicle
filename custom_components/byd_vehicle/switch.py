"""Switches for BYD Vehicle."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from pybyd.models.vehicle import Vehicle

from .const import DOMAIN
from .coordinator import BydDataUpdateCoordinator
from .entity import BydActionEntity, BydVehicleEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BYD switches from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[str, BydDataUpdateCoordinator] = data["coordinators"]
    gps_coordinators = data.get("gps_coordinators", {})

    entities: list[SwitchEntity] = []
    for vin, coordinator in coordinators.items():
        gps_coordinator = gps_coordinators.get(vin)
        vehicle = coordinator.vehicle
        entities.append(
            BydDisablePollingSwitch(coordinator, gps_coordinator, vin, vehicle)
        )
        if coordinator.capability_available("car_on"):
            entities.append(BydCarOnSwitch(coordinator, vin, vehicle))
        if coordinator.capability_available("battery_heat"):
            entities.append(BydBatteryHeatSwitch(coordinator, vin, vehicle))
        if coordinator.capability_available("steering_wheel_heat"):
            entities.append(BydSteeringWheelHeatSwitch(coordinator, vin, vehicle))

        entities.append(BydScheduleEnabledSwitch(coordinator, vin, vehicle))
        entities.append(BydChargeToFullSwitch(coordinator, vin, vehicle))
        entities.append(BydRepeatDailySwitch(coordinator, vin, vehicle))

    async_add_entities(entities)


class BydBatteryHeatSwitch(BydActionEntity, SwitchEntity):
    """Representation of the BYD battery heat toggle.

    Reads state from ``VehicleSnapshot.realtime.is_battery_heating``.
    Commands go through ``car.battery.heat(on=True/False)`` which
    handles projections internally.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "battery_heat"
    _attr_icon = "mdi:heat-wave"

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_switch_battery_heat"

    @property
    def is_on(self) -> bool | None:
        """Return whether battery heat is on."""
        realtime = self._get_realtime()
        if realtime is not None:
            heating = realtime.is_battery_heating
            if heating is not None:
                return heating
        return None

    @property
    def assumed_state(self) -> bool:
        """Return True if we have no realtime data."""
        realtime = self._get_realtime()
        if realtime is not None:
            return getattr(realtime, "battery_heat_state", None) is None
        return True

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Turn on battery heat."""
        car = self.coordinator.car
        if car is None:
            return
        await self._execute_car_command(
            car.battery.heat(on=True),
            command="battery_heat_on",
        )

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off battery heat."""
        car = self.coordinator.car
        if car is None:
            return
        await self._execute_car_command(
            car.battery.heat(on=False),
            command="battery_heat_off",
        )


class BydCarOnSwitch(BydActionEntity, SwitchEntity):
    """Representation of a BYD car-on switch via climate control.

    Thin wrapper over ``car.hvac.start()`` / ``car.hvac.stop()`` that
    shares projected state with the climate entity via ``VehicleSnapshot``.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "car_on"
    _attr_icon = "mdi:car"
    _DEFAULT_TEMP_C = 21.0
    _DEFAULT_DURATION = 20

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_switch_car_on"

    @property
    def is_on(self) -> bool | None:
        """Return whether car-on (climate) is on."""
        hvac = self._get_hvac_status()
        if hvac is not None:
            return bool(hvac.is_ac_on)
        return None

    @property
    def assumed_state(self) -> bool:
        """Return True if HVAC state is unavailable."""
        return self._get_hvac_status() is None

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Turn on car-on (start climate at 21 C)."""
        car = self.coordinator.car
        if car is None:
            return
        await self._execute_car_command(
            car.hvac.start(
                temperature=self._DEFAULT_TEMP_C,
                duration=self._DEFAULT_DURATION,
            ),
            command="car_on",
        )

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off car-on (stop climate)."""
        car = self.coordinator.car
        if car is None:
            return
        await self._execute_car_command(
            car.hvac.stop(),
            command="car_off",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {**super().extra_state_attributes, "target_temperature_c": 21}


class BydSteeringWheelHeatSwitch(BydActionEntity, SwitchEntity):
    """Representation of the BYD steering wheel heat toggle.

    Commands go through ``car.steering.heat(on=True/False)`` which
    handles seat-climate payload assembly and projections internally.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "steering_wheel_heat"
    _attr_icon = "mdi:steering"

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_switch_steering_wheel_heat"

    @property
    def is_on(self) -> bool | None:
        """Return whether steering wheel heating is on."""
        if not self._is_vehicle_on():
            return False
        hvac = self._get_hvac_status()
        if hvac is not None:
            val = hvac.is_steering_wheel_heating
            if val is not None:
                return val
        realtime = self._get_realtime()
        if realtime is not None:
            val = realtime.is_steering_wheel_heating
            if val is not None:
                return val
        return None

    @property
    def assumed_state(self) -> bool:
        """Return True when the state is assumed."""
        hvac = self._get_hvac_status()
        if hvac is not None:
            return hvac.is_steering_wheel_heating is None
        realtime = self._get_realtime()
        if realtime is not None:
            return realtime.is_steering_wheel_heating is None
        return True

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Turn on steering wheel heating."""
        car = self.coordinator.car
        if car is None:
            return
        await self._execute_car_command(
            car.steering.heat(on=True),
            command="steering_wheel_heat_on",
        )

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off steering wheel heating."""
        car = self.coordinator.car
        if car is None:
            return
        await self._execute_car_command(
            car.steering.heat(on=False),
            command="steering_wheel_heat_off",
        )


class BydDisablePollingSwitch(BydVehicleEntity, RestoreEntity, SwitchEntity):
    """Per-vehicle switch to disable scheduled polling."""

    _attr_has_entity_name = True
    _attr_translation_key = "disable_polling"
    _attr_icon = "mdi:sync-off"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        gps_coordinator: Any,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle = vehicle
        self._gps_coordinator = gps_coordinator
        self._attr_unique_id = f"{vin}_switch_disable_polling"
        self._disabled = False

    async def async_added_to_hass(self) -> None:
        """Restore last state on startup."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self._disabled = last.state == "on"
        await self._apply()

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return self.coordinator.data is not None

    @property
    def is_on(self) -> bool:
        """Return True when polling is disabled."""
        return self._disabled

    async def _apply(self) -> None:
        await self.coordinator.async_set_polling_enabled(not self._disabled)
        gps = self._gps_coordinator
        if gps is not None:
            await gps.async_set_polling_enabled(not self._disabled)
        self.async_write_ha_state()

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Disable polling."""
        self._disabled = True
        await self._apply()

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Re-enable polling."""
        self._disabled = False
        await self._apply()


class BydScheduleEnabledSwitch(BydVehicleEntity, SwitchEntity):
    """Switch to enable/disable the charging schedule."""

    _attr_has_entity_name = True
    _attr_translation_key = "schedule_enabled"
    _attr_icon = "mdi:calendar-clock"

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_switch_schedule_enabled"
        self._optimistic_state: bool | None = None

    @property
    def is_on(self) -> bool | None:
        """Return True if schedule is enabled."""
        if self._optimistic_state is not None:
            return self._optimistic_state
        if self.coordinator.data and self.coordinator.data.charging_schedule and self.coordinator.data.charging_schedule.charge:
            return self.coordinator.data.charging_schedule.charge.status
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic_state = None
        super()._handle_coordinator_update()

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Enable schedule."""
        self._optimistic_state = True
        self.async_write_ha_state()
        await self.coordinator.async_request_schedule_update("enabled", True)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Disable schedule."""
        self._optimistic_state = False
        self.async_write_ha_state()
        await self.coordinator.async_request_schedule_update("enabled", False)


class BydChargeToFullSwitch(BydVehicleEntity, SwitchEntity):
    """Switch to toggle whether to charge to 100% or stop at end_time."""

    _attr_has_entity_name = True
    _attr_translation_key = "charge_to_full"
    _attr_icon = "mdi:battery-charging-100"

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_switch_charge_to_full"
        self._optimistic_state: bool | None = None

    @property
    def is_on(self) -> bool | None:
        """Return True if charging to full."""
        if self._optimistic_state is not None:
            return self._optimistic_state
        if self.coordinator.data and self.coordinator.data.charging_schedule and self.coordinator.data.charging_schedule.charge:
            return self.coordinator.data.charging_schedule.charge.charge_until_full
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic_state = None
        super()._handle_coordinator_update()

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Turn on charge to full."""
        self._optimistic_state = True
        self.async_write_ha_state()
        await self.coordinator.async_request_schedule_update("charge_to_full", True)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off charge to full."""
        self._optimistic_state = False
        self.async_write_ha_state()
        await self.coordinator.async_request_schedule_update("charge_to_full", False)


class BydRepeatDailySwitch(BydVehicleEntity, SwitchEntity):
    """Switch to toggle daily repeat (True for 'e', False for 's')."""

    _attr_has_entity_name = True
    _attr_translation_key = "repeat_daily"
    _attr_icon = "mdi:repeat"

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_switch_repeat_daily"
        self._optimistic_state: bool | None = None

    @property
    def is_on(self) -> bool | None:
        """Return True if repeat is daily."""
        if self._optimistic_state is not None:
            return self._optimistic_state
        if self.coordinator.data and self.coordinator.data.charging_schedule and self.coordinator.data.charging_schedule.charge:
            return self.coordinator.data.charging_schedule.charge.charge_way == "e"
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic_state = None
        super()._handle_coordinator_update()

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Turn on repeat daily."""
        self._optimistic_state = True
        self.async_write_ha_state()
        await self.coordinator.async_request_schedule_update("pattern", "e")

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off repeat daily."""
        self._optimistic_state = False
        self.async_write_ha_state()
        await self.coordinator.async_request_schedule_update("pattern", "s")
