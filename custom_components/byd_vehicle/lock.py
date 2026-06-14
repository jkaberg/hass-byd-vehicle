"""Lock control for BYD Vehicle."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity, LockState
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from pybyd.models.vehicle import Vehicle

from .const import DOMAIN
from .coordinator import BydDataUpdateCoordinator
from .entity import BydActionEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BYD lock entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[str, BydDataUpdateCoordinator] = data["coordinators"]

    entities: list[LockEntity] = []

    for vin, coordinator in coordinators.items():
        if not (
            coordinator.capability_available("lock")
            or coordinator.capability_available("unlock")
        ):
            continue
        entities.append(BydLock(coordinator, vin, coordinator.vehicle))

    async_add_entities(entities)


class BydLock(BydActionEntity, LockEntity, RestoreEntity):
    """Representation of BYD lock control.

    Reads lock state from ``VehicleSnapshot.realtime.is_locked``.
    Commands go through ``car.lock.lock()`` / ``car.lock.unlock()``
    which handle projections and guard windows internally.

    Survives restarts and config-entry reloads via ``RestoreEntity``:
    individual lock flags drop out of the realtime payload while the
    car is in deep sleep, so without restore a reload-immediately-after
    means ``lock = unknown`` until the car wakes back up (which can be
    minutes).  The restored value gives us a sensible fallback.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "lock"

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_lock"
        self._last_is_locked: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last known lock state before the coordinator binds."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None:
            return
        if last.state == LockState.LOCKED:
            self._last_is_locked = True
        elif last.state == LockState.UNLOCKED:
            self._last_is_locked = False

    @property
    def is_locked(self) -> bool | None:
        """Return True if all doors are locked.

        Falls back to the last known value when the realtime payload
        omits the lock flag (typical of deep-sleep responses), so the
        entity doesn't flip to ``unknown`` on every reload.
        """
        realtime = self._get_realtime()
        if realtime is not None:
            value = realtime.is_locked
            if value is not None:
                self._last_is_locked = value
                return value
        return self._last_is_locked

    @property
    def assumed_state(self) -> bool:
        """Return True when lock state is assumed (no realtime data).

        Also treated as assumed while the vehicle is on: BYD reports
        ``is_locked=True`` during driving because the auto-lock kicks in,
        which makes the HA control look "already locked" and greys out the
        lock button when the user actually wants to act on it.  Marking it
        assumed keeps both lock and unlock controls actionable on park.
        """
        realtime = self._get_realtime()
        if realtime is None:
            return True
        if realtime.is_locked is None:
            return True
        return bool(getattr(realtime, "is_vehicle_on", False))

    async def async_lock(self, **_: Any) -> None:
        """Lock the vehicle."""
        car = self.coordinator.car
        if car is None:
            return
        await self._execute_car_command(
            car.lock.lock(),
            command="lock",
        )

    async def async_unlock(self, **_: Any) -> None:
        """Unlock the vehicle."""
        car = self.coordinator.car
        if car is None:
            return
        await self._execute_car_command(
            car.lock.unlock(),
            command="unlock",
        )
