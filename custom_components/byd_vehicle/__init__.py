"""BYD Vehicle integration."""

from __future__ import annotations

# _vendor/ override: if a sibling _vendor/ directory exists, prepend it to
# sys.path and evict any already-imported pybyd modules so the next
# ``import pybyd`` resolves to the vendored copy. No-op when absent, so
# the manifest-pinned pybyd is used. See HA_LOCAL_OVERRIDE.md.
import sys as _sys
from pathlib import Path as _Path

_vendor_path = _Path(__file__).parent / "_vendor"
if _vendor_path.is_dir():
    _vendor_str = str(_vendor_path)
    if _vendor_str not in _sys.path:
        _sys.path.insert(0, _vendor_str)
    for _name in list(_sys.modules):
        if _name == "pybyd" or _name.startswith("pybyd."):
            del _sys.modules[_name]
del _sys, _Path, _vendor_path

import logging
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pybyd import BydClient

from .const import (
    CONF_BASE_URL,
    CONF_CONTROL_PIN,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_PROFILE,
    CONF_GPS_POLL_INTERVAL,
    CONF_LANGUAGE,
    CONF_POLL_INTERVAL,
    DEFAULT_COUNTRY,
    DEFAULT_GPS_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_GPS_POLL_INTERVAL,
    MAX_POLL_INTERVAL,
    MIN_GPS_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    PLATFORMS,
    get_country_connection_settings,
    get_country_connection_settings_by_code,
)
from .coordinator import BydApi, BydDataUpdateCoordinator, BydGpsUpdateCoordinator
from .device_fingerprint import async_generate_device_profile

_LOGGER = logging.getLogger(__name__)


def _sanitize_interval(value: int, default: int, min_value: int, max_value: int) -> int:
    """Clamp interval values so stale options cannot break scheduling."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, parsed))


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entries to latest schema."""
    _LOGGER.debug(
        "Migrating BYD config entry %s from version %s",
        entry.entry_id,
        entry.version,
    )

    if entry.version > 3:
        _LOGGER.error(
            "Cannot migrate BYD config entry %s from version %s",
            entry.entry_id,
            entry.version,
        )
        return False

    if entry.version < 2:
        options = dict(entry.options)

        options.pop("smart_gps_polling", None)
        options.pop("gps_active_interval", None)
        options.pop("gps_inactive_interval", None)

        options[CONF_POLL_INTERVAL] = _sanitize_interval(
            options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
            DEFAULT_POLL_INTERVAL,
            MIN_POLL_INTERVAL,
            MAX_POLL_INTERVAL,
        )
        _sanitize_interval(
            options.get(CONF_GPS_POLL_INTERVAL, DEFAULT_GPS_POLL_INTERVAL),
            DEFAULT_GPS_POLL_INTERVAL,
            MIN_GPS_POLL_INTERVAL,
            MAX_GPS_POLL_INTERVAL,
        )
        options[CONF_GPS_POLL_INTERVAL] = DEFAULT_GPS_POLL_INTERVAL

        hass.config_entries.async_update_entry(entry, options=options)

    if entry.version < 3:
        data = dict(entry.data)
        raw_country_code = data.get(CONF_COUNTRY_CODE)

        try:
            country_code, language, base_url = get_country_connection_settings_by_code(
                str(raw_country_code)
            )
        except (KeyError, AttributeError):
            country_code, language, base_url = get_country_connection_settings(
                DEFAULT_COUNTRY
            )
            _LOGGER.warning(
                (
                    "Entry %s had unknown country code %s; "
                    "defaulting to %s during migration"
                ),
                entry.entry_id,
                raw_country_code,
                DEFAULT_COUNTRY,
            )

        data[CONF_COUNTRY_CODE] = country_code
        data[CONF_LANGUAGE] = language
        data[CONF_BASE_URL] = base_url

        new_unique_id = entry.unique_id
        username = data.get("username")
        if isinstance(username, str) and username:
            new_unique_id = f"{username}@{base_url}"

        hass.config_entries.async_update_entry(
            entry,
            data=data,
            unique_id=new_unique_id,
        )

    _LOGGER.debug("Migration of BYD config entry %s complete", entry.entry_id)
    return True


