"""Buttons for BYD Vehicle remote commands."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pybyd.car import BydCar
from pybyd.models.vehicle import Vehicle

from .const import DOMAIN
from .coordinator import BydDataUpdateCoordinator
from .entity import BydActionEntity, BydVehicleEntity


@dataclass(frozen=True, kw_only=True)
class BydButtonDescription(ButtonEntityDescription):
    """Describe a BYD button backed by a car capability."""

    car_command: Callable[[BydCar], Awaitable[Any]]
    """Lambda returning the capability coroutine to execute."""
    capability_key: str
    """Normalized pyBYD capability flag name."""


BUTTON_DESCRIPTIONS: tuple[BydButtonDescription, ...] = (
    BydButtonDescription(
        key="flash_lights",
        icon="mdi:car-light-high",
        capability_key="flash_lights",
        car_command=lambda car: car.finder.flash_lights(),
    ),
    BydButtonDescription(
        key="find_car",
        icon="mdi:car-search",
        capability_key="find_car",
        car_command=lambda car: car.finder.find(),
    ),
    BydButtonDescription(
        key="close_windows",
        icon="mdi:window-closed",
        capability_key="close_windows",
        car_command=lambda car: car.windows.close(),
    ),
    BydButtonDescription(
        key="open_windows",
        icon="mdi:window-open",
        capability_key="open_windows",
        car_command=lambda car: car.windows.open(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BYD buttons from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[str, BydDataUpdateCoordinator] = data["coordinators"]
    gps_coordinators = data.get("gps_coordinators", {})

    entities: list[ButtonEntity] = []
    for vin, coordinator in coordinators.items():
        vehicle = coordinator.vehicle
        gps_coordinator = gps_coordinators.get(vin)

        entities.append(BydForcePollButton(coordinator, gps_coordinator, vin, vehicle))
        entities.append(BydStartChargingButton(coordinator, vin, vehicle))
        entities.append(BydFetchEnergyButton(coordinator, vin, vehicle))
        for description in BUTTON_DESCRIPTIONS:
            if not coordinator.capability_available(description.capability_key):
                continue
            entities.append(BydButton(coordinator, vin, vehicle, description))

    async_add_entities(entities)


class BydButton(BydActionEntity, ButtonEntity):
    """Representation of a BYD remote command button."""

    _attr_has_entity_name = True
    entity_description: BydButtonDescription

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
        description: BydButtonDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_button_{description.key}"

    async def async_press(self) -> None:
        """Execute the remote command via pyBYD capability."""
        car = self.coordinator.car
        if car is None:
            return
        await self._execute_car_command(
            self.entity_description.car_command(car),
            command=self.entity_description.key,
        )


class BydForcePollButton(BydVehicleEntity, ButtonEntity):
    """Button that forces a coordinator refresh (telemetry + GPS)."""

    _attr_has_entity_name = True
    _attr_translation_key = "force_poll"
    _attr_icon = "mdi:sync"
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
        self._attr_unique_id = f"{vin}_button_force_poll"

    async def async_press(self) -> None:
        """Force-refresh all coordinators for this vehicle."""
        try:
            await self.coordinator.async_force_refresh()
            gps = self._gps_coordinator
            if gps is not None:
                await gps.async_force_refresh()
        except Exception as exc:  # noqa: BLE001
            raise HomeAssistantError(str(exc)) from exc


class BydStartChargingButton(BydVehicleEntity, ButtonEntity):
    """Button that starts charging immediately."""

    _attr_has_entity_name = True
    _attr_translation_key = "start_charging"
    _attr_icon = "mdi:play"

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_button_start_charging"

    @property
    def available(self) -> bool:
        # BYD's cloud rejects /control/smartCharge/changeChargeStatue with
        # res=3 "Operation failure" when the vehicle is already in the
        # target state — either already charging, at 100 % SoC, or when
        # the cable isn't physically plugged in.  Hide the button in
        # those cases so users don't get a confusing error.
        #
        # Prefer realtime fields (always present, drive the user-visible
        # battery_level / charging sensors) over the charging snapshot
        # (only refreshed on smart-charging-page polls and may be None
        # between updates).
        if not super().available:
            return False
        snapshot = self._snapshot()
        if snapshot is None:
            return True
        is_charging: bool | None = None
        if snapshot.realtime is not None:
            is_charging = snapshot.realtime.is_charging
        if is_charging is None and snapshot.charging is not None:
            is_charging = snapshot.charging.is_charging
        if is_charging:
            return False
        soc: float | None = None
        if snapshot.realtime is not None:
            soc = snapshot.realtime.elec_percent
        if soc is None and snapshot.charging is not None:
            soc = snapshot.charging.soc
        if soc is not None and soc >= 100:
            return False
        # Cable must be plugged in.  Source from the charging endpoint
        # which PR #144 made the authoritative plug state — realtime's
        # connectState frequently sits at -1 (sentinel) on Sealion 7 EU
        # so we only treat charging.connect_state as a hard "no".
        if snapshot.charging is not None:
            connect_state = getattr(snapshot.charging, "connect_state", None)
            if connect_state is not None and not connect_state:
                return False
        return True

    async def async_press(self) -> None:
        await self.coordinator.async_start_charging()


class BydFetchEnergyButton(BydVehicleEntity, ButtonEntity):
    """Button that fetches the getEnergyConsumption snapshot on demand.

    Energy data isn't included in the regular telemetry poll (cumulative
    averages and last-trip breakdown change slowly and the cloud rate-
    limits the endpoint), so the energy_* sensors are unavailable until
    this button is pressed.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "fetch_energy"
    _attr_icon = "mdi:download"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_button_fetch_energy"

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_fetch_energy()
            # Push the updated snapshot (with energy) out to subscribers
            # so the dependent sensors come online without waiting for
            # the next telemetry tick.
            car = self.coordinator.car
            if car is not None:
                self.coordinator.async_set_updated_data(car.state)
        except Exception as exc:  # noqa: BLE001
            raise HomeAssistantError(str(exc)) from exc
