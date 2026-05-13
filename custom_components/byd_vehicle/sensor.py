"""Sensors for BYD Vehicle."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfPower,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pybyd.models.realtime import TirePressureUnit
from pybyd.models.vehicle import EnergyType, Vehicle

from .const import DOMAIN
from .coordinator import BydDataUpdateCoordinator
from .entity import BydVehicleEntity

# ---------------------------------------------------------------------------
# Simple presentation-level validators (pyBYD state engine handles deeper
# quality guards; these cover HA display edge-cases only).
# ---------------------------------------------------------------------------

FieldValidator = Callable[[Any, Any], Any]


def keep_previous_when_zero(previous: Any, current: Any) -> Any:
    """Return *previous* when *current* is zero or None.

    Prevents transient ``0 %`` SOC values from showing in the HA UI
    when the vehicle sends stale/invalid telemetry.
    """
    if current is None or current == 0:
        return previous
    return current


def _normalize_epoch(value: Any) -> datetime | None:
    """Ensure a pre-parsed BydTimestamp is UTC-aware, or return None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    return None


def _snap_whole_hour_offset(
    value: datetime,
    reference: datetime | None,
) -> datetime | None:
    """Remove a clean whole-hour offset of *value* relative to *reference*.

    Returns the corrected value when the gap between *value* and
    *reference* is within 5 minutes of a non-zero whole number of hours;
    otherwise returns ``None`` to signal "no correction applied" (either
    because there is no reference, the gap is already sub-hour, or it is
    not close enough to a whole hour to be a timezone-style shift).
    """
    if reference is None:
        return None

    delta = value - reference
    whole_hours = round(delta.total_seconds() / 3600)
    if whole_hours == 0:
        return None

    whole_hour_delta = timedelta(hours=whole_hours)
    if abs(delta - whole_hour_delta) > timedelta(minutes=5):
        return None

    return value - whole_hour_delta


def _normalize_gps_timestamp(
    gps_timestamp: datetime | None,
    realtime_timestamp: datetime | None,
    now: datetime | None = None,
) -> datetime | None:
    """Correct clean whole-hour GPS offsets.

    Some vehicles report GPS timestamps with a timezone-style encoding
    bug that shifts the value by an exact number of whole hours.  Two
    references are tried, in order:

    1. The realtime payload timestamp — catches a shift that affects
       only the GPS section (the case the original fix handled).
    2. The wall clock (*now*) — catches a *feed-wide* shift where the
       realtime timestamp carries the **same** offset, so the
       GPS-vs-realtime delta is ~0 and step 1 finds nothing.  This step
       only fires when the GPS timestamp lies in the *future*: a
       satellite fix can never be dated after the moment we received it,
       so a whole-hour future offset is unambiguously the encoding bug,
       whereas a past timestamp may simply be a stale/preserved fix and
       is left untouched to avoid over-correcting.
    """
    if gps_timestamp is None:
        return gps_timestamp

    corrected = _snap_whole_hour_offset(gps_timestamp, realtime_timestamp)
    if corrected is not None:
        return corrected

    if now is None:
        now = datetime.now(tz=UTC)
    if gps_timestamp > now:
        corrected = _snap_whole_hour_offset(gps_timestamp, now)
        if corrected is not None:
            return corrected

    return gps_timestamp


@dataclass(frozen=True, kw_only=True)
class BydSensorDescription(SensorEntityDescription):
    """Describe a BYD sensor."""

    source: str = "realtime"
    attr_key: str | None = None
    value_fn: Callable[[Any], Any] | None = None
    unit_fn: Callable[[Any], str | None] | None = None
    state_attrs_fn: Callable[[Any], dict[str, Any]] | None = None
    validator_fn: FieldValidator | None = None
    available_fn: Callable[[Any], bool] | None = None
    """Optional predicate against the source object to mark the entity
    unavailable.  Returning ``False`` produces an HA "unavailable" state
    even when the source object exists (e.g. for the schedule-end-time
    sensor when the schedule is set to charge until full)."""


