"""Data coordinators for BYD Vehicle."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pybyd import (
    BydApiError,
    BydAuthenticationError,
    BydClient,
    BydRemoteControlError,
    BydTransportError,
    RemoteControlResult,
)
from pybyd.config import BydConfig, DeviceProfile
from pybyd.models.vehicle import Vehicle

from .const import (
    CONF_BASE_URL,
    CONF_CONTROL_PIN,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_PROFILE,
    CONF_LANGUAGE,
    DEFAULT_LANGUAGE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _get_vehicle_name(vehicle: Vehicle) -> str:
    return vehicle.auto_alias or vehicle.model_name or vehicle.vin


class BydApi:
    """Thin wrapper around the pybyd client."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, session: Any) -> None:
        self._hass = hass
        self._entry = entry
        self._session = session
        time_zone = hass.config.time_zone or "UTC"
        device = DeviceProfile(**entry.data[CONF_DEVICE_PROFILE])
        self._config = BydConfig(
            username=entry.data["username"],
            password=entry.data["password"],
            base_url=entry.data[CONF_BASE_URL],
            country_code=entry.data.get(CONF_COUNTRY_CODE, "NL"),
            language=entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
            time_zone=time_zone,
            device=device,
            control_pin=entry.data.get(CONF_CONTROL_PIN) or None,
        )
        self._last_remote_results: dict[tuple[str, str], dict[str, Any]] = {}

    @property
    def config(self) -> BydConfig:
        return self._config

    def get_last_remote_result(self, vin: str, command: str) -> dict[str, Any] | None:
        return self._last_remote_results.get((vin, command))

    def _store_remote_result(
        self,
        vin: str,
        command: str,
        result: RemoteControlResult | None,
        error: Exception | None = None,
    ) -> None:
        data: dict[str, Any] = {
            "command": command,
            "success": False,
            "control_state": 0,
            "request_serial": None,
        }
        if result is not None:
            data.update(
                {
                    "success": result.success,
                    "control_state": result.control_state,
                    "request_serial": result.request_serial,
                    "raw": result.raw,
                }
            )
        if error is not None:
            data["error"] = str(error)
            data["error_type"] = type(error).__name__
        self._last_remote_results[(vin, command)] = data

    async def async_call(
        self,
        handler: Any,
        *,
        vin: str | None = None,
        command: str | None = None,
    ) -> Any:
        try:
            async with BydClient(self._config, session=self._session) as client:
                await client.login()
                result = await handler(client)
                if isinstance(result, RemoteControlResult) and vin and command:
                    self._store_remote_result(vin, command, result)
                return result
        except BydRemoteControlError as exc:
            if vin and command:
                self._store_remote_result(vin, command, None, exc)
            raise UpdateFailed(str(exc)) from exc
        except (BydAuthenticationError, BydApiError, BydTransportError) as exc:
            if vin and command:
                self._store_remote_result(vin, command, None, exc)
            raise UpdateFailed(str(exc)) from exc


class BydDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for normal telemetry updates."""

    def __init__(self, hass: HomeAssistant, api: BydApi, poll_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_telemetry",
            update_interval=timedelta(seconds=poll_interval),
        )
        self._api = api

    async def _async_update_data(self) -> dict[str, Any]:
        async def _fetch(client: BydClient) -> dict[str, Any]:
            vehicles = await client.get_vehicles()
            vehicle_map = {vehicle.vin: vehicle for vehicle in vehicles}

            async def _fetch_for_vin(
                vin: str,
            ) -> tuple[str, Any, Any, Any, Any]:
                realtime = await client.get_vehicle_realtime(vin)
                energy = await client.get_energy_consumption(vin)
                hvac = await client.get_hvac_status(vin)
                charging = await client.get_charging_status(vin)
                return vin, realtime, energy, hvac, charging

            tasks = [_fetch_for_vin(vin) for vin in vehicle_map]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            realtime_map: dict[str, Any] = {}
            energy_map: dict[str, Any] = {}
            hvac_map: dict[str, Any] = {}
            charging_map: dict[str, Any] = {}
            for result in results:
                if isinstance(result, BaseException):
                    _LOGGER.warning("Telemetry update failed: %s", result)
                    continue
                vin, realtime, energy, hvac, charging = result
                realtime_map[vin] = realtime
                energy_map[vin] = energy
                hvac_map[vin] = hvac
                charging_map[vin] = charging

            return {
                "vehicles": vehicle_map,
                "realtime": realtime_map,
                "energy": energy_map,
                "hvac": hvac_map,
                "charging": charging_map,
            }

        return await self._api.async_call(_fetch)


class BydGpsUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for GPS updates with optional smart polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: BydApi,
        poll_interval: int,
        *,
        telemetry_coordinator: BydDataUpdateCoordinator | None = None,
        smart_polling: bool = False,
        active_interval: int = 30,
        inactive_interval: int = 600,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_gps",
            update_interval=timedelta(seconds=poll_interval),
        )
        self._api = api
        self._telemetry_coordinator = telemetry_coordinator
        self._smart_polling = smart_polling
        self._active_interval = timedelta(seconds=active_interval)
        self._inactive_interval = timedelta(seconds=inactive_interval)
        self._last_smart_state: bool | None = None

    def _is_any_vehicle_online(self) -> bool:
        """Check if any vehicle reports online_state == 1 from telemetry data."""
        if self._telemetry_coordinator is None:
            return False
        data = self._telemetry_coordinator.data
        if not data or "realtime" not in data:
            return False
        for realtime in data["realtime"].values():
            if realtime is None:
                continue
            online = getattr(realtime, "online_state", None)
            if online == 1:
                return True
        return False

    def _adjust_interval(self) -> None:
        """Adjust the polling interval based on vehicle online state."""
        if not self._smart_polling:
            return
        is_online = self._is_any_vehicle_online()
        new_interval = self._active_interval if is_online else self._inactive_interval
        if self.update_interval != new_interval:
            _LOGGER.debug(
                "Smart GPS polling: vehicle %s, interval set to %ss",
                "online" if is_online else "offline",
                new_interval.total_seconds(),
            )
            self.update_interval = new_interval
            self._last_smart_state = is_online

    async def _async_update_data(self) -> dict[str, Any]:
        async def _fetch(client: BydClient) -> dict[str, Any]:
            vehicles = await client.get_vehicles()
            vehicle_map = {vehicle.vin: vehicle for vehicle in vehicles}

            async def _fetch_for_vin(vin: str) -> tuple[str, Any]:
                gps = await client.get_gps_info(vin)
                return vin, gps

            tasks = [_fetch_for_vin(vin) for vin in vehicle_map]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            gps_map: dict[str, Any] = {}
            for result in results:
                if isinstance(result, BaseException):
                    _LOGGER.warning("GPS update failed: %s", result)
                    continue
                vin, gps = result
                gps_map[vin] = gps

            return {
                "vehicles": vehicle_map,
                "gps": gps_map,
            }

        data = await self._api.async_call(_fetch)
        self._adjust_interval()
        return data


def get_vehicle_display(vehicle: Vehicle) -> str:
    """Return a friendly name for a vehicle."""
    return _get_vehicle_name(vehicle)
