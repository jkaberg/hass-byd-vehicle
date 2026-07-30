"""Data coordinators for BYD Vehicle."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from pybyd import (
    BydApiError,
    BydAuthenticationError,
    BydCar,
    BydClient,
    BydControlPasswordError,
    BydDataUnavailableError,
    BydEndpointNotSupportedError,
    BydRateLimitError,
    BydRemoteControlError,
    BydSessionExpiredError,
    BydTransportError,
    CommandAckEvent,
    CommandLifecycleEvent,
    VehicleSnapshot,
)
from pybyd.config import BydConfig, DeviceProfile
from pybyd.models.vehicle import Vehicle

from .const import (
    CONF_BASE_URL,
    CONF_CONTROL_PIN,
    CONF_COUNTRY_CODE,
    CONF_DEBUG_DUMPS,
    CONF_DEVICE_PROFILE,
    CONF_LANGUAGE,
    DEFAULT_DEBUG_DUMPS,
    DEFAULT_LANGUAGE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_HA_EVENT_COMMAND_LIFECYCLE: str = f"{DOMAIN}_command_lifecycle"

_AUTH_ERRORS = (BydAuthenticationError, BydSessionExpiredError)
_RECOVERABLE_ERRORS = (
    BydApiError,
    BydTransportError,
    BydRateLimitError,
    BydEndpointNotSupportedError,
)


class BydApi:
    """Thin wrapper around the pybyd client.

    Manages client lifecycle, exception translation, MQTT callback wiring,
    and debug dump writing.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, session: Any) -> None:
        self._hass = hass
        self._entry = entry
        self._http_session = session
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
        self._client: BydClient | None = None
        self._commands_enabled: bool = False
        self._commands_failed_reason: str | None = None
        self._verified_vin: str | None = None
        self._debug_dumps_enabled = entry.options.get(
            CONF_DEBUG_DUMPS,
            DEFAULT_DEBUG_DUMPS,
        )
        self._debug_dump_dir = Path(hass.config.path(".storage/byd_vehicle_debug"))
        self._coordinators: dict[str, BydDataUpdateCoordinator] = {}
        self._gps_coordinators: dict[str, BydGpsUpdateCoordinator] = {}
        _LOGGER.debug(
            "BYD API initialized: entry_id=%s, region=%s, language=%s",
            entry.entry_id,
            entry.data[CONF_BASE_URL],
            entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
        )

    # ------------------------------------------------------------------
    # Debug dumps
    # ------------------------------------------------------------------

    def _write_debug_dump(self, category: str, payload: dict[str, Any]) -> None:
        if not self._debug_dumps_enabled:
            return
        try:
            self._debug_dump_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S%fZ")
            file_path = self._debug_dump_dir / f"{timestamp}_{category}.json"
            file_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Failed to write BYD debug dump.", exc_info=True)

    async def _async_write_debug_dump(
        self,
        category: str,
        payload: dict[str, Any],
    ) -> None:
        await self._hass.async_add_executor_job(
            self._write_debug_dump, category, payload
        )

    # ------------------------------------------------------------------
    # pyBYD callbacks
    # ------------------------------------------------------------------

    def _handle_mqtt_event(
        self, event: str, vin: str, respond_data: dict[str, Any]
    ) -> None:
        """Handle generic MQTT events from pyBYD."""
        if self._debug_dumps_enabled:
            dump: dict[str, Any] = {
                "vin": vin,
                "mqtt_event": event,
                "respond_data": respond_data,
            }
            self._hass.async_create_task(
                self._async_write_debug_dump(f"mqtt_{event}", dump)
            )

    def _handle_command_ack(self, ack: CommandAckEvent) -> None:
        """Process a structured command ACK from pyBYD (diagnostics)."""
        _LOGGER.debug(
            "Command ack received: vin=%s serial=%s correlated=%s success=%s result=%s",
            ack.vin[-6:] if ack.vin else "-",
            ack.request_serial,
            ack.is_correlated,
            ack.success,
            ack.result,
        )

    def _handle_command_lifecycle(self, event: CommandLifecycleEvent) -> None:
        """Handle pyBYD-owned command lifecycle events."""
        payload: dict[str, Any] = {
            "vin": event.vin,
            "request_serial": event.request_serial,
            "status": event.status.value,
            "reason": event.reason,
            "command": event.command,
            "timestamp": event.timestamp,
        }
        if event.ack is not None:
            payload["ack_success"] = event.ack.success
            payload["ack_result"] = event.ack.result

        self._hass.bus.async_fire(_HA_EVENT_COMMAND_LIFECYCLE, payload)

        _LOGGER.debug(
            "Command lifecycle event: vin=%s serial=%s status=%s reason=%s",
            event.vin[-6:] if event.vin else "-",
            event.request_serial,
            event.status.value,
            event.reason,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_coordinators(
        self,
        coordinators: dict[str, BydDataUpdateCoordinator],
        gps_coordinators: dict[str, BydGpsUpdateCoordinator],
    ) -> None:
        """Register coordinators (used by on_state_changed)."""
        self._coordinators = coordinators
        self._gps_coordinators = gps_coordinators

    @property
    def config(self) -> BydConfig:
        return self._config

    @property
    def commands_enabled(self) -> bool:
        """Return True when command access has been verified."""
        return self._commands_enabled

    @property
    def commands_failed_reason(self) -> str | None:
        """Return the failure code from the last verify attempt, or None."""
        return self._commands_failed_reason

    @property
    def debug_dumps_enabled(self) -> bool:
        return self._debug_dumps_enabled

    async def async_write_debug_dump(
        self, category: str, payload: dict[str, Any]
    ) -> None:
        await self._async_write_debug_dump(category, payload)

    async def async_shutdown(self) -> None:
        await self._invalidate_client()

    async def async_verify_commands(self, vin: str) -> bool:
        """Verify the control PIN and enable remote commands.

        Returns ``True`` when verification succeeded, ``False`` otherwise.
        On failure the error code is stored in :attr:`commands_failed_reason`
        and a warning is logged.  Does **not** raise.
        """
        if not self._config.control_pin:
            _LOGGER.debug("No control PIN configured — skipping command verification")
            return False

        client = await self._ensure_client()
        try:
            await client.verify_command_access(vin)
        except BydControlPasswordError as exc:
            self._commands_enabled = False
            self._commands_failed_reason = exc.code
            if exc.code == "5006":
                _LOGGER.warning(
                    "BYD cloud control is temporarily locked; "
                    "command actions disabled (code=%s)",
                    exc.code,
                )
            else:
                _LOGGER.warning(
                    "Command PIN is wrong, disabled command actions (code=%s)",
                    exc.code,
                )
            return False
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "Command access verification failed unexpectedly; "
                "command actions disabled",
                exc_info=True,
            )
            self._commands_enabled = False
            self._commands_failed_reason = "verify_error"
            return False

        self._commands_enabled = True
        self._commands_failed_reason = None
        self._verified_vin = vin
        _LOGGER.info("Command access verified — remote control actions enabled")
        return True

    async def _ensure_client(self) -> BydClient:
        if self._client is None:
            _LOGGER.debug(
                "Creating new pyBYD client: entry_id=%s",
                self._entry.entry_id,
            )
            self._client = BydClient(
                self._config,
                session=self._http_session,
                on_mqtt_event=self._handle_mqtt_event,
                on_command_ack=self._handle_command_ack,
                on_command_lifecycle=self._handle_command_lifecycle,
            )
            await self._client.async_start()

            # Re-verify command access after client recreation.
            if self._verified_vin is not None and self._config.control_pin:
                await self.async_verify_commands(self._verified_vin)
        return self._client

    async def _invalidate_client(self) -> None:
        if self._client is not None:
            _LOGGER.debug(
                "Invalidating pyBYD client: entry_id=%s",
                self._entry.entry_id,
            )
            try:
                await self._client.async_close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
            self._commands_enabled = False

    async def async_get_car(self, vin: str, vehicle: Vehicle) -> BydCar:
        """Obtain a ``BydCar`` aggregate for *vin*.

        The ``on_state_changed`` callback triggers coordinator updates
        so that HA entities re-render immediately on any state change
        (including MQTT push and post-command projections).
        """
        client = await self._ensure_client()

        def _on_state_changed(changed_vin: str, snapshot: VehicleSnapshot) -> None:
            coordinator = self._coordinators.get(changed_vin)
            if coordinator is not None:
                coordinator._async_handle_state_push(snapshot)
            gps_coordinator = self._gps_coordinators.get(changed_vin)
            if gps_coordinator is not None:
                gps_coordinator._async_handle_state_push(snapshot)

        return await client.get_car(
            vin,
            vehicle=vehicle,
            on_state_changed=_on_state_changed,
        )

    async def async_call(
        self,
        handler: Any,
        *,
        vin: str | None = None,
        command: str | None = None,
    ) -> Any:
        """Execute a raw pyBYD call with error translation.

        Handles session expiry (re-auth), transport errors, rate limits,
        and authentication failures.  Used during initial setup and by
        the GPS coordinator.
        """
        call_started = perf_counter()
        _LOGGER.debug(
            "BYD API call started: entry_id=%s, vin=%s, command=%s",
            self._entry.entry_id,
            vin[-6:] if vin else "-",
            command or "-",
        )
        try:
            client = await self._ensure_client()
            result = await handler(client)
            _LOGGER.debug(
                "BYD API call succeeded: entry_id=%s, vin=%s, "
                "command=%s, duration_ms=%.1f",
                self._entry.entry_id,
                vin[-6:] if vin else "-",
                command or "-",
                (perf_counter() - call_started) * 1000,
            )
            return result
        except BydSessionExpiredError:
            await self._invalidate_client()
            try:
                client = await self._ensure_client()
                return await handler(client)
            except (
                BydSessionExpiredError,
                BydAuthenticationError,
            ) as retry_exc:
                raise ConfigEntryAuthFailed(str(retry_exc)) from retry_exc
            except (BydApiError, BydTransportError) as retry_exc:
                raise UpdateFailed(str(retry_exc)) from retry_exc
            except Exception as retry_exc:  # noqa: BLE001
                raise UpdateFailed(str(retry_exc)) from retry_exc
        except BydControlPasswordError as exc:
            self._commands_enabled = False
            self._commands_failed_reason = exc.code
            if exc.code == "5006":
                _LOGGER.warning(
                    "BYD cloud control is temporarily locked; "
                    "command actions disabled (code=%s)",
                    exc.code,
                )
            else:
                _LOGGER.warning(
                    "Command PIN is wrong, disabled command actions (code=%s)",
                    exc.code,
                )
            raise UpdateFailed(
                "Control PIN rejected or cloud control temporarily locked"
            ) from exc
        except BydRateLimitError as exc:
            raise UpdateFailed(
                "Command rate limited by BYD cloud, please retry shortly"
            ) from exc
        except BydEndpointNotSupportedError as exc:
            raise UpdateFailed("Feature not supported for this vehicle/region") from exc
        except BydTransportError as exc:
            await self._invalidate_client()
            raise UpdateFailed(str(exc)) from exc
        except BydAuthenticationError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except BydApiError as exc:
            raise UpdateFailed(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "BYD API call failed: entry_id=%s, vin=%s, command=%s, "
                "duration_ms=%.1f, error=%s",
                self._entry.entry_id,
                vin[-6:] if vin else "-",
                command or "-",
                (perf_counter() - call_started) * 1000,
                type(exc).__name__,
            )
            raise