def _round_int_attr(attr: str) -> Callable[[Any], int | None]:
    """Create a converter that rounds a numeric attribute to an integer."""

    def _convert(obj: Any) -> int | None:
        value = getattr(obj, attr, None)
        if value is None:
            return None
        return int(round(float(value)))

    return _convert


_LEADING_NUMBER_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)")


def _parse_numeric_string(attr: str) -> Callable[[Any], float | None]:
    """Create a converter that parses a string attribute to float.

    Returns *None* for sentinel strings like ``"--"`` or non-numeric values.
    The BYD API sends several energy-related fields as strings. Some are
    bare numbers (e.g. ``"29.6"``) while others include unit suffixes
    (e.g. ``"18.4kW·h/100km"``, ``"11.9度/百公里"``). The fallback regex
    extracts the leading numeric portion so both styles parse cleanly.
    """

    def _convert(obj: Any) -> float | None:
        value = getattr(obj, attr, None)
        if value is None or value == "--":
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            if isinstance(value, str):
                match = _LEADING_NUMBER_RE.match(value)
                if match:
                    try:
                        return float(match.group(1))
                    except ValueError:
                        pass
            return None

    return _convert


def _positive_float_attr(attr: str) -> Callable[[Any], float | None]:
    """Create a converter returning *None* for negative sentinel values.

    The BYD API uses ``-1`` as a "not available" marker for several
    numeric fields (e.g. ``oilEndurance``).
    """

    def _convert(obj: Any) -> float | None:
        value = getattr(obj, attr, None)
        if value is None or value < 0:
            return None
        return float(value)

    return _convert


def _attr_getter(name: str) -> Callable[[Any], Any]:
    """Return a callable that reads attribute *name* from a source object."""

    def _get(obj: Any) -> Any:
        if obj is None:
            return None
        return getattr(obj, name, None)

    return _get


_WEEKDAY_LABELS: tuple[str, ...] = (
    "Mon",
    "Tue",
    "Wed",
    "Thu",
    "Fri",
    "Sat",
    "Sun",
)


def _format_charge_way(value: str | None) -> str | None:
    """Render the BYD ``chargeWay`` token as a human-readable repeat label.

    * ``"s"`` → ``"Single"``
    * ``"e"`` → ``"Every day"``
    * ``"0,1,2,3,4"`` → ``"Weekdays"``
    * ``"5,6"`` → ``"Weekends"``
    * other comma-separated weekday indices → ``"Custom (Mon, Wed, Fri)"``

    Falls back to the raw string for unparseable values so the sensor
    surfaces the truth rather than swallowing unknown formats silently.
    """
    if value is None or not value:
        return None
    if value == "s":
        return "Single"
    if value == "e":
        return "Every day"
    if value == "0,1,2,3,4":
        return "Weekdays"
    if value == "5,6":
        return "Weekends"
    try:
        indices = sorted({int(p.strip()) for p in value.split(",") if p.strip()})
    except ValueError:
        return value
    names = [_WEEKDAY_LABELS[i] for i in indices if 0 <= i < len(_WEEKDAY_LABELS)]
    if not names:
        return value
    return f"Custom ({', '.join(names)})"


def _eq_consumption_value(snap: Any) -> Any:
    """Return the 'Last 50km equivalent consumption' value.

    Prefers ``realtime.eq_consumption`` (the raw MQTT
    ``nearestEnergyConsumption`` summary, populated every poll cycle).
    Falls back to the HTTP equivalent based on the vehicle's
    energyType — ``avg_ev_consumption`` at et=0, otherwise
    ``avg_eq_oil_consumption``.
    """
    if snap is None:
        return None
    rt = getattr(snap, "realtime", None)
    if rt is not None:
        v = getattr(rt, "eq_consumption", None)
        if v is not None:
            return v
    energy = getattr(snap, "energy", None)
    if energy is None:
        return None
    nearest = getattr(energy, "nearest_energy_consumption", None)
    if nearest is None:
        return None
    energy_type = getattr(getattr(snap, "vehicle", None), "energy_type", EnergyType.EV)
    if energy_type in (EnergyType.ICE, EnergyType.HYBRID):
        return getattr(nearest, "avg_eq_oil_consumption", None)
    return getattr(nearest, "avg_ev_consumption", None)


