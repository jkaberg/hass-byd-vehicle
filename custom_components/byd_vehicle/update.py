"""Firmware update entity for BYD Vehicle."""

from __future__ import annotations

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pybyd.models.ota import OtaStatus, OtaUpgradeInfo
from pybyd.models.vehicle import Vehicle

from .const import DOMAIN
from .coordinator import BydDataUpdateCoordinator
from .entity import BydVehicleEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the firmware update entity for cars the cloud offers OTA for."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[str, BydDataUpdateCoordinator] = data["coordinators"]
    entities: list[BydFirmwareUpdate] = []
    for vin, coordinator in coordinators.items():
        if await coordinator.async_ota_supported():
            entities.append(BydFirmwareUpdate(coordinator, vin, coordinator.vehicle))
    async_add_entities(entities)


def release_notes(ota: OtaUpgradeInfo) -> str | None:
    """The release notes the app shows for the new version, as markdown."""
    sections = [
        ota.function_description,
        ota.function_addition,
        ota.function_optimization,
    ]
    notes = "\n\n".join(section.strip() for section in sections if section.strip())
    return notes or None


class BydFirmwareUpdate(BydVehicleEntity, UpdateEntity):
    """The car's firmware version.

    Read only: the cloud reports the version but installing happens in the
    car or through night auto-upgrade, so there's no install action.
    """

    _attr_has_entity_name = True
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = UpdateEntityFeature.RELEASE_NOTES

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
    ) -> None:
        self._vin = vin
        self._vehicle = vehicle
        super().__init__(coordinator)
        self._attr_unique_id = f"{vin}_update_firmware"

    @property
    def available(self) -> bool:
        """Available once the firmware status was fetched."""
        return super().available and self.coordinator.ota is not None

    @property
    def installed_version(self) -> str | None:
        """The version on the car."""
        ota = self.coordinator.ota
        return (ota.current_version.strip() or None) if ota else None

    @property
    def latest_version(self) -> str | None:
        """The version the cloud offers, the installed one when none."""
        ota = self.coordinator.ota
        if ota is None:
            return None
        return ota.update_version.strip() or self.installed_version

    @property
    def in_progress(self) -> bool:
        """Whether the car is installing right now."""
        ota = self.coordinator.ota
        return ota is not None and ota.upgrade_status == OtaStatus.UPGRADING

    async def async_release_notes(self) -> str | None:
        """Release notes for the offered version."""
        ota = self.coordinator.ota
        if ota is None or not ota.has_update:
            return None
        return release_notes(ota)
