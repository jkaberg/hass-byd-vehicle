"""Binary sensors for BYD Vehicle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from pybyd.models.realtime import (
    DoorOpenState,
    WindowState,
)
from pybyd.models.vehicle import Vehicle

from .const import DOMAIN
from .coordinator import BydDataUpdateCoordinator
from .entity import BydVehicleEntity


@dataclass(frozen=True, kw_only=True)
class BydBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a BYD binary sensor."""

    source: str = "realtime"
    attr_key: str | None = None
    value_fn: Callable[[Any], bool | None] | None = None


def _is_charging_from_realtime(obj: Any) -> bool | None:
    """Return whether the vehicle is actively charging from realtime state."""
    return getattr(obj, "is_charging", None)


def _attr_truthy(attr_name: str) -> Callable[[Any], bool | None]:
    """Return a value_fn that checks ``bool(getattr(obj, attr_name))``."""

    def _fn(obj: Any) -> bool | None:
        val = getattr(obj, attr_name, None)
        if val is None:
            return None
        return bool(val)

    return _fn


def _attr_equals(attr_name: str, target: Any) -> Callable[[Any], bool | None]:
    """Return a value_fn that checks ``getattr(obj, attr_name) == target``."""

    def _fn(obj: Any) -> bool | None:
        val = getattr(obj, attr_name, None)
        if val is None:
            return None
        return val == target

    return _fn


def _sentinel_int_on(attr_name: str) -> Callable[[Any], bool | None]:
    """Return a value_fn converting an integer indicator to bool.

    pyBYD normalises ``-1`` sentinels to ``None``.  This helper maps
    ``0`` → ``False`` (off) and any value ``> 0`` → ``True`` (on).
    """

    def _fn(obj: Any) -> bool | None:
        val = getattr(obj, attr_name, None)
        if val is None:
            return None
        return val > 0

    return _fn