def _eq_consumption_unit(snap: Any) -> Any:
    """Return the matching unit for ``_eq_consumption_value``."""
    if snap is None:
        return None
    rt = getattr(snap, "realtime", None)
    if rt is not None:
        u = getattr(rt, "eq_consumption_unit", None)
        if u:
            return u
    energy = getattr(snap, "energy", None)
    if energy is None:
        return None
    nearest = getattr(energy, "nearest_energy_consumption", None)
    if nearest is None:
        return None
    energy_type = getattr(getattr(snap, "vehicle", None), "energy_type", EnergyType.EV)
    if energy_type in (EnergyType.ICE, EnergyType.HYBRID):
        return getattr(nearest, "oil_unit", None) or None
    return getattr(nearest, "ev_unit", None) or None


def _prefer_rt_then_energy(
    rt_attr: str | None,
    *energy_path: str,
) -> Callable[[Any], Any]:
    """Return ``snap.realtime.<rt_attr>`` if set, else navigate ``snap.energy``.

    The realtime section is updated automatically every poll cycle while the
    energy section is on-demand (via ``Fetch energy data``). Reading from
    realtime first means merged sensors stay fresh between energy fetches;
    falling back to the energy section keeps them populated when realtime
    hasn't carried the value (or returned a sentinel).
    """

    def _convert(snap: Any) -> Any:
        if snap is None:
            return None
        if rt_attr is not None:
            rt = getattr(snap, "realtime", None)
            if rt is not None:
                value = getattr(rt, rt_attr, None)
                if value is not None:
                    return value
        cur: Any = getattr(snap, "energy", None)
        for part in energy_path:
            if cur is None:
                return None
            cur = getattr(cur, part, None)
        return cur

    return _convert


