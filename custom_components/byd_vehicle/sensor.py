"""Sensors for BYD Vehicle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pybyd.models.realtime import TirePressureUnit
from pybyd.models.vehicle import Vehicle

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


@dataclass(frozen=True, kw_only=True)
class BydSensorDescription(SensorEntityDescription):
    """Describe a BYD sensor."""

    source: str = "realtime"
    attr_key: str | None = None
    value_fn: Callable[[Any], Any] | None = None
    validator_fn: FieldValidator | None = None


def _round_int_attr(attr: str) -> Callable[[Any], int | None]:
    """Create a converter that rounds a numeric attribute to an integer."""

    def _convert(obj: Any) -> int | None:
        value = getattr(obj, attr, None)
        if value is None:
            return None
        return int(round(float(value)))

    return _convert


def _parse_numeric_string(attr: str) -> Callable[[Any], float | None]:
    """Create a converter that parses a string attribute to float.

    Returns *None* for sentinel strings like ``"--"`` or non-numeric values.
    The BYD API sends several energy-related fields as strings (e.g. ``"29.6"``).
    """

    def _convert(obj: Any) -> float | None:
        value = getattr(obj, attr, None)
        if value is None or value == "--":
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
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


SENSOR_DESCRIPTIONS: tuple[BydSensorDescription, ...] = (
    # =============================================
    # Realtime: primary sensors (enabled by default)
    # =============================================
    BydSensorDescription(
        key="elec_percent",
        source="realtime",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision = 0,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        validator_fn=keep_previous_when_zero,
    ),
    BydSensorDescription(
        key="endurance_mileage",
        source="realtime",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision = 0,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
        value_fn=_round_int_attr("endurance_mileage"),
    ),
    BydSensorDescription(
        key="total_mileage",
        source="realtime",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision = 0,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=_round_int_attr("total_mileage"),
    ),
    BydSensorDescription(
        key="speed",
        source="realtime",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        suggested_display_precision = 0,
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    BydSensorDescription(
        key="temp_in_car",
        source="realtime",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision = 0,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda obj: (
            int(round(obj.temp_in_car)) if obj.temp_in_car is not None else 0
        ),
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
        suggested_display_precision = 0,
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
        suggested_display_precision = 0,
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
        suggested_display_precision = 0,
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
        suggested_display_precision = 0,
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
        suggested_display_precision = 0,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_round_int_attr("total_mileage_v2"),
    ),
    # Charging detail from realtime
    BydSensorDescription(
        key="charging_state",
        source="realtime",
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
    BydSensorDescription(
        key="booking_charge_state",
        source="realtime",
        icon="mdi:calendar-clock",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="booking_charging_hour",
        source="realtime",
        icon="mdi:calendar-clock",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BydSensorDescription(
        key="booking_charging_minute",
        source="realtime",
        icon="mdi:calendar-clock",
        entity_registry_enabled_default=False,
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
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
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
            return _normalize_epoch(getattr(gps, "gps_timestamp", None))

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
        return (
            super().available
            and self._get_source_obj(self.entity_description.source) is not None
        )

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit; tire pressures resolve dynamically."""
        desc_unit = self.entity_description.native_unit_of_measurement
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