BINARY_SENSOR_DESCRIPTIONS: tuple[BydBinarySensorDescription, ...] = (
    # =================================
    # Aggregate states (enabled)
    # =================================
    BydBinarySensorDescription(
        key="is_online",
        source="realtime",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda r: r.is_online,
    ),
    BydBinarySensorDescription(
        key="is_charging",
        source="realtime",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=_is_charging_from_realtime,
    ),
    # Plug/charger connection.  Reads from the smart-charging endpoint
    # because the realtime payload reports ``connectState=-1``
    # permanently on Sealion 7 (and other EU 2024 cars) — see issue #115.
    BydBinarySensorDescription(
        key="is_charger_connected",
        source="charging",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=lambda c: c.is_connected if c is not None else None,
    ),
    BydBinarySensorDescription(
        key="is_any_door_open",
        source="realtime",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda r: r.is_any_door_open,
    ),
    BydBinarySensorDescription(
        key="is_any_window_open",
        source="realtime",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=lambda r: r.is_any_window_open,
    ),
    BydBinarySensorDescription(
        key="is_locked",
        source="realtime",
        device_class=BinarySensorDeviceClass.LOCK,
        # is_locked returns True when locked; for BinarySensorDeviceClass.LOCK,
        # is_on=True means "problem" (unlocked), so invert. None propagates as-is.
        value_fn=lambda r: None if (v := r.is_locked) is None else not v,
    ),
    BydBinarySensorDescription(
        key="sentry_status",
        source="realtime",
        icon="mdi:shield-car",
        value_fn=_attr_truthy("sentry_status"),
    ),
    # ====================================
    # Individual doors (disabled)
    # ====================================
    BydBinarySensorDescription(
        key="left_front_door",
        source="realtime",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_attr_equals("left_front_door", DoorOpenState.OPEN),
        entity_registry_enabled_default=False,
    ),
    BydBinarySensorDescription(
        key="right_front_door",
        source="realtime",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_attr_equals("right_front_door", DoorOpenState.OPEN),
        entity_registry_enabled_default=False,
    ),
    BydBinarySensorDescription(
        key="left_rear_door",
        source="realtime",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_attr_equals("left_rear_door", DoorOpenState.OPEN),
        entity_registry_enabled_default=False,
    ),
    BydBinarySensorDescription(
        key="right_rear_door",
        source="realtime",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_attr_equals("right_rear_door", DoorOpenState.OPEN),
        entity_registry_enabled_default=False,
    ),
    BydBinarySensorDescription(
        key="trunk_lid",
        source="realtime",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_attr_equals("trunk_lid", DoorOpenState.OPEN),
        entity_registry_enabled_default=False,
    ),
    BydBinarySensorDescription(
        key="sliding_door",
        source="realtime",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_attr_equals("sliding_door", DoorOpenState.OPEN),
        entity_registry_enabled_default=False,
    ),
    BydBinarySensorDescription(
        key="forehold",
        source="realtime",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_attr_equals("forehold", DoorOpenState.OPEN),
        entity_registry_enabled_default=False,
    ),
    # ====================================
    # Individual windows (disabled)
    # ====================================
    BydBinarySensorDescription(
        key="left_front_window",
        source="realtime",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=_attr_equals("left_front_window", WindowState.OPEN),
        entity_registry_enabled_default=False,
    ),
    BydBinarySensorDescription(
        key="right_front_window",
        source="realtime",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=_attr_equals("right_front_window", WindowState.OPEN),
        entity_registry_enabled_default=False,
    ),
    BydBinarySensorDescription(
        key="left_rear_window",
        source="realtime",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=_attr_equals("left_rear_window", WindowState.OPEN),
        entity_registry_enabled_default=False,
    ),
    BydBinarySensorDescription(
        key="right_rear_window",
        source="realtime",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=_attr_equals("right_rear_window", WindowState.OPEN),
        entity_registry_enabled_default=False,
    ),
    BydBinarySensorDescription(
        key="skylight",
        source="realtime",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=_attr_equals("skylight", WindowState.OPEN),
        entity_registry_enabled_default=False,
    ),
    # ====================================
    # Other (disabled)
    # ====================================
    BydBinarySensorDescription(
        key="battery_heat_state",
        source="realtime",
        icon="mdi:heat-wave",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_attr_truthy("battery_heat_state"),
    ),
    # ====================================
    # Warning / status indicators (disabled)
    # ====================================
    BydBinarySensorDescription(
        key="abs_warning",
        source="realtime",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:car-brake-abs",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("abs_warning"),
    ),
    BydBinarySensorDescription(
        key="svs",
        source="realtime",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:car-wrench",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("svs"),
    ),
    BydBinarySensorDescription(
        key="srs",
        source="realtime",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:airbag",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("srs"),
    ),
    BydBinarySensorDescription(
        key="eps",
        source="realtime",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:steering",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("eps"),
    ),
    BydBinarySensorDescription(
        key="esp",
        source="realtime",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:car-traction-control",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("esp"),
    ),
    BydBinarySensorDescription(
        key="pwr",
        source="realtime",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:flash-alert",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("pwr"),
    ),
    BydBinarySensorDescription(
        key="power_system",
        source="realtime",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:flash",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("power_system"),
    ),
    BydBinarySensorDescription(
        key="ect",
        source="realtime",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:coolant-temperature",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("ect"),
    ),
    BydBinarySensorDescription(
        key="tirepressure_system",
        source="realtime",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:car-tire-alert",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("tirepressure_system"),
    ),
    BydBinarySensorDescription(
        key="rapid_tire_leak",
        source="realtime",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:car-tire-alert",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("rapid_tire_leak"),
    ),
    BydBinarySensorDescription(
        key="left_front_tire_status",
        source="realtime",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:car-tire-alert",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("left_front_tire_status"),
    ),
    BydBinarySensorDescription(
        key="right_front_tire_status",
        source="realtime",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:car-tire-alert",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("right_front_tire_status"),
    ),
    BydBinarySensorDescription(
        key="left_rear_tire_status",
        source="realtime",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:car-tire-alert",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("left_rear_tire_status"),
    ),
    BydBinarySensorDescription(
        key="right_rear_tire_status",
        source="realtime",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:car-tire-alert",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("right_rear_tire_status"),
    ),
    BydBinarySensorDescription(
        key="upgrade_status",
        source="realtime",
        icon="mdi:cellphone-arrow-down",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("upgrade_status"),
    ),
    BydBinarySensorDescription(
        key="charge_heat_state",
        source="realtime",
        icon="mdi:heat-wave",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_attr_truthy("charge_heat_state"),
    ),
    BydBinarySensorDescription(
        key="vehicle_state",
        source="realtime",
        device_class=BinarySensorDeviceClass.POWER,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda r: r.is_vehicle_on,
    ),
    # ====================================
    # Additional warnings (disabled)
    # ====================================
    BydBinarySensorDescription(
        key="oil_pressure_system",
        source="realtime",
        icon="mdi:oil",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("oil_pressure_system"),
    ),
    BydBinarySensorDescription(
        key="braking_system",
        source="realtime",
        icon="mdi:car-brake-alert",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("braking_system"),
    ),
    BydBinarySensorDescription(
        key="charging_system",
        source="realtime",
        icon="mdi:ev-station",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("charging_system"),
    ),
    BydBinarySensorDescription(
        key="steering_system",
        source="realtime",
        icon="mdi:steering",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sentinel_int_on("steering_system"),
    ),
    BydBinarySensorDescription(
        key="less_one_min",
        source="realtime",
        icon="mdi:timer-alert",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_attr_truthy("less_one_min"),
    ),
    # ====================================
    # Smart-charging schedule
    # ====================================
    BydBinarySensorDescription(
        key="scheduled_charge_enabled",
        source="charging_schedule_charge",
        icon="mdi:calendar-check",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_attr_truthy("status"),
    ),
    BydBinarySensorDescription(
        key="scheduled_charge_until_full",
        source="charging_schedule_charge",
        icon="mdi:battery-charging-100",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_attr_truthy("charge_until_full"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BYD binary sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[str, BydDataUpdateCoordinator] = data["coordinators"]

    entities: list[BinarySensorEntity] = []
    for vin, coordinator in coordinators.items():
        vehicle = coordinator.vehicle
        for description in BINARY_SENSOR_DESCRIPTIONS:
            entities.append(BydBinarySensor(coordinator, vin, vehicle, description))

    async_add_entities(entities)


class BydBinarySensor(BydVehicleEntity, BinarySensorEntity, RestoreEntity):
    """Representation of a BYD vehicle binary sensor.

    Survives restarts and config-entry reloads via ``RestoreEntity`` —
    the cached ``_last_is_on`` value is seeded from HA's restore state
    on ``async_added_to_hass()`` so a partial post-reload payload that
    drops a field (typical of deep-sleep responses) doesn't flip a known
    value to ``unknown``.
    """

    _attr_has_entity_name = True
    entity_description: BydBinarySensorDescription

    def __init__(
        self,
        coordinator: BydDataUpdateCoordinator,
        vin: str,
        vehicle: Vehicle,
        description: BydBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._vin = vin
        self._vehicle = vehicle
        self._attr_unique_id = f"{vin}_{description.source}_{description.key}"
        self._last_is_on: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Restore last known is_on value before the coordinator binds."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None:
            return
        if last.state == STATE_ON:
            self._last_is_on = True
        elif last.state == "off":
            self._last_is_on = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_value(self) -> bool | None:
        """Extract the current value using the description's extraction logic."""
        obj = self._get_source_obj(self.entity_description.source)
        if obj is None:
            return None
        if self.entity_description.value_fn is not None:
            return self.entity_description.value_fn(obj)
        attr = self.entity_description.attr_key or self.entity_description.key
        value = getattr(obj, attr, None)
        if value is None:
            return None
        return bool(value)

    # ------------------------------------------------------------------
    # Entity properties
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Return True when the coordinator has data for this source."""
        return (
            super().available
            and self._get_source_obj(self.entity_description.source) is not None
        )

    @property
    def is_on(self) -> bool | None:
        """Return the binary sensor state.

        Resolution order:
        1. Fresh value from the current data fetch — use it (and cache it).
        2. No value but we have a restored / cached previous one — use that.
           Covers deep-sleep payloads where individual flags drop out
           transiently even though the wider snapshot is present.
        3. Genuinely no signal → ``None``.
        """
        value = self._resolve_value()
        if value is not None:
            return value
        # Field missing this fetch — fall back to last known value if we have one.
        if self._last_is_on is not None:
            return self._last_is_on
        return None

    def _handle_coordinator_update(self) -> None:
        """Track last known state, then run standard coordinator update."""
        value = self._resolve_value()
        if value is not None:
            self._last_is_on = value
        super()._handle_coordinator_update()
