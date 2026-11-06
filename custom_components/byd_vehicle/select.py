"""Select entities for BYD Vehicle seat climate control."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pybyd._capabilities.seat import SeatLevel, SeatPosition
from pybyd.models.realtime import SeatHeatVentState
from pybyd.models.vehicle import Vehicle

from .const import DOMAIN
from .coordinator import BydDataUpdateCoordinator
from .entity import BydActionEntity

_LOGGER = logging.getLogger(__name__)

# Derive options from the enum – single source of truth, no duplicate mappings.
SEAT_LEVEL_OPTIONS = [s.name.lower() for s in SeatHeatVentState if s.value > 0]

# Map UI option text → SeatLevel used by the pyBYD capability.
_OPTION_TO_LEVEL: dict[str, SeatLevel] = {
    "off": SeatLevel.OFF,
    "low": SeatLevel.LOW,
    "high": SeatLevel.HIGH,
}


def _seat_status_to_option(value: Any) -> str | None:
    """Map a seat status value to a UI option label.

    Uses ``SeatHeatVentState`` member names directly so there is no
    separate int<->string mapping to keep in sync.

    Returns ``"off"`` when *value* is ``None`` or ``NO_DATA`` (0) because
    the entity exists but no data has been received yet (vehicle may be
    off). The safe assumption is the feature exists but is idle.
    """
    if value is None:
        return "off"
    if not isinstance(value, SeatHeatVentState):
        try:
            value = SeatHeatVentState(int(value))
        except (TypeError, ValueError):
            return "off"
    if value == SeatHeatVentState.NO_DATA:
        return "off"
    return value.name.lower() if value.value > 0 else "off"


@dataclass(frozen=True, kw_only=True)
class BydSeatClimateDescription(SelectEntityDescription):
    """Describe a BYD seat climate select entity."""

    seat_position: SeatPosition | None
    """pyBYD seat position, or None for unsupported rear seats."""
    mode: str
    """``'heat'`` or ``'vent'``."""
    hvac_attr: str
    """Attribute name on HVAC / realtime status for current state."""
    capability_key: str | None
    """Normalized pyBYD capability flag name."""


SEAT_CLIMATE_DESCRIPTIONS: tuple[BydSeatClimateDescription, ...] = (
    BydSeatClimateDescription(
        key="driver_seat_heat",
        icon="mdi:car-seat-heater",
        seat_position=SeatPosition.DRIVER,
        mode="heat",
        hvac_attr="main_seat_heat_state",
        capability_key="driver_seat_heat",
    ),
    BydSeatClimateDescription(
        key="driver_seat_ventilation",
        icon="mdi:car-seat-cooler",
        seat_position=SeatPosition.DRIVER,
        mode="vent",
        hvac_attr="main_seat_ventilation_state",
        capability_key="driver_seat_ventilation",
    ),
    BydSeatClimateDescription(
        key="passenger_seat_heat",
        icon="mdi:car-seat-heater",
        seat_position=SeatPosition.COPILOT,
        mode="heat",
        hvac_attr="copilot_seat_heat_state",
        capability_key="passenger_seat_heat",
    ),
    BydSeatClimateDescription(
        key="passenger_seat_ventilation",
        icon="mdi:car-seat-cooler",
        seat_position=SeatPosition.COPILOT,
        mode="vent",
        hvac_attr="copilot_seat_ventilation_state",
        capability_key="passenger_seat_ventilation",
    ),
    BydSeatClimateDescription(
        key="rear_left_seat_heat",
        icon="mdi:car-seat-heater",
        seat_position=None,
        mode="heat",
        hvac_attr="lr_seat_heat_state",
        capability_key="rear_left_seat_heat",
        entity_registry_enabled_default=False,
    ),
    BydSeatClimateDescription(
        key="rear_left_seat_ventilation",
        icon="mdi:car-seat-cooler",
        seat_position=None,
        mode="vent",
        hvac_attr="lr_seat_ventilation_state",
        capability_key=None,
        entity_registry_enabled_default=False,
    ),
    BydSeatClimateDescription(
        key="rear_right_seat_heat",
        icon="mdi:car-seat-heater",
        seat_position=None,
        mode="heat",
        hvac_attr="rr_seat_heat_state",
        capability_key="rear_right_seat_heat",
        entity_registry_enabled_default=False,
    ),
    BydSeatClimateDescription(
        key="rear_right_seat_ventilation",
        icon="mdi:car-seat-cooler",
        seat_position=None,
        mode="vent",
        hvac_attr="rr_seat_ventilation_state",
        capability_key=None,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BYD seat climate select entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[str, BydDataUpdateCoordinator] = data["coordinators"]

    entities: list[SelectEntity] = []
    for vin, coordinator in coordinators.items():
        vehicle = coordinator.vehicle
        for description in SEAT_CLIMATE_DESCRIPTIONS:
            capability_key = description.capability_key
            if capability_key is None or not coordinator.capability_available(
                capability_key
            ):
                continue
            entities.append(
                BydSeatClimateSelect(coordinator, vin, vehicle, description)
            )

    async_add_entities(entities)


class BydSeatClimateSelect(BydActionEntity, SelectEntity):
    """Select entity for a single seat heating/ventilation level.

    For driver and copilot seats, commands are dispatched through
    ``car.seat.heat()`` / ``car.seat.ventilation()`` which handle
    ``SeatClimateParams`` assembly and projections internally.

    Rear-seat entities are read-only (disabled by default) because the
    pyBYD capability does not yet map rear seat positions.
    """

    _attr_has_entity_name = True
    _attr_options = SEAT_LEVEL_OPTIONS

    entity_description: BydSeatClimateDescription

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
        description: BydSeatClimateDescription,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_select_{description.key}"

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        hvac = self._get_hvac_status()
        realtime = self._get_realtime()
        val = None
        if hvac is not None:
            val = getattr(hvac, self.entity_description.hvac_attr, None)
        if val is None and realtime is not None:
            val = getattr(realtime, self.entity_description.hvac_attr, None)
        option = _seat_status_to_option(val)
        # Fallback: entity was created so the feature exists — default to 'off'.
        return option if option is not None else "off"

    async def async_select_option(self, option: str) -> None:
        """Set the seat climate level via pyBYD capability."""
        self._ensure_action_allowed()
        desc = self.entity_description

        # Rear seats not yet supported by pyBYD SeatCapability.
        if desc.seat_position is None:
            _LOGGER.warning(
                "Rear seat commands are not yet supported by pyBYD; %s ignored",
                desc.key,
            )
            return

        level = _OPTION_TO_LEVEL.get(option)
        if level is None:
            return

        car = self.coordinator.car
        if car is None:
            return

        if desc.mode == "heat":
            await self._execute_car_command(
                car.seat.heat(desc.seat_position, level),
                command=f"seat_climate_{desc.key}",
            )
        else:
            await self._execute_car_command(
                car.seat.ventilation(desc.seat_position, level),
                command=f"seat_climate_{desc.key}",
            )