SENSOR_DESCRIPTIONS: tuple[BydSensorDescription, ...] = (
    # =============================================
    # Realtime: primary sensors (enabled by default)
    # =============================================
    BydSensorDescription(
        key="elec_percent",
        source="realtime",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        validator_fn=keep_previous_when_zero,
    ),
    BydSensorDescription(
        key="endurance_mileage",
        source="realtime",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
        value_fn=_round_int_attr("endurance_mileage"),
    ),
    BydSensorDescription(
        key="total_mileage",
        source="realtime",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=_round_int_attr("total_mileage"),
    ),
    BydSensorDescription(
        key="speed",
        source="realtime",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    BydSensorDescription(
        key="temp_in_car",
        source="realtime",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_round_int_attr("temp_in_car"),
    ),
    # Tire pressures – unit resolved dynamically from tire_press_unit;
    # kPa is the default because most BYD vehicles report tirePressUnit=3.
    BydSensorDescription(
        key="left_front_tire_pressure",
        source="realtime",
        native_unit_of_measurement=UnitOfPressure.KPA,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:car-tire-alert",
    ),
    BydSensorDescription(
        key="right_front_tire_pressure",
        source="realtime",
        native_unit_of_measurement=UnitOfPressure.KPA,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:car-tire-alert",
    ),
    BydSensorDescription(
        key="left_rear_tire_pressure",
        source="realtime",
        native_unit_of_measurement=UnitOfPressure.KPA,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:car-tire-alert",
    ),
    BydSensorDescription(
        key="right_rear_tire_pressure",
        source="realtime",
        native_unit_of_measurement=UnitOfPressure.KPA,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:car-tire-alert",
    ),
    BydSensorDescription(
        key="battery_power",
        attr_key="gl",
        source="realtime",
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # =============================================
    # HVAC: primary sensors (enabled by default)
    # =============================================
    BydSensorDescription(
        key="temp_out_car",
        source="hvac",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_round_int_attr("temp_out_car"),
    ),
    BydSensorDescription(
        key="pm",
        source="hvac",
        native_unit_of_measurement="µg/m³",
        device_class=SensorDeviceClass.PM25,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # ===========================================================
    # Realtime: disabled by default (diagnostic / secondary data)
    # ===========================================================
    # Alt battery / range fields
    BydSensorDescription(
        key="power_battery",
        source="realtime",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        validator_fn=keep_previous_when_zero,
    ),
    BydSensorDescription(
        key="ev_endurance",
        source="realtime",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_round_int_attr("ev_endurance"),
    ),
    BydSensorDescription(
        key="endurance_mileage_v2",
        source="realtime",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_round_int_attr("endurance_mileage_v2"),
    ),
    BydSensorDescription(
        key="total_mileage_v2",
        source="realtime",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_round_int_attr("total_mileage_v2"),
    ),
    # Charging detail from realtime
    # Source the charging-state value from the smart-charging endpoint:
    # the realtime payload reports ``chargingState=-1`` permanently on
    # Sealion 7 (and other EU 2024 cars) while the charging endpoint
    # returns the real numeric state (15=connected, 1=charging, …).
    # See issue #115.
    BydSensorDescription(
        key="charging_state",
        source="charging",
        icon="mdi:ev-station",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="charge_state",
        source="realtime",
        icon="mdi:ev-station",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="wait_status",
        source="realtime",
        icon="mdi:timer-sand",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="full_hour",
        source="realtime",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-outline",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="full_minute",
        source="realtime",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-outline",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="remaining_hours",
        source="realtime",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-outline",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="remaining_minutes",
        source="realtime",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-outline",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # Combined ``remaining_hours``/``remaining_minutes`` realtime fields,
    # rendered as a single ``HH:MM`` string.  Only populates while
    # actively charging — both source fields are ``-1`` (sentinel)
    # otherwise, so the sensor stays unavailable instead of showing
    # ``00:00``.  ``full_hour``/``full_minute`` always read ``-1`` even
    # mid-charge per the active-charging capture, so they're unused.
    BydSensorDescription(
        key="charge_remaining_time",
        source="realtime",
        available_fn=lambda obj: (
            obj is not None
            and getattr(obj, "remaining_hours", None) is not None
            and getattr(obj, "remaining_minutes", None) is not None
        ),
        value_fn=lambda obj: (
            f"{obj.remaining_hours:02d}:{obj.remaining_minutes:02d}"
            if obj is not None
            and obj.remaining_hours is not None
            and obj.remaining_minutes is not None
            else None
        ),
        icon="mdi:battery-clock",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="total_power",
        source="realtime",
        icon="mdi:flash",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="nearest_energy_consumption",
        source="realtime",
        icon="mdi:lightning-bolt",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_parse_numeric_string("nearest_energy_consumption"),
    ),
    BydSensorDescription(
        key="recent_50km_energy",
        source="realtime",
        icon="mdi:lightning-bolt",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_parse_numeric_string("recent_50km_energy"),
    ),
    # Fuel (hybrid vehicles)
    BydSensorDescription(
        key="oil_endurance",
        source="realtime",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gas-station",
        entity_registry_enabled_default=True,
        value_fn=_round_int_attr("oil_endurance"),
    ),
    BydSensorDescription(
        key="oil_percent",
        source="realtime",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gas-station",
        entity_registry_enabled_default=True,
    ),
    BydSensorDescription(
        key="total_oil",
        source="realtime",
        icon="mdi:gas-station",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # System indicators
    BydSensorDescription(
        key="engine_status",
        source="realtime",
        icon="mdi:engine",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="epb",
        source="realtime",
        # The ``epb`` field returns ``-1`` while the car is asleep or
        # otherwise unable to report EPB state; without this guard the
        # diagnostic sensor surfaces a literal ``-1`` as its state.
        value_fn=lambda obj: (
            None
            if obj is None or not isinstance(getattr(obj, "raw", None), dict)
            else (None if obj.raw.get("epb", -1) < 0 else obj.raw.get("epb"))
        ),
        icon="mdi:car-brake-parking",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="ect_value",
        source="realtime",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:coolant-temperature",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # =========================================
    # HVAC: standalone sensors (not climate)
    # =========================================
    BydSensorDescription(
        key="refrigerator_state",
        source="hvac",
        icon="mdi:fridge",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="refrigerator_door_state",
        source="hvac",
        icon="mdi:fridge",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ==========================================
    # Realtime: additional diagnostic sensors
    #   (disabled by default — raw / unparsed)
    # ==========================================
    BydSensorDescription(
        key="total_energy",
        source="realtime",
        icon="mdi:flash",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_parse_numeric_string("total_energy"),
    ),
    BydSensorDescription(
        key="nearest_energy_consumption_unit",
        source="realtime",
        icon="mdi:lightning-bolt",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="endurance_mileage_v2_unit",
        source="realtime",
        icon="mdi:map-marker-distance",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="total_mileage_v2_unit",
        source="realtime",
        icon="mdi:counter",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # Charge rate
    BydSensorDescription(
        key="rate",
        source="realtime",
        icon="mdi:ev-station",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # Energy consumption strings
    BydSensorDescription(
        key="energy_consumption",
        source="realtime",
        icon="mdi:lightning-bolt",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_parse_numeric_string("energy_consumption"),
    ),
    BydSensorDescription(
        key="total_consumption",
        source="realtime",
        icon="mdi:lightning-bolt",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_parse_numeric_string("total_consumption"),
    ),
    BydSensorDescription(
        key="total_consumption_en",
        source="realtime",
        icon="mdi:lightning-bolt",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_parse_numeric_string("total_consumption_en"),
    ),
    # Warning indicators (as numeric sensors)
    BydSensorDescription(
        key="ok_light",
        source="realtime",
        icon="mdi:check-circle",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="power_battery_connection",
        source="realtime",
        # Mirrors the ``epb`` guard above: this field reports ``-1``
        # while telemetry is stale and surfaces as a literal ``-1``
        # state on the diagnostic sensor without filtering.
        value_fn=lambda obj: (
            None
            if obj is None or not isinstance(getattr(obj, "raw", None), dict)
            else (
                None
                if obj.raw.get("powerBatteryConnection", -1) < 0
                else obj.raw.get("powerBatteryConnection")
            )
        ),
        icon="mdi:battery-alert",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="ins",
        source="realtime",
        icon="mdi:shield-car",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # Misc
    BydSensorDescription(
        key="repair_mode_switch",
        source="realtime",
        icon="mdi:wrench",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="vehicle_time_zone",
        source="realtime",
        icon="mdi:clock-outline",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ==========================================
    # Last updated timestamp
    # ==========================================
    BydSensorDescription(
        key="last_updated",
        source="realtime",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="gps_last_updated",
        source="gps",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:crosshairs-gps",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ==========================================
    # Merged hybrid leg averages (realtime + energy endpoints carry
    # the same value at different update cadences). Each merged sensor
    # prefers the realtime field — updated every poll — and falls back
    # to the energy-endpoint field — refreshed on Fetch energy data.
    # ==========================================
    BydSensorDescription(
        key="last_50km_avg_ev_consumption",
        source="snapshot",
        value_fn=_prefer_rt_then_energy(
            "energy_consumption_ev",
            "nearest_energy_consumption",
            "avg_ev_consumption",
        ),
        unit_fn=_prefer_rt_then_energy(
            "energy_consumption_ev_unit",
            "nearest_energy_consumption",
            "ev_unit",
        ),
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="last_50km_avg_fuel_consumption",
        source="snapshot",
        value_fn=_prefer_rt_then_energy(
            "energy_consumption_fuel",
            "nearest_energy_consumption",
            "avg_oil_consumption",
        ),
        unit_fn=_prefer_rt_then_energy(
            "energy_consumption_fuel_unit",
            "nearest_energy_consumption",
            "oil_unit",
        ),
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gas-station",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="lifetime_avg_ev_consumption",
        source="snapshot",
        value_fn=_prefer_rt_then_energy(
            "total_consumption_en_ev",
            "cumulative_energy_consumption",
            "avg_ev_consumption",
        ),
        unit_fn=_prefer_rt_then_energy(
            "total_consumption_en_ev_unit",
            "cumulative_energy_consumption",
            "ev_unit",
        ),
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="lifetime_avg_fuel_consumption",
        source="snapshot",
        value_fn=_prefer_rt_then_energy(
            "total_consumption_en_fuel",
            "cumulative_energy_consumption",
            "avg_oil_consumption",
        ),
        unit_fn=_prefer_rt_then_energy(
            "total_consumption_en_fuel_unit",
            "cumulative_energy_consumption",
            "oil_unit",
        ),
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gas-station",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ==========================================
    # EnergyConsumption (getEnergyConsumption only)
    # ==========================================
    BydSensorDescription(
        key="energy_cumulative_total_mileage",
        source="energy_cumulative",
        attr_key="total_mileage",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="energy_last_50km_ev_consumption",
        source="energy_nearest",
        attr_key="ev_consumption",
        unit_fn=_attr_getter("ev_value_unit"),
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="energy_last_50km_oil_consumption",
        source="energy_nearest",
        attr_key="oil_consumption",
        unit_fn=_attr_getter("oil_value_unit"),
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gas-station",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="last_50km_avg_eq_consumption",
        source="snapshot",
        value_fn=_eq_consumption_value,
        unit_fn=_eq_consumption_unit,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fuel",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="energy_last_50km_drive_distribution",
        source="energy_nearest",
        attr_key="drive_distribution",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:steering",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="energy_last_50km_elect_distribution",
        source="energy_nearest",
        attr_key="elect_distribution",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="energy_last_50km_air_distribution",
        source="energy_nearest",
        attr_key="air_distribution",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:air-conditioner",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="energy_last_50km_other_distribution",
        source="energy_nearest",
        attr_key="other_distribution",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:dots-horizontal",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ==========================================
    # EnergyConsumption — 7-day graph series.
    # Exposes today's value (last element) as the sensor state and
    # the full series as ``daily_values`` extra state attribute.
    # ==========================================
    BydSensorDescription(
        key="energy_self_graph_today",
        source="energy_self_graph",
        value_fn=lambda obj: (
            obj.energy_consumption[-1]
            if obj is not None and obj.energy_consumption
            else None
        ),
        unit_fn=_attr_getter("energy_consumption_unit"),
        state_attrs_fn=lambda obj: (
            {
                "daily_values": list(obj.energy_consumption),
            }
            if obj is not None and obj.energy_consumption
            else {}
        ),
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-line",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="energy_auto_model_graph_today",
        source="energy_auto_model_graph",
        value_fn=lambda obj: (
            obj.energy_consumption[-1]
            if obj is not None and obj.energy_consumption
            else None
        ),
        unit_fn=_attr_getter("energy_consumption_unit"),
        state_attrs_fn=lambda obj: (
            {
                "daily_values": list(obj.energy_consumption),
            }
            if obj is not None and obj.energy_consumption
            else {}
        ),
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-line",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # --- Smart-charging schedule (sourced from /control/smartCharge/homePage) ---
    BydSensorDescription(
        key="scheduled_charge_start_time",
        source="charging_schedule_charge",
        value_fn=lambda obj: (
            obj.start_time.strftime("%H:%M")
            if obj is not None and obj.start_time is not None
            else None
        ),
        icon="mdi:calendar-clock",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="scheduled_charge_end_time",
        source="charging_schedule_charge",
        # ``charge_until_full`` flags the wire sentinel ``"full"`` —
        # there's no clock-time end, so surface as unavailable rather
        # than showing a misleading value.
        available_fn=lambda obj: (
            obj is not None and obj.end_time is not None and not obj.charge_until_full
        ),
        value_fn=lambda obj: (
            obj.end_time.strftime("%H:%M")
            if obj is not None and obj.end_time is not None
            else None
        ),
        icon="mdi:calendar-clock",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="scheduled_charge_repeat",
        source="charging_schedule_charge",
        value_fn=lambda obj: (
            _format_charge_way(obj.charge_way) if obj is not None else None
        ),
        icon="mdi:calendar-refresh",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BYD sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[str, BydDataUpdateCoordinator] = data["coordinators"]
    gps_coordinators = data.get("gps_coordinators", {})

    entities: list[SensorEntity] = []
    for vin, coordinator in coordinators.items():
        vehicle = coordinator.vehicle
        for description in SENSOR_DESCRIPTIONS:
            if description.key == "gps_last_updated":
                gps_coordinator = gps_coordinators.get(vin)
                if gps_coordinator is not None:
                    entities.append(
                        BydSensor(gps_coordinator, vin, vehicle, description)
                    )
                continue
            entities.append(BydSensor(coordinator, vin, vehicle, description))

    async_add_entities(entities)


_TIRE_PRESSURE_KEYS = {
    "left_front_tire_pressure",
    "right_front_tire_pressure",
    "left_rear_tire_pressure",
    "right_rear_tire_pressure",
}

_TIRE_UNIT_MAP = {
    TirePressureUnit.BAR: UnitOfPressure.BAR,
    TirePressureUnit.PSI: UnitOfPressure.PSI,
    TirePressureUnit.KPA: UnitOfPressure.KPA,
}


class BydSensor(BydVehicleEntity, SensorEntity):
    """Representation of a BYD vehicle sensor.

    All state is read from ``VehicleSnapshot`` sections via the
    base-class ``_get_source_obj()`` helper. No local shadow state.
    """

    _attr_has_entity_name = True
    entity_description: BydSensorDescription

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
        description: BydSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_{description.source}_{description.key}"
        self._last_native_value: Any | None = None

        # Auto-disable sensors that return no data on first fetch.
        if description.entity_registry_enabled_default is not False:
            if self._resolve_validated_value() is None:
                self._attr_entity_registry_enabled_default = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_value(self) -> Any:
        """Extract the current value using the description's extraction logic."""
        key = self.entity_description.key

        # Timestamp sensors use the snapshot section's timestamp attribute.
        if key == "last_updated":
            realtime = self._get_realtime()
            if realtime is None:
                return None
            return _normalize_epoch(getattr(realtime, "timestamp", None))

        if key == "gps_last_updated":
            gps = self._get_gps()
            if gps is None:
                return None
            gps_timestamp = _normalize_epoch(getattr(gps, "gps_timestamp", None))
            realtime = self._get_realtime()
            realtime_timestamp = _normalize_epoch(getattr(realtime, "timestamp", None))
            return _normalize_gps_timestamp(gps_timestamp, realtime_timestamp)

        obj = self._get_source_obj(self.entity_description.source)
        if obj is None:
            return None

        if self.entity_description.value_fn is not None:
            return self.entity_description.value_fn(obj)

        attr = self.entity_description.attr_key or key
        value = getattr(obj, attr, None)
        enum_value = getattr(value, "value", None)
        if isinstance(enum_value, int):
            return enum_value
        return value

    def _resolve_validated_value(self) -> Any:
        """Resolve sensor value and apply optional per-entity validation."""
        value = self._resolve_value()
        validator = self.entity_description.validator_fn
        if validator is not None:
            value = validator(self._last_native_value, value)
        if value is not None:
            self._last_native_value = value
        return value

    # ------------------------------------------------------------------
    # Entity properties
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Return True when the coordinator has data for this source."""
        if self.entity_description.key in ("last_updated", "gps_last_updated"):
            return super().available and self._resolve_value() is not None
        if not super().available:
            return False
        obj = self._get_source_obj(self.entity_description.source)
        if obj is None:
            return False
        if self.entity_description.available_fn is not None:
            return bool(self.entity_description.available_fn(obj))
        return True

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit; tyres + per-leg energy fields resolve dynamically."""
        desc_unit = self.entity_description.native_unit_of_measurement
        if self.entity_description.unit_fn is not None:
            obj = self._get_source_obj(self.entity_description.source)
            if obj is not None:
                dynamic_unit = self.entity_description.unit_fn(obj)
                if dynamic_unit:
                    return dynamic_unit
            return desc_unit
        if self.entity_description.key not in _TIRE_PRESSURE_KEYS:
            return desc_unit
        obj = self._get_source_obj(self.entity_description.source)
        if obj is not None:
            api_unit = getattr(obj, "tire_press_unit", None)
            if api_unit is not None:
                return _TIRE_UNIT_MAP.get(api_unit, desc_unit)
        return desc_unit

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self._resolve_validated_value()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Merge VIN with description-supplied dynamic attributes."""
        attrs = super().extra_state_attributes
        if self.entity_description.state_attrs_fn is not None:
            obj = self._get_source_obj(self.entity_description.source)
            if obj is not None:
                extra = self.entity_description.state_attrs_fn(obj)
                if extra:
                    attrs = {**attrs, **extra}
        return attrs