class BydDataUpdateCoordinator(DataUpdateCoordinator[VehicleSnapshot]):
    """Coordinator for telemetry + HVAC updates for a single VIN.

    Holds a ``BydCar`` reference (set after first refresh).
    ``_async_update_data()`` calls ``car.update_realtime()`` and
    conditionally ``car.update_hvac()``, then returns ``car.state``.
    Receives state-change callbacks from the state engine, which
    trigger ``async_set_updated_data(car.state)``.
    Retains ``_should_fetch_hvac()`` as consumer-side optimisation.

    When realtime transitions from ON -> OFF, performs a final HVAC
    reconcile immediately and schedules one delayed retry to avoid stale
    HVAC/seat states when the vehicle powers down.
    """

    _HVAC_FINAL_RECONCILE_RETRY_DELAY_SECONDS = 60

    # Override parent annotations: ``data`` is None until first refresh,
    # and we assign ``update_interval = None`` to pause polling (HA
    # accepts None at runtime; the stub doesn't mark it Optional).
    data: VehicleSnapshot | None
    update_interval: timedelta | None

    def __init__(
        self,
        hass: HomeAssistant,
        api: BydApi,
        vehicle: Vehicle,
        vin: str,
        poll_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_telemetry_{vin[-6:]}",
            update_interval=timedelta(seconds=poll_interval),
        )
        self._api = api
        self._vehicle = vehicle
        self._vin = vin
        self._fixed_interval = timedelta(seconds=poll_interval)
        self._polling_enabled = True
        self._force_next_refresh = False
        self._car: BydCar | None = None
        self._realtime_endpoint_unsupported: bool = False
        # ``getEnergyConsumption`` returns ``code=1001`` on several VINs
        # (notably the Sealion 7 EU trim).  pyBYD translates that to
        # ``BydEndpointNotSupportedError``; we record it here so the
        # service handler only logs the warning once instead of on
        # every press of the fetch button.
        self._energy_endpoint_unsupported: bool = False
        self._cancel_hvac_final_retry: CALLBACK_TYPE | None = None
        self.update_pending: bool = False
        self._debounce_timer: CALLBACK_TYPE | None = None
        self._pending_schedule_updates: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # State-engine push
    # ------------------------------------------------------------------

    @callback
    def _async_handle_state_push(self, snapshot: VehicleSnapshot) -> None:
        """Update from a state-engine push and reset next poll from this update."""
        previous_snapshot = self.data
        self._schedule_hvac_final_reconcile_if_needed(previous_snapshot, snapshot)

        previous_timestamp = None
        if previous_snapshot is not None and previous_snapshot.realtime is not None:
            previous_timestamp = getattr(previous_snapshot.realtime, "timestamp", None)

        current_timestamp = None
        if snapshot.realtime is not None:
            current_timestamp = getattr(snapshot.realtime, "timestamp", None)

        if current_timestamp is not None and current_timestamp != previous_timestamp:
            self.async_set_updated_data(snapshot)
            return

        self.data = snapshot
        self.last_update_success = True
        self.async_update_listeners()

    @callback
    def _cancel_pending_hvac_final_retry(self) -> None:
        """Cancel any scheduled delayed HVAC final-reconcile retry."""
        if self._cancel_hvac_final_retry is not None:
            self._cancel_hvac_final_retry()
            self._cancel_hvac_final_retry = None

    @callback
    def _schedule_hvac_final_reconcile_if_needed(
        self,
        previous_snapshot: VehicleSnapshot | None,
        current_snapshot: VehicleSnapshot | None,
    ) -> None:
        """Schedule immediate + delayed HVAC reconcile on ON->OFF transition."""
        was_on = self._is_vehicle_on_from_snapshot(previous_snapshot) is True
        is_on = self._is_vehicle_on_from_snapshot(current_snapshot) is True

        if not was_on:
            return

        if is_on:
            self._cancel_pending_hvac_final_retry()
            return

        _LOGGER.debug(
            "Vehicle transitioned OFF, scheduling final HVAC reconcile: vin=%s",
            self._vin[-6:],
        )

        self._cancel_pending_hvac_final_retry()
        self.hass.async_create_task(self._async_run_hvac_final_reconcile(attempt=1))

        @callback
        def _retry(_now: Any) -> None:
            self._cancel_hvac_final_retry = None
            self.hass.async_create_task(self._async_run_hvac_final_reconcile(attempt=2))

        self._cancel_hvac_final_retry = async_call_later(
            self.hass,
            self._HVAC_FINAL_RECONCILE_RETRY_DELAY_SECONDS,
            _retry,
        )

    async def _async_run_hvac_final_reconcile(self, *, attempt: int) -> None:
        """Run one HVAC reconcile attempt after an ON->OFF transition."""
        if not self._polling_enabled:
            _LOGGER.debug(
                "Skipping final HVAC reconcile (polling disabled): vin=%s, attempt=%s",
                self._vin[-6:],
                attempt,
            )
            return

        car = self._car
        if car is None:
            return

        _LOGGER.debug(
            "Running final HVAC reconcile: vin=%s, attempt=%s",
            self._vin[-6:],
            attempt,
        )

        try:
            await car.update_hvac()
        except _AUTH_ERRORS:
            raise
        except _RECOVERABLE_ERRORS as exc:
            _LOGGER.debug(
                "Final HVAC reconcile failed: vin=%s, attempt=%s, error=%s",
                self._vin,
                attempt,
                exc,
            )

        snapshot = car.state
        if snapshot.hvac is not None:
            self.async_set_updated_data(snapshot)

    @property
    def car(self) -> BydCar | None:
        """Return the ``BydCar`` instance if available."""
        return self._car

    @property
    def vehicle(self) -> Vehicle:
        return self._vehicle

    @property
    def has_pin_configured(self) -> bool:
        """Return True when a non-empty control PIN exists in config."""
        pin = self._api.config.control_pin
        return isinstance(pin, str) and bool(pin.strip())

    @property
    def has_operation_pin(self) -> bool:
        """Return True when a PIN is configured **and** command access verified."""
        return self.has_pin_configured and self._api.commands_enabled

    @property
    def vin(self) -> str:
        return self._vin

    @staticmethod
    def _is_vehicle_on_from_snapshot(
        snapshot: VehicleSnapshot | None,
    ) -> bool | None:
        if snapshot is None or snapshot.realtime is None:
            return None
        return snapshot.realtime.is_vehicle_on

    @property
    def is_vehicle_on(self) -> bool:
        return self._is_vehicle_on_from_snapshot(self.data) is True

    def capability_available(self, capability_key: str) -> bool:
        """Return capability availability from pyBYD.

        Missing capability metadata is treated as unavailable.
        """
        car = self._car
        if car is None:
            return False
        capabilities = getattr(car, "capabilities", None)
        if capabilities is None:
            return False
        value = getattr(capabilities, capability_key, None)
        return bool(value)

    def _should_fetch_hvac(
        self,
        snapshot: VehicleSnapshot | None,
        *,
        force: bool = False,
    ) -> bool:
        """Decide whether HVAC data should be fetched."""
        if force:
            return True
        if snapshot is not None and snapshot.hvac is None:
            return True
        return self._is_vehicle_on_from_snapshot(snapshot) is True

    async def _async_update_data(self) -> VehicleSnapshot:
        """Fetch telemetry + conditional HVAC and return car.state."""
        _LOGGER.debug("Telemetry refresh started: vin=%s", self._vin[-6:])
        force = self._force_next_refresh
        self._force_next_refresh = False
        previous_snapshot = self.data

        if self.update_pending:
            _LOGGER.debug(
                "Skipping telemetry refresh due to pending schedule update: vin=%s",
                self._vin[-6:],
            )
            if self.data is not None:
                return self.data
            return VehicleSnapshot(vehicle=self._vehicle)

        if not self._polling_enabled and not force:
            if self.data is not None:
                return self.data
            return VehicleSnapshot(vehicle=self._vehicle)

        if self._car is None:
            self._car = await self._api.async_get_car(self._vin, self._vehicle)

        car = self._car

        # --- Realtime ---
        try:
            await car.update_realtime()
        except _AUTH_ERRORS:
            raise
        except BydEndpointNotSupportedError:
            if not self._realtime_endpoint_unsupported:
                _LOGGER.warning(
                    "Realtime HTTP endpoint not supported for vin=%s — "
                    "will rely on MQTT push (logged once only)",
                    self._vin,
                )
                self._realtime_endpoint_unsupported = True
        except _RECOVERABLE_ERRORS as exc:
            _LOGGER.warning(
                "Realtime fetch failed: vin=%s, error=%s",
                self._vin,
                exc,
            )

        # --- HVAC (conditional) ---
        if self._should_fetch_hvac(car.state, force=force):
            try:
                await car.update_hvac()
            except _AUTH_ERRORS:
                raise
            except _RECOVERABLE_ERRORS as exc:
                _LOGGER.warning(
                    "HVAC fetch failed: vin=%s, error=%s",
                    self._vin,
                    exc,
                )
        else:
            _LOGGER.debug(
                "HVAC fetch skipped: vin=%s, reason=vehicle_not_on",
                self._vin[-6:],
            )

        # --- Charging (Schedule & Live) ---
        try:
            await car.update_charging()
        except _AUTH_ERRORS:
            raise
        except _RECOVERABLE_ERRORS as exc:
            _LOGGER.warning(
                "Charging fetch failed: vin=%s, error=%s",
                self._vin,
                exc,
            )

        snapshot = car.state
        self._schedule_hvac_final_reconcile_if_needed(previous_snapshot, snapshot)

        # Bail if we still have no realtime data at all
        if snapshot.realtime is None and not self._realtime_endpoint_unsupported:
            raise UpdateFailed(
                f"Realtime state unavailable for {self._vin}; no data returned from API"
            )

        # Debug dump
        if self._api.debug_dumps_enabled:
            dump: dict[str, Any] = {"vin": self._vin, "sections": {}}
            if snapshot.realtime is not None:
                dump["sections"]["realtime"] = snapshot.realtime.model_dump(mode="json")
            if snapshot.hvac is not None:
                dump["sections"]["hvac"] = snapshot.hvac.model_dump(mode="json")
            self.hass.async_create_task(
                self._api.async_write_debug_dump("telemetry", dump)
            )

        _LOGGER.debug(
            "Telemetry refresh succeeded: vin=%s, realtime=%s, hvac=%s",
            self._vin[-6:],
            snapshot.realtime is not None,
            snapshot.hvac is not None,
        )
        return snapshot

    # ------------------------------------------------------------------
    # Polling control
    # ------------------------------------------------------------------

    @property
    def polling_enabled(self) -> bool:
        return self._polling_enabled

    @property
    def poll_interval_seconds(self) -> int:
        """Return the configured telemetry poll interval in seconds."""
        return int(self._fixed_interval.total_seconds())

    def set_poll_interval(self, seconds: int) -> None:
        """Set telemetry poll interval in seconds."""
        self._fixed_interval = timedelta(seconds=seconds)
        if self._polling_enabled:
            self.update_interval = self._fixed_interval
        self.async_update_listeners()

    def set_polling_enabled(self, enabled: bool) -> bool:
        was_enabled = self._polling_enabled
        self._polling_enabled = bool(enabled)
        if not self._polling_enabled:
            self._cancel_pending_hvac_final_retry()
        self.update_interval = self._fixed_interval if self._polling_enabled else None
        return not was_enabled and self._polling_enabled

    async def async_set_polling_enabled(self, enabled: bool) -> None:
        """Update polling state and resume scheduling when re-enabled."""
        if self.set_polling_enabled(enabled):
            await self.async_request_refresh()

    async def async_force_refresh(self) -> None:
        self._force_next_refresh = True
        await self.async_request_refresh()

    # ------------------------------------------------------------------
    # Service helpers — direct BydCar calls
    # ------------------------------------------------------------------

    async def async_fetch_realtime(self) -> None:
        """Service handler: fetch fresh realtime via BydCar."""
        if self._car is None:
            return
        try:
            result = await self._car.update_realtime()
            _LOGGER.info(
                "fetch_realtime result: vin=%s, payload=%s",
                self._vin[-6:],
                result,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Service fetch_realtime failed: vin=%s, error=%s",
                self._vin,
                exc,
            )

    async def async_fetch_hvac(self) -> None:
        """Service handler: fetch fresh HVAC via BydCar."""
        if self._car is None:
            return
        try:
            result = await self._car.update_hvac()
            _LOGGER.info(
                "fetch_hvac result: vin=%s, payload=%s",
                self._vin[-6:],
                result,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Service fetch_hvac failed: vin=%s, error=%s",
                self._vin,
                exc,
            )

    async def async_fetch_charging(self) -> None:
        """Service handler: refresh charging state + schedule from one homePage call.

        Hits ``/control/smartCharge/homePage`` once and updates both the
        live charging snapshot section (also pushed via MQTT) and the
        schedule section (HTTP-only).  Pushes the refreshed snapshot
        out so dependent sensors update immediately.
        """
        if self._car is None:
            return
        try:
            result = await self._car.update_charging()
            _LOGGER.info(
                "fetch_charging result: vin=%s, payload=%s",
                self._vin[-6:],
                result,
            )
            self.async_set_updated_data(self._car.state)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Service fetch_charging failed: vin=%s, error=%s",
                self._vin,
                exc,
            )

    async def async_fetch_energy(self) -> None:
        """Service handler: fetch energy consumption and log the raw response.

        ``getEnergyConsumption`` is one of the endpoints BYD's cloud
        marks as ``code=1001`` on some VINs (pyBYD translates that to
        :class:`BydEndpointNotSupportedError`).  When that happens the
        ``energy_last_50km_*`` sensors will never populate from this
        endpoint, so we log the warning once and bail quietly on
        subsequent presses instead of spamming on every retry.
        """
        if self._car is None:
            return
        try:
            result = await self._car.update_energy()
        except BydEndpointNotSupportedError as exc:
            if not self._energy_endpoint_unsupported:
                _LOGGER.warning(
                    "Energy endpoint not supported for vin=%s — "
                    "energy_last_50km_* sensors will stay unavailable "
                    "(logged once only): %s",
                    self._vin,
                    exc,
                )
                self._energy_endpoint_unsupported = True
            return
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Service fetch_energy failed: vin=%s, error=%s",
                self._vin,
                exc,
            )
            return
        # Success: clear the unsupported flag in case the VIN's
        # capability changed (e.g. after a TBOX firmware update).
        self._energy_endpoint_unsupported = False
        _LOGGER.info(
            "fetch_energy result: vin=%s, payload=%s",
            self._vin[-6:],
            result,
        )

    async def async_request_schedule_update(
        self, property_name: str, new_value: Any
    ) -> None:
        """Queue a debounced update for the charging schedule."""
        self._pending_schedule_updates[property_name] = new_value

        if self._debounce_timer is not None:
            self._debounce_timer()
            self._debounce_timer = None

        self.update_pending = True

        @callback
        def _execute_update(_now: Any) -> None:
            self._debounce_timer = None
            self.hass.async_create_task(self._async_execute_schedule_update())

        self._debounce_timer = async_call_later(
            self.hass,
            10.0,
            _execute_update,
        )

    async def _async_execute_schedule_update(self) -> None:
        """Execute the pending schedule update."""
        if not self._pending_schedule_updates:
            self.update_pending = False
            return

        current_enabled = True
        current_charge_to_full = True
        current_start_time = "22:00"
        current_end_time = "full"
        current_charge_way = "e"

        if (
            self.data
            and self.data.charging_schedule
            and self.data.charging_schedule.charge
        ):
            charge = self.data.charging_schedule.charge
            if charge.status is not None:
                current_enabled = charge.status
            if charge.charge_until_full is not None:
                current_charge_to_full = charge.charge_until_full

            if charge.start_time is not None:
                current_start_time = charge.start_time.strftime("%H:%M")
            if charge.end_time is not None:
                current_end_time = charge.end_time.strftime("%H:%M")

            if charge.charge_way is not None:
                current_charge_way = charge.charge_way

        updates = self._pending_schedule_updates

        enabled = updates.get("enabled", current_enabled)
        charge_to_full = updates.get("charge_to_full", current_charge_to_full)
        pattern = updates.get("pattern", current_charge_way)
        start_time_obj = updates.get("start_time")
        end_time_obj = updates.get("end_time")

        start_charge_time = (
            start_time_obj.strftime("%H:%M") if start_time_obj else current_start_time
        )

        if charge_to_full:
            end_charge_time = "full"
        else:
            end_charge_time = (
                end_time_obj.strftime("%H:%M") if end_time_obj else current_end_time
            )
            if end_charge_time == "full":
                end_charge_time = "06:00"

        charge_way = pattern

        self._pending_schedule_updates.clear()

        try:
            await self.async_save_charging_schedule(
                start_charge_time=start_charge_time,
                end_charge_time=end_charge_time,
                charge_way=charge_way,
                enabled=enabled,
            )
        except Exception as exc:
            _LOGGER.error("Debounced schedule save failed: %s", exc)
        finally:
            self.update_pending = False
            await self.async_request_refresh()

    async def async_save_charging_schedule(
        self,
        *,
        start_charge_time: str,
        end_charge_time: str,
        charge_way: str,
        enabled: bool = True,
    ) -> None:
        """Push a new smart-charging schedule and refresh the snapshot.

        Wire format follows the captured ``saveOrUpdate`` request:
        ``startChargeTime`` / ``endChargeTime`` are ``"HH:MM"`` strings
        (or the ``"full"`` sentinel on end), ``chargeWay`` selects the
        repeat (``"s"`` / ``"e"`` / comma-separated weekday indices),
        ``status`` is the enabled flag.
        """
        if self._car is None:
            raise HomeAssistantError(
                f"BYD vehicle {self._vin[-6:]} not ready for charging commands"
            )
        try:
            await self._car.save_charging_schedule(
                start_charge_time=start_charge_time,
                end_charge_time=end_charge_time,
                charge_way=charge_way,
                enabled=enabled,
            )
        except BydEndpointNotSupportedError as exc:
            raise HomeAssistantError(
                "save_charging_schedule not supported for this vehicle/region"
            ) from exc
        except BydDataUnavailableError as exc:
            # BYD code 6002: cloud accepted the request but couldn't
            # reach the vehicle (weak cellular signal, parked in a
            # garage, etc.).  Recoverable — surface a friendlier
            # message than the raw "endpoint failed: code=6002 …".
            raise HomeAssistantError(
                "Vehicle has a weak network signal — try again when "
                "it's back in coverage"
            ) from exc
        except BydRemoteControlError as exc:
            raise HomeAssistantError(
                f"save_charging_schedule failed to settle: {exc}"
            ) from exc
        except BydAuthenticationError as exc:
            raise HomeAssistantError(
                f"save_charging_schedule failed (auth): {exc}"
            ) from exc
        except (BydApiError, BydTransportError) as exc:
            raise HomeAssistantError(f"save_charging_schedule failed: {exc}") from exc

        _LOGGER.info(
            "save_charging_schedule accepted: vin=%s, "
            "start=%s end=%s charge_way=%s enabled=%s",
            self._vin[-6:],
            start_charge_time,
            end_charge_time,
            charge_way,
            enabled,
        )
        # ``car.save_charging_schedule`` polls ``changeResult`` until
        # the cloud reports a terminal state and then refreshes the
        # snapshot via ``update_charging`` — push the new snapshot out
        # to subscribers so dependent sensors update immediately.
        self.async_set_updated_data(self._car.state)

    async def async_start_charging(self) -> None:
        """Start charging immediately and refresh charging state on success.

        Raises :class:`HomeAssistantError` on failure (auth, transport,
        unsupported endpoint, polling timeout) so service callers see a
        loud failure rather than a silent no-op.
        """
        if self._car is None:
            raise HomeAssistantError(
                f"BYD vehicle {self._vin[-6:]} not ready for charging commands"
            )
        try:
            result = await self._car.start_charging()
        except BydEndpointNotSupportedError as exc:
            raise HomeAssistantError(
                "start_charging not supported for this vehicle/region"
            ) from exc
        except BydRemoteControlError as exc:
            raise HomeAssistantError(f"start_charging failed to settle: {exc}") from exc
        except BydAuthenticationError as exc:
            raise HomeAssistantError(f"start_charging failed (auth): {exc}") from exc
        except (BydApiError, BydTransportError) as exc:
            raise HomeAssistantError(f"start_charging failed: {exc}") from exc

        _LOGGER.info(
            "start_charging settled: vin=%s, message=%s",
            self._vin[-6:],
            result.message,
        )

        try:
            await self._car.update_charging()
            await self.async_request_refresh()
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Post-start_charging refresh failed (non-fatal)",
                exc_info=True,
            )


