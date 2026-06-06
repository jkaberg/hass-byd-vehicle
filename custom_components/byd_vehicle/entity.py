"""Base entity mixins for BYD Vehicle."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from pybyd import (
    BydControlPasswordError,
    BydEndpointNotSupportedError,
    BydRemoteControlError,
    VehicleSnapshot,
)
from pybyd.models.energy import EnergyConsumption
from pybyd.models.gps import GpsInfo
from pybyd.models.hvac import HvacStatus
from pybyd.models.realtime import VehicleRealtimeData
from pybyd.models.vehicle import Vehicle

from .const import DOMAIN
from .coordinator import BydDataUpdateCoordinator, get_vehicle_display

_LOGGER = logging.getLogger(__name__)


class BydVehicleEntity(CoordinatorEntity[BydDataUpdateCoordinator]):
    """Mixin providing common properties for BYD vehicle entities.

    Subclasses must set ``_vin`` and ``_vehicle`` before calling
    ``super().__init__``.  Data is read from ``coordinator.data`` which
    is a :class:`VehicleSnapshot` — no local shadow state, no optimistic
    tracking.
    """

    _vin: str
    _vehicle: Vehicle

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info common to every BYD entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._vin)},
            name=get_vehicle_display(self._vehicle),
            manufacturer=self._vehicle.brand_name or "BYD",
            model=self._vehicle.model_name,
            serial_number=self._vin,
            hw_version=self._vehicle.tbox_version or None,
        )

    @property
    def available(self) -> bool:
        """Available when coordinator has a snapshot with vehicle data."""
        if not super().available:
            return False
        return self.coordinator.data is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return VIN as the default extra attribute."""
        return {"vin": self._vin}

    # ------------------------------------------------------------------
    # Snapshot data helpers
    # ------------------------------------------------------------------

    def _snapshot(self) -> VehicleSnapshot | None:
        """Return the coordinator's current snapshot."""
        return self.coordinator.data

    def _get_realtime(self) -> VehicleRealtimeData | None:
        """Return realtime data from the snapshot."""
        snap = self._snapshot()
        return snap.realtime if snap is not None else None

    def _get_hvac_status(self) -> HvacStatus | None:
        """Return HVAC status from the snapshot."""
        snap = self._snapshot()
        return snap.hvac if snap is not None else None

    def _get_gps(self) -> GpsInfo | None:
        """Return GPS data from the snapshot."""
        snap = self._snapshot()
        return snap.gps if snap is not None else None

    def _get_energy(self) -> EnergyConsumption | None:
        """Return energy-consumption data from the snapshot."""
        snap = self._snapshot()
        return snap.energy if snap is not None else None

    def _get_source_obj(self, source: str = "realtime") -> Any | None:
        """Return the snapshot section for the given *source* string.

        Supported values: ``"realtime"``, ``"hvac"``, ``"gps"``,
        ``"energy"``, ``"energy_cumulative"``, ``"energy_nearest"``,
        ``"energy_self_graph"``, ``"energy_auto_model_graph"``,
        ``"charging"``, ``"charging_schedule"``, ``"charging_schedule_charge"``,
        ``"charging_schedule_journey"``, ``"snapshot"`` (the full
        :class:`VehicleSnapshot` for cross-section merged value_fn lookups).
        """
        if source == "realtime":
            return self._get_realtime()
        if source == "hvac":
            return self._get_hvac_status()
        if source == "gps":
            return self._get_gps()
        if source == "energy":
            return self._get_energy()
        if source == "charging":
            snap = self._snapshot()
            return snap.charging if snap is not None else None
        if source == "snapshot":
            return self._snapshot()
        if source.startswith("energy_"):
            energy = self._get_energy()
            if energy is None:
                return None
            attr = source[len("energy_") :]
            # Map URL-style suffixes to model attribute names.
            attr_map = {
                "cumulative": "cumulative_energy_consumption",
                "nearest": "nearest_energy_consumption",
                "self_graph": "self_graph",
                "auto_model_graph": "auto_model_graph",
            }
            return getattr(energy, attr_map.get(attr, attr), None)
        if source.startswith("charging_schedule"):
            snap = self._snapshot()
            schedule = snap.charging_schedule if snap is not None else None
            if source == "charging_schedule":
                return schedule
            if schedule is None:
                return None
            attr = source[len("charging_schedule_") :]
            return getattr(schedule, attr, None)
        return None

    def _is_vehicle_on(self) -> bool:
        """Return True when the vehicle is on."""
        realtime = self._get_realtime()
        if realtime is None:
            return False
        return bool(realtime.is_vehicle_on)

    # ------------------------------------------------------------------
    # Command helpers
    # ------------------------------------------------------------------

    def _command_pin_error_message(self) -> str:
        """Return a user-facing error message for command PIN issues."""
        if self.coordinator.has_pin_configured:
            return (
                "Command PIN is invalid or cloud control is locked — "
                "reconfigure the integration to update your Control PIN"
            )
        return "Control PIN is not configured; set Control PIN to enable actions"

    async def _execute_car_command(
        self,
        coro: Any,
        *,
        command: str,
    ) -> None:
        """Execute a BydCar capability command with HA error handling.

        On :class:`BydRemoteControlError` the command is treated as
        optimistically successful (pyBYD's state engine handles the
        projection).  On any other failure the exception is re-raised
        as :class:`HomeAssistantError`.
        """
        if not self.coordinator.has_operation_pin:
            raise HomeAssistantError(self._command_pin_error_message())
        try:
            await coro
        except BydRemoteControlError as exc:
            _LOGGER.warning(
                "%s command sent but cloud reported failure — "
                "pyBYD state engine handles projection: %s",
                command,
                exc,
            )
        except BydControlPasswordError as exc:
            if exc.code == "5006":
                msg = "Cloud control temporarily locked by BYD — try again later"
            elif exc.code == "commands_disabled":
                msg = "Command access not verified — reconfigure your Control PIN"
            elif exc.code == "5005":
                msg = "Command PIN is wrong — reconfigure the integration"
            else:
                msg = f"Command PIN error: {exc}"
            _LOGGER.warning("%s command failed: %s (code=%s)", command, msg, exc.code)
            raise HomeAssistantError(msg) from exc
        except BydEndpointNotSupportedError as exc:
            msg = "This command is not supported by your vehicle"
            _LOGGER.warning("%s command blocked: %s", command, exc)
            raise HomeAssistantError(msg) from exc
        except Exception as exc:  # noqa: BLE001
            raise HomeAssistantError(str(exc)) from exc


class BydActionEntity(BydVehicleEntity):
    """Base for action entities requiring a verified Control PIN."""

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Gate default enabled state by whether a PIN is configured.

        Uses ``has_pin_configured`` (config-level check) so entities are
        *registered* when a PIN exists, even if verification has not yet
        succeeded.  The runtime gate (``has_operation_pin``) prevents
        commands from actually executing when verification failed.
        """
        enabled_default = getattr(self, "_attr_entity_registry_enabled_default", None)
        if enabled_default is None:
            description = getattr(self, "entity_description", None)
            enabled_default = getattr(
                description,
                "entity_registry_enabled_default",
                True,
            )
        return bool(enabled_default) and self.coordinator.has_pin_configured

    def _ensure_action_allowed(self) -> None:
        """Raise when actions are attempted without a verified Control PIN."""
        if not self.coordinator.has_operation_pin:
            raise HomeAssistantError(self._command_pin_error_message())
