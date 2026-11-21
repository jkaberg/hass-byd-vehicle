"""Time entities for BYD Vehicle."""

from __future__ import annotations

import datetime
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pybyd.models.vehicle import Vehicle

from .const import DOMAIN
from .coordinator import BydDataUpdateCoordinator
from .entity import BydActionEntity, BydVehicleEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BYD time entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[str, BydDataUpdateCoordinator] = data["coordinators"]

    entities: list[TimeEntity] = []
    for vin, coordinator in coordinators.items():
        vehicle = coordinator.vehicle
        entities.append(BydStartTimeEntity(coordinator, vin, vehicle))
        entities.append(BydEndTimeEntity(coordinator, vin, vehicle))
        if await coordinator.async_ota_supported():
            entities.append(BydOtaAutoUpgradeTime(coordinator, vin, vehicle))

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
        if (
            self.coordinator.data
            and self.coordinator.data.charging_schedule
            and self.coordinator.data.charging_schedule.charge
        ):
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
    def available(self) -> bool:
        """Hide end_time when the schedule is set to charge until full."""
        if not super().available:
            return False
        charge = self._charge()
        if charge is None:
            return False
        return not bool(getattr(charge, "charge_until_full", False))

    @property
    def native_value(self) -> datetime.time | None:
        """Return the end time."""
        if self._optimistic_state is not None:
            return self._optimistic_state
        charge = self._charge()
        if charge is None:
            return None
        return charge.end_time

    def _charge(self) -> Any:
        if self.coordinator.data and self.coordinator.data.charging_schedule:
            return self.coordinator.data.charging_schedule.charge
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


def parse_hmm(value: str) -> datetime.time | None:
    """The cloud's ``H:mm`` upgrade time, ``None`` when unset or garbled."""
    try:
        hour, minute = (int(part) for part in value.split(":"))
        return datetime.time(hour, minute)
    except ValueError:
        return None


class BydOtaAutoUpgradeTime(BydActionEntity, TimeEntity):
    """When night auto-upgrade installs a new firmware."""

    _attr_has_entity_name = True
    _attr_translation_key = "ota_auto_upgrade_time"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        self._vin = vin
        self._vehicle = vehicle
        super().__init__(coordinator)
        self._attr_unique_id = f"{vin}_time_ota_auto_upgrade"

    @property
    def available(self) -> bool:
        """Available once the firmware status was fetched."""
        return super().available and self.coordinator.ota is not None

    @property
    def native_value(self) -> datetime.time | None:
        """The upgrade time."""
        ota = self.coordinator.ota
        return parse_hmm(ota.auto_upgrade_time) if ota is not None else None

    async def async_set_value(self, value: datetime.time) -> None:
        """Change the upgrade time, keeping the on/off setting."""
        self._ensure_action_allowed()
        await self.coordinator.async_set_ota_auto_upgrade(
            at=f"{value.hour}:{value.minute:02d}"
        )