class BydGpsUpdateCoordinator(DataUpdateCoordinator[VehicleSnapshot]):
    """Coordinator for GPS updates for a single VIN.

    Uses the ``BydCar`` from the telemetry coordinator so GPS data flows
    through the same state engine and benefits from the value-quality
    validators (Null Island rejection).
    """

    # See note on BydDataUpdateCoordinator above — same parent annotations.
    data: VehicleSnapshot | None
    update_interval: timedelta | None

    def __init__(
        self,
        hass: HomeAssistant,
        api: BydApi,
        vehicle: Vehicle,
        vin: str,
        poll_interval: int,
        *,
        telemetry_coordinator: BydDataUpdateCoordinator | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_gps_{vin[-6:]}",
            update_interval=timedelta(seconds=poll_interval),
        )
        self._api = api
        self._vehicle = vehicle
        self._vin = vin
        self._telemetry_coordinator = telemetry_coordinator
        self._fixed_interval = timedelta(seconds=poll_interval)
        self._polling_enabled = True
        self._force_next_refresh = False

    @property
    def polling_enabled(self) -> bool:
        return self._polling_enabled

    @property
    def poll_interval_seconds(self) -> int:
        """Return the configured GPS poll interval in seconds."""
        return int(self._fixed_interval.total_seconds())

    def set_poll_interval(self, seconds: int) -> None:
        """Set GPS poll interval in seconds."""
        self._fixed_interval = timedelta(seconds=seconds)
        if self._polling_enabled:
            self.update_interval = self._fixed_interval
        self.async_update_listeners()

    def set_polling_enabled(self, enabled: bool) -> bool:
        was_enabled = self._polling_enabled
        self._polling_enabled = bool(enabled)
        self.update_interval = self._fixed_interval if self._polling_enabled else None
        return not was_enabled and self._polling_enabled

    async def async_set_polling_enabled(self, enabled: bool) -> None:
        """Update polling state and resume scheduling when re-enabled."""
        if self.set_polling_enabled(enabled):
            await self.async_request_refresh()

    async def async_force_refresh(self) -> None:
        self._force_next_refresh = True
        await self.async_request_refresh()

    async def async_fetch_gps(self) -> None:
        """Service handler: fetch fresh GPS via BydCar."""
        car = self._get_car()
        if car is None:
            return
        try:
            result = await car.update_gps()
            _LOGGER.info(
                "fetch_gps result: vin=%s, payload=%s",
                self._vin[-6:],
                result,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Service fetch_gps failed: vin=%s, error=%s",
                self._vin,
                exc,
            )

    def _get_car(self) -> BydCar | None:
        """Return BydCar from telemetry coordinator."""
        if self._telemetry_coordinator is not None:
            return self._telemetry_coordinator.car
        return None

    @callback
    def _async_handle_state_push(self, snapshot: VehicleSnapshot) -> None:
        """Update GPS state from a push and reset next poll on new GPS timestamp."""
        if snapshot.gps is None:
            return

        previous_timestamp = None
        if self.data is not None and self.data.gps is not None:
            previous_timestamp = getattr(self.data.gps, "gps_timestamp", None)

        current_timestamp = getattr(snapshot.gps, "gps_timestamp", None)

        if current_timestamp is not None and current_timestamp != previous_timestamp:
            self.async_set_updated_data(snapshot)
            return

        self.data = snapshot
        self.last_update_success = True
        self.async_update_listeners()

    async def _async_update_data(self) -> VehicleSnapshot:
        """Fetch GPS data and return the current car state snapshot."""
        _LOGGER.debug("GPS refresh started: vin=%s", self._vin[-6:])
        force = self._force_next_refresh
        self._force_next_refresh = False

        if not self._polling_enabled and not force:
            if self.data is not None:
                return self.data
            return VehicleSnapshot(vehicle=self._vehicle)

        car = self._get_car()
        if car is None:
            if self.data is not None:
                return self.data
            return VehicleSnapshot(vehicle=self._vehicle)

        try:
            await car.update_gps()
        except _AUTH_ERRORS:
            raise
        except BydDataUnavailableError:
            _LOGGER.debug(
                "GPS data unavailable (vehicle may lack signal): vin=%s",
                self._vin,
            )
        except _RECOVERABLE_ERRORS as exc:
            _LOGGER.warning("GPS fetch failed: vin=%s, error=%s", self._vin, exc)

        snapshot = car.state
        if snapshot.gps is None:
            if self.data is not None:
                _LOGGER.debug(
                    "GPS unavailable, preserving last known position: vin=%s",
                    self._vin,
                )
                return self.data
            return VehicleSnapshot(vehicle=self._vehicle)

        if self._api.debug_dumps_enabled and snapshot.gps is not None:
            dump: dict[str, Any] = {
                "vin": self._vin,
                "sections": {"gps": snapshot.gps.model_dump(mode="json")},
            }
            self.hass.async_create_task(self._api.async_write_debug_dump("gps", dump))
        _LOGGER.debug(
            "GPS refresh succeeded: vin=%s, gps=%s",
            self._vin[-6:],
            snapshot.gps is not None,
        )
        return snapshot


def get_vehicle_display(vehicle: Vehicle) -> str:
    return vehicle.model_name or vehicle.vin
