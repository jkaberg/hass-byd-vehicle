"""Switches for BYD Vehicle."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from pybyd.models.vehicle import Vehicle

from .abrp import async_send_telemetry
from .const import CONF_ABRP_TOKEN, DOMAIN
from .coordinator import BydDataUpdateCoordinator
from .entity import BydActionEntity, BydVehicleEntity

_LOGGER = logging.getLogger(__name__)

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
        
        # Add our new ABRP switch
        entities.append(BYDABRPSwitch(coordinator, gps_coordinator, vin, vehicle))

        entities.append(
            BydDisablePollingSwitch(coordinator, gps_coordinator, vin, vehicle)
        )
        if coordinator.capability_available("car_on"):
            entities.append(BydCarOnSwitch(coordinator, vin, vehicle))
        if coordinator.capability_available("battery_heat"):
            entities.append(BydBatteryHeatSwitch(coordinator, vin, vehicle))
        if coordinator.capability_available("steering_wheel_heat"):
            entities.append(BydSteeringWheelHeatSwitch(coordinator, vin, vehicle))

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

class BYDABRPSwitch(SwitchEntity):
    """Switch to control ABRP synchronization."""

    def __init__(self, coordinator, gps_coordinator, vin, vehicle):
        self.coordinator = coordinator
        self.gps_coordinator = gps_coordinator
        self._vin = vin
        self._vehicle = vehicle
        name = getattr(coordinator, "vehicle_name", "BYD")
        self._attr_name = f"ABRP Sync {name}"
        self._attr_unique_id = f"{vin}_abrp_sync"
        self._attr_is_on = False

    @property
    def is_on(self):
        return self._attr_is_on

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._vin)},
            "name": getattr(self.coordinator, "vehicle_name", "BYD Vehicle"),
            "manufacturer": "BYD",
        }

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        self._attr_is_on = True
        
        # Listen to BOTH coordinators to be safe
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))
        if self.gps_coordinator:
            self.async_on_remove(self.gps_coordinator.async_add_listener(self._handle_coordinator_update))
            
        # KICKSTART: Send data immediately when turned on
        self._handle_coordinator_update()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._attr_is_on = False
        self.async_write_ha_state()

    def _handle_coordinator_update(self):
        """Bridge function."""
        if self._attr_is_on:
            # We use call_soon_threadsafe to ensure the task starts correctly
            self.hass.add_job(self._sync_data)

    async def _sync_data(self):
        """Fetch data from your specific HA entities."""
        if not self._attr_is_on:
            return

        token = "YOUR_ABRP_TOKEN_GOES_HERE"

        try:
            # 1. Use your exact Entity IDs
            soc_state = self.hass.states.get("sensor.byd_seal_battery_level")
            odo_state = self.hass.states.get("sensor.byd_seal_odometer")
            gps_state = self.hass.states.get("device_tracker.byd_seal_location")

            # 2. Extract SOC (Battery)
            soc = None
            if soc_state and soc_state.state not in ["unknown", "unavailable"]:
                soc = float(soc_state.state)

            # 3. Extract Odometer (Mileage)
            odo = None
            if odo_state and odo_state.state not in ["unknown", "unavailable"]:
                # We replace any commas if present and convert to float
                odo = float(odo_state.state.replace(",", ""))

            # 4. Extract GPS Coordinates from Attributes
            lat, lon = None, None
            if gps_state and "latitude" in gps_state.attributes:
                lat = gps_state.attributes.get("latitude")
                lon = gps_state.attributes.get("longitude")

            # 5. Get Charging & Speed from the coordinator
            attr = self.coordinator.data
            rt = getattr(attr, "realtime", None)
            is_charging = getattr(rt, "charge_status", 0) > 0 if rt else False
            speed = getattr(rt, "speed", 0) if rt else 0

            data = {
                "soc": soc,
                "lat": lat,
                "lon": lon,
                "is_charging": is_charging,
                "odometer": odo,
                "speed": speed,
            }

            # Log what we are about to send
            _LOGGER.debug(
                "ABRP Final Sync Check: SOC=%s, ODO=%s, Lat=%s, Lon=%s", 
                soc, odo, lat, lon
            )
            
            # We must have SOC and GPS to be useful for ABRP
            if soc is not None and lat is not None:
                await async_send_telemetry(self.hass, token, data)
            else:
                _LOGGER.warning(
                    "ABRP Sync: Missing data. SOC found: %s, GPS found: %s", 
                    "Yes" if soc is not None else "No", 
                    "Yes" if lat is not None else "No"
                )
                
        except Exception as err:
            _LOGGER.error("ABRP Sync State Error: %s", err)
