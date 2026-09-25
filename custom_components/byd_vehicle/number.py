"""Number entities for BYD Vehicle."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pybyd.models.vehicle import Vehicle

from .const import (
    CONF_GPS_POLL_INTERVAL_BY_VIN,
    CONF_POLL_INTERVAL_BY_VIN,
    DOMAIN,
    MAX_GPS_POLL_INTERVAL,
    MAX_POLL_INTERVAL,
    MIN_GPS_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)
from .coordinator import BydDataUpdateCoordinator, BydGpsUpdateCoordinator
from .entity import BydVehicleEntity


def _persist_vin_interval(
    hass: HomeAssistant,
    entry: ConfigEntry,
    key: str,
    vin: str,
    interval: int,
) -> None:
    """Store a per-vehicle poll interval in the entry options.

    Intervals are per vehicle so that setting one car's number entity
    never changes another car on the same account (issue #189).
    """
    current = entry.options.get(key)
    by_vin: dict[str, Any] = dict(current) if isinstance(current, Mapping) else {}
    if by_vin.get(vin) == interval:
        return
    by_vin[vin] = interval
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, key: by_vin}
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BYD number entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[str, BydDataUpdateCoordinator] = data["coordinators"]
    gps_coordinators: dict[str, BydGpsUpdateCoordinator] = data.get(
        "gps_coordinators", {}
    )

    entities: list[NumberEntity] = []
    for vin, coordinator in coordinators.items():
        vehicle = coordinator.vehicle
        entities.append(
            BydRealtimePollIntervalNumber(hass, entry, coordinator, vin, vehicle)
        )

        gps_coordinator = gps_coordinators.get(vin)
        if gps_coordinator is not None:
            entities.append(
                BydGpsPollIntervalNumber(
                    hass,
                    entry,
                    coordinator,
                    gps_coordinator,
                    vin,
                    vehicle,
                )
            )

    async_add_entities(entities)


class BydRealtimePollIntervalNumber(BydVehicleEntity, NumberEntity):
    """Runtime-configurable realtime polling interval."""

    _attr_has_entity_name = True
    _attr_translation_key = "realtime_poll_interval"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = float(MIN_POLL_INTERVAL)
    _attr_native_max_value = float(MAX_POLL_INTERVAL)
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        super().__init__(coordinator)
        self.hass = hass
        self._entry = entry
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_number_realtime_poll_interval"

    @property
    def native_value(self) -> float:
        """Return realtime poll interval in seconds."""
        return float(self.coordinator.poll_interval_seconds)

    async def async_set_native_value(self, value: float) -> None:
        """Set and persist realtime poll interval."""
        interval = max(MIN_POLL_INTERVAL, min(MAX_POLL_INTERVAL, int(value)))

        self.coordinator.set_poll_interval(interval)
        _persist_vin_interval(
            self.hass, self._entry, CONF_POLL_INTERVAL_BY_VIN, self._vin, interval
        )
        self.async_write_ha_state()


class BydGpsPollIntervalNumber(BydVehicleEntity, NumberEntity):
    """Runtime-configurable GPS polling interval."""

    _attr_has_entity_name = True
    _attr_translation_key = "gps_poll_interval"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = float(MIN_GPS_POLL_INTERVAL)
    _attr_native_max_value = float(MAX_GPS_POLL_INTERVAL)
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: BydDataUpdateCoordinator,
        gps_coordinator: BydGpsUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        super().__init__(coordinator)
        self.hass = hass
        self._entry = entry
        self._gps_coordinator = gps_coordinator
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_number_gps_poll_interval"

    @property
    def native_value(self) -> float:
        """Return GPS poll interval in seconds."""
        return float(self._gps_coordinator.poll_interval_seconds)

    async def async_set_native_value(self, value: float) -> None:
        """Set and persist GPS poll interval."""
        interval = max(MIN_GPS_POLL_INTERVAL, min(MAX_GPS_POLL_INTERVAL, int(value)))

        self._gps_coordinator.set_poll_interval(interval)
        _persist_vin_interval(
            self.hass, self._entry, CONF_GPS_POLL_INTERVAL_BY_VIN, self._vin, interval
        )
        self.async_write_ha_state()
