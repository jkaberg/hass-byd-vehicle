"""Time entities for BYD Vehicle."""

from __future__ import annotations

import datetime
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pybyd.models.vehicle import Vehicle

from .const import DOMAIN
from .coordinator import BydDataUpdateCoordinator
from .entity import BydVehicleEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BYD time entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[str, BydDataUpdateCoordinator] = data["coordinators"]

    entities: list[TimeEntity] = []
    for vin, coordinator in coordinators.items():
        vehicle = coordinator.vehicle
        entities.append(BydStartTimeEntity(coordinator, vin, vehicle))
        entities.append(BydEndTimeEntity(coordinator, vin, vehicle))

    async_add_entities(entities)


class BydStartTimeEntity(BydVehicleEntity, TimeEntity):
    """Time entity for charging start time."""

    _attr_has_entity_name = True
    _attr_translation_key = "start_time"
    _attr_icon = "mdi:clock-start"

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_time_start_time"
        self._optimistic_state: datetime.time | None = None

    @property
    def native_value(self) -> datetime.time | None:
        """Return the start time."""
        if self._optimistic_state is not None:
            return self._optimistic_state
        if self.coordinator.data and self.coordinator.data.charging_schedule and self.coordinator.data.charging_schedule.charge:
            return self.coordinator.data.charging_schedule.charge.start_time
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic_state = None
        super()._handle_coordinator_update()

    async def async_set_value(self, value: datetime.time) -> None:
        """Set the start time."""
        self._optimistic_state = value
        self.async_write_ha_state()
        await self.coordinator.async_request_schedule_update("start_time", value)


class BydEndTimeEntity(BydVehicleEntity, TimeEntity):
    """Time entity for charging end time."""

    _attr_has_entity_name = True
    _attr_translation_key = "end_time"
    _attr_icon = "mdi:clock-end"

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_time_end_time"
        self._optimistic_state: datetime.time | None = None

    @property
    def native_value(self) -> datetime.time | None:
        """Return the end time."""
        if self._optimistic_state is not None:
            return self._optimistic_state
        if self.coordinator.data and self.coordinator.data.charging_schedule and self.coordinator.data.charging_schedule.charge:
            return self.coordinator.data.charging_schedule.charge.end_time
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic_state = None
        super()._handle_coordinator_update()

    async def async_set_value(self, value: datetime.time) -> None:
        """Set the end time."""
        self._optimistic_state = value
        self.async_write_ha_state()
        await self.coordinator.async_request_schedule_update("end_time", value)