def _apply_poll_intervals_from_options(
    entry: ConfigEntry,
    entry_data: dict[str, Any],
) -> None:
    """Apply poll intervals from entry options to all coordinators."""
    poll_interval = _sanitize_interval(
        entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        DEFAULT_POLL_INTERVAL,
        MIN_POLL_INTERVAL,
        MAX_POLL_INTERVAL,
    )
    gps_interval = _sanitize_interval(
        entry.options.get(CONF_GPS_POLL_INTERVAL, DEFAULT_GPS_POLL_INTERVAL),
        DEFAULT_GPS_POLL_INTERVAL,
        MIN_GPS_POLL_INTERVAL,
        MAX_GPS_POLL_INTERVAL,
    )

    for coordinator in entry_data.get("coordinators", {}).values():
        coordinator.set_poll_interval(poll_interval)
    for gps_coordinator in entry_data.get("gps_coordinators", {}).values():
        gps_coordinator.set_poll_interval(gps_interval)


async def _async_handle_entry_update(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry option updates."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is None:
        return

    previous_options = entry_data.get("options_snapshot", {})
    current_options = dict(entry.options)
    entry_data["options_snapshot"] = current_options

    changed_keys = {
        key
        for key in set(previous_options) | set(current_options)
        if previous_options.get(key) != current_options.get(key)
    }
    poll_keys = {CONF_POLL_INTERVAL, CONF_GPS_POLL_INTERVAL}

    if changed_keys and changed_keys.issubset(poll_keys):
        _apply_poll_intervals_from_options(entry, entry_data)
        return

    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BYD Vehicle from a config entry."""
    _LOGGER.debug("Setting up BYD config entry %s", entry.entry_id)
    hass.data.setdefault(DOMAIN, {})

    # Dismiss any stale PIN-invalid notification from a prior run.
    notification_id = f"{DOMAIN}_{entry.entry_id}_pin_invalid"
    persistent_notification.async_dismiss(hass, notification_id)

    # Ensure a device fingerprint exists (backfill for pre-existing entries)
    if CONF_DEVICE_PROFILE not in entry.data:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_DEVICE_PROFILE: await async_generate_device_profile(hass),
            },
        )

    session = async_get_clientsession(hass)
    api = BydApi(hass, entry, session)

    poll_interval = _sanitize_interval(
        entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        DEFAULT_POLL_INTERVAL,
        MIN_POLL_INTERVAL,
        MAX_POLL_INTERVAL,
    )
    gps_interval = _sanitize_interval(
        entry.options.get(CONF_GPS_POLL_INTERVAL, DEFAULT_GPS_POLL_INTERVAL),
        DEFAULT_GPS_POLL_INTERVAL,
        MIN_GPS_POLL_INTERVAL,
        MAX_GPS_POLL_INTERVAL,
    )

    async def _fetch_vehicles(client: BydClient) -> list:
        return await client.get_vehicles()

    vehicles = await api.async_call(_fetch_vehicles)
    if not vehicles:
        raise ConfigEntryNotReady("No vehicles available for this account")

    _LOGGER.debug(
        "Discovered %s BYD vehicle(s) for entry %s",
        len(vehicles),
        entry.entry_id,
    )

    # Verify command access when a control PIN is configured.
    if entry.data.get(CONF_CONTROL_PIN):
        pin_ok = await api.async_verify_commands(vehicles[0].vin)
        if not pin_ok:
            persistent_notification.async_create(
                hass,
                (
                    "The Control PIN is incorrect or cloud control is "
                    "temporarily locked. Remote control actions are disabled. "
                    "Please reconfigure the integration to update your "
                    "Control PIN."
                ),
                title="BYD Vehicle: Command PIN invalid",
                notification_id=notification_id,
            )

    coordinators: dict[str, BydDataUpdateCoordinator] = {}
    gps_coordinators: dict[str, BydGpsUpdateCoordinator] = {}

    for vehicle in vehicles:
        vin = vehicle.vin
        telemetry_coordinator = BydDataUpdateCoordinator(
            hass,
            api,
            vehicle,
            vin,
            poll_interval,
        )
        gps_coordinator = BydGpsUpdateCoordinator(
            hass,
            api,
            vehicle,
            vin,
            gps_interval,
            telemetry_coordinator=telemetry_coordinator,
        )
        coordinators[vin] = telemetry_coordinator
        gps_coordinators[vin] = gps_coordinator

    # Wire MQTT push early so vehicleInfo messages arriving during the
    # first refresh are dispatched to coordinators instead of being dropped.
    api.register_coordinators(coordinators, gps_coordinators)

    try:
        _LOGGER.debug("Running first refresh for BYD telemetry coordinators")
        for coordinator in coordinators.values():
            await coordinator.async_config_entry_first_refresh()
        _LOGGER.debug("Running first refresh for BYD GPS coordinators")
        for gps_coordinator in gps_coordinators.values():
            await gps_coordinator.async_config_entry_first_refresh()
    except Exception as exc:  # noqa: BLE001
        raise ConfigEntryNotReady from exc

    # One-shot energy fetch so the EnergyConsumption-backed sensors are
    # populated at startup. Subsequent refreshes are user-driven via the
    # ``Fetch energy data`` button or ``byd_vehicle.fetch_energy`` service
    # — energy data changes slowly and the cloud rate-limits the endpoint.
    _LOGGER.debug("Running initial energy fetch for BYD coordinators")
    for vin, coordinator in coordinators.items():
        try:
            await coordinator.async_fetch_energy()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "Initial energy fetch failed (will populate on next press): "
                "vin=%s error=%s",
                vin,
                exc,
            )

    # One-shot charging fetch so the homePage-backed sensors are
    # populated at startup. Pulls live state AND schedule from one
    # /control/smartCharge/homePage call — MQTT updates the live state
    # afterwards, but the schedule is HTTP-only so without this the
    # schedule sensors stay unavailable until the user presses the
    # ``Fetch charging`` button.
    _LOGGER.debug("Running initial charging fetch for BYD coordinators")
    for vin, coordinator in coordinators.items():
        try:
            await coordinator.async_fetch_charging()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "Initial charging fetch failed "
                "(will populate on next press): vin=%s error=%s",
                vin,
                exc,
            )

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinators": coordinators,
        "gps_coordinators": gps_coordinators,
        "options_snapshot": dict(entry.options),
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # --- Register domain services (once, on first entry) ---
    _async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_handle_entry_update))
    _LOGGER.debug("BYD config entry %s setup complete", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading BYD config entry %s", entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if entry_data and "api" in entry_data:
            await entry_data["api"].async_shutdown()
        _LOGGER.debug("Unloaded BYD config entry %s", entry.entry_id)
        # Unregister services when no entries remain.
        if not hass.data.get(DOMAIN):
            _async_unregister_services(hass)
    else:
        _LOGGER.debug("BYD config entry %s unload returned False", entry.entry_id)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    _LOGGER.debug("Reloading BYD config entry %s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


# ------------------------------------------------------------------
# Service helpers
# ------------------------------------------------------------------

_SERVICE_FETCH_REALTIME = "fetch_realtime"
_SERVICE_FETCH_GPS = "fetch_gps"
_SERVICE_FETCH_HVAC = "fetch_hvac"
_SERVICE_FETCH_CHARGING = "fetch_charging"
_SERVICE_FETCH_ENERGY = "fetch_energy"
_SERVICE_START_CHARGING = "start_charging"
_SERVICE_SAVE_CHARGING_SCHEDULE = "save_charging_schedule"

# Repeat-mode → BYD ``chargeWay`` wire format.
_REPEAT_TO_CHARGE_WAY: dict[str, str] = {
    "single": "s",
    "every_day": "e",
    "weekdays": "0,1,2,3,4",
    "weekends": "5,6",
}
# Day-of-week token → BYD index (``0`` = Monday).
_WEEKDAY_INDEX: dict[str, int] = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}

_ALL_SERVICES = (
    _SERVICE_FETCH_REALTIME,
    _SERVICE_FETCH_GPS,
    _SERVICE_FETCH_HVAC,
    _SERVICE_FETCH_CHARGING,
    _SERVICE_FETCH_ENERGY,
    _SERVICE_START_CHARGING,
    _SERVICE_SAVE_CHARGING_SCHEDULE,
)


def _normalise_hhmm(value: Any, *, field: str) -> str:
    """Coerce a service-call time input to a ``"HH:MM"`` string.

    HA's ``time`` selector hands us ``datetime.time`` instances, but
    YAML / template-rendered calls may also pass plain strings.  We
    accept both and reject anything else with a clear error.
    """
    from datetime import time as _time

    if isinstance(value, _time):
        return value.strftime("%H:%M")
    if isinstance(value, str):
        text = value.strip()
        # Accept ``"HH:MM"`` and ``"HH:MM:SS"``; ignore seconds either way.
        parts = text.split(":")
        if 2 <= len(parts) <= 3:
            try:
                hour = int(parts[0])
                minute = int(parts[1])
            except ValueError as exc:
                raise HomeAssistantError(
                    f"{field} must be an HH:MM time, got {value!r}"
                ) from exc
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"
    raise HomeAssistantError(f"{field} must be an HH:MM time, got {value!r}")


def _resolve_charge_way(call: ServiceCall) -> str:
    """Map service-call ``repeat`` (+ optional ``weekdays``) to ``chargeWay``."""
    repeat = (call.data.get("repeat") or "every_day").strip()
    if repeat == "custom":
        weekdays = call.data.get("weekdays") or []
        if isinstance(weekdays, str):
            weekdays = [weekdays]
        if not weekdays:
            raise HomeAssistantError("weekdays must be set when repeat='custom'")
        try:
            indices = sorted({_WEEKDAY_INDEX[d] for d in weekdays})
        except KeyError as exc:
            raise HomeAssistantError(
                f"unknown weekday token: {exc.args[0]!r} "
                f"(expected one of {sorted(_WEEKDAY_INDEX)})"
            ) from exc
        return ",".join(str(i) for i in indices)
    try:
        return _REPEAT_TO_CHARGE_WAY[repeat]
    except KeyError as exc:
        raise HomeAssistantError(
            f"unknown repeat mode: {repeat!r} "
            f"(expected one of {sorted(_REPEAT_TO_CHARGE_WAY)} or 'custom')"
        ) from exc


def _resolve_vins_from_call(
    hass: HomeAssistant,
    call: ServiceCall,
) -> list[tuple[str, str]]:
    """Resolve (entry_id, vin) pairs from device targets in a service call.

    Raises ``HomeAssistantError`` when no valid targets can be resolved.
    """
    device_ids: list[str] = call.data.get("device_id", [])
    if isinstance(device_ids, str):
        device_ids = [device_ids]

    dev_reg = dr.async_get(hass)
    results: list[tuple[str, str]] = []

    for device_id in device_ids:
        device = dev_reg.async_get(device_id)
        if device is None:
            continue
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN:
                vin = identifier[1]
                # Find which config entry owns this VIN.
                for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
                    coordinators = entry_data.get("coordinators", {})
                    if vin in coordinators:
                        results.append((entry_id, vin))
                        break

    if not results:
        raise HomeAssistantError("No BYD vehicle devices found for the given targets")
    return results


def _get_coordinators(
    hass: HomeAssistant,
    entry_id: str,
    vin: str,
) -> tuple[BydDataUpdateCoordinator, BydGpsUpdateCoordinator | None]:
    """Return (telemetry, gps) coordinators for an entry/vin pair."""
    entry_data: dict[str, Any] = hass.data[DOMAIN][entry_id]
    telemetry: BydDataUpdateCoordinator = entry_data["coordinators"][vin]
    gps: BydGpsUpdateCoordinator | None = entry_data.get("gps_coordinators", {}).get(
        vin
    )
    return telemetry, gps


def _async_register_services(hass: HomeAssistant) -> None:
    """Register domain services (idempotent — safe to call multiple times)."""

    if hass.services.has_service(DOMAIN, _SERVICE_FETCH_REALTIME):
        return  # Already registered.

    async def _handle_fetch_realtime(call: ServiceCall) -> None:
        for entry_id, vin in _resolve_vins_from_call(hass, call):
            coordinator, _ = _get_coordinators(hass, entry_id, vin)
            await coordinator.async_fetch_realtime()

    async def _handle_fetch_gps(call: ServiceCall) -> None:
        for entry_id, vin in _resolve_vins_from_call(hass, call):
            _, gps = _get_coordinators(hass, entry_id, vin)
            if gps is not None:
                await gps.async_fetch_gps()

    async def _handle_fetch_hvac(call: ServiceCall) -> None:
        for entry_id, vin in _resolve_vins_from_call(hass, call):
            coordinator, _ = _get_coordinators(hass, entry_id, vin)
            await coordinator.async_fetch_hvac()

    async def _handle_fetch_charging(call: ServiceCall) -> None:
        for entry_id, vin in _resolve_vins_from_call(hass, call):
            coordinator, _ = _get_coordinators(hass, entry_id, vin)
            await coordinator.async_fetch_charging()

    async def _handle_fetch_energy(call: ServiceCall) -> None:
        for entry_id, vin in _resolve_vins_from_call(hass, call):
            coordinator, _ = _get_coordinators(hass, entry_id, vin)
            await coordinator.async_fetch_energy()

    async def _handle_start_charging(call: ServiceCall) -> None:
        for entry_id, vin in _resolve_vins_from_call(hass, call):
            coordinator, _ = _get_coordinators(hass, entry_id, vin)
            await coordinator.async_start_charging()

    async def _handle_save_charging_schedule(call: ServiceCall) -> None:
        # Resolve targets first so the input-shape errors below fire on
        # the first device only — they're identical for every target.
        targets = _resolve_vins_from_call(hass, call)

        until_full = bool(call.data.get("until_full", True))
        start_charge_time = _normalise_hhmm(
            call.data.get("start_time"), field="start_time"
        )
        if until_full:
            end_charge_time = "full"
        else:
            raw_end = call.data.get("end_time")
            if raw_end is None:
                raise HomeAssistantError(
                    "end_time is required when until_full is false"
                )
            end_charge_time = _normalise_hhmm(raw_end, field="end_time")
        charge_way = _resolve_charge_way(call)
        enabled = bool(call.data.get("enabled", True))

        for entry_id, vin in targets:
            coordinator, _ = _get_coordinators(hass, entry_id, vin)
            await coordinator.async_save_charging_schedule(
                start_charge_time=start_charge_time,
                end_charge_time=end_charge_time,
                charge_way=charge_way,
                enabled=enabled,
            )

    hass.services.async_register(
        DOMAIN, _SERVICE_FETCH_REALTIME, _handle_fetch_realtime
    )
    hass.services.async_register(DOMAIN, _SERVICE_FETCH_GPS, _handle_fetch_gps)
    hass.services.async_register(DOMAIN, _SERVICE_FETCH_HVAC, _handle_fetch_hvac)
    hass.services.async_register(
        DOMAIN, _SERVICE_FETCH_CHARGING, _handle_fetch_charging
    )
    hass.services.async_register(DOMAIN, _SERVICE_FETCH_ENERGY, _handle_fetch_energy)
    hass.services.async_register(
        DOMAIN, _SERVICE_START_CHARGING, _handle_start_charging
    )
    hass.services.async_register(
        DOMAIN,
        _SERVICE_SAVE_CHARGING_SCHEDULE,
        _handle_save_charging_schedule,
    )

    _LOGGER.debug("Registered %s domain services", len(_ALL_SERVICES))


def _async_unregister_services(hass: HomeAssistant) -> None:
    """Remove domain services when the last config entry is unloaded."""
    for service in _ALL_SERVICES:
        hass.services.async_remove(DOMAIN, service)
    _LOGGER.debug("Unregistered %s domain services", len(_ALL_SERVICES))
