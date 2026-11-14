"""Freshness is source data age, not coordinator success or field changes."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pybyd import BydAuthenticationError, BydTransportError

from custom_components.byd_vehicle.coordinator import (
    BydDataUpdateCoordinator,
    BydGpsUpdateCoordinator,
)
from custom_components.byd_vehicle.freshness import data_age, freshness_state
from custom_components.byd_vehicle.sensor import BydFreshnessSensor
from custom_components.byd_vehicle.sensor import async_setup_entry as setup_sensors

NOW = datetime(2026, 11, 14, 8, tzinfo=UTC)
OLD = NOW - timedelta(hours=2)


@pytest.mark.parametrize(
    "timestamp",
    [
        None,
        "not a timestamp",
        0,
        NOW.replace(tzinfo=None),
        datetime(1970, 1, 1, tzinfo=UTC),
        NOW + timedelta(seconds=1),
    ],
)
def test_untrustworthy_timestamp_is_unknown(timestamp):
    assert data_age(timestamp, NOW) is None


def test_age_uses_elapsed_time_and_timezone():
    assert data_age(OLD, NOW) == 7200
    assert data_age(NOW.astimezone(UTC), NOW) == 0
    assert data_age(OLD, NOW + timedelta(minutes=1)) == 7260


@pytest.mark.parametrize(
    ("age", "polling", "seconds", "expected"),
    [
        (None, True, 300, None),
        (None, False, 300, "paused"),
        (0, True, 30, "fresh"),
        (300, True, 30, "fresh"),
        (301, True, 30, "stale"),
        (600, True, 300, "fresh"),
        (601, True, 300, "stale"),
        (2400, True, 1200, "fresh"),
        (2401, True, 1200, "stale"),
        (7200, False, 300, "paused"),
    ],
)
def test_effective_interval_and_pause(age, polling, seconds, expected):
    assert freshness_state(age, polling, timedelta(seconds=seconds)) == expected


@pytest.mark.parametrize(
    ("reference", "effective_telemetry_seconds", "telemetry_state", "gps_state"),
    [
        ("2026-11-14T09:13:43+00:00", 60, "fresh", "fresh"),
        ("2026-11-14T09:16:40+00:00", 60, "stale", "fresh"),
        ("2026-11-14T09:16:40+00:00", 240, "fresh", "fresh"),
    ],
)
def test_observed_display_values_with_independent_cadence(
    reference, effective_telemetry_seconds, telemetry_state, gps_state
):
    # Replayed UI values, not an assertion of a new live sample or raw GPS time.
    now = datetime.fromisoformat(reference)
    telemetry = datetime.fromisoformat("2026-11-14T09:09:36+00:00")
    gps = datetime.fromisoformat("2026-11-14T09:09:40+00:00")
    assert (
        freshness_state(
            data_age(telemetry, now),
            True,
            timedelta(seconds=effective_telemetry_seconds),
        )
        == telemetry_state
    )
    assert (
        freshness_state(data_age(gps, now), True, timedelta(seconds=300)) == gps_state
    )


def source_coordinator():
    return SimpleNamespace(
        data=SimpleNamespace(
            realtime=SimpleNamespace(timestamp=NOW),
            gps=SimpleNamespace(gps_timestamp=OLD),
        ),
        last_successful_fetch=None,
        update_interval=timedelta(minutes=5),
        poll_interval_seconds=300,
        polling_enabled=True,
    )


def sensor(coordinator, source="telemetry", kind="freshness"):
    return BydFreshnessSensor(coordinator, "TESTVIN", SimpleNamespace(), source, kind)


def test_gps_and_status_freshness_are_independent():
    c = source_coordinator()
    with patch("custom_components.byd_vehicle.sensor.dt_util.utcnow", return_value=NOW):
        assert sensor(c).native_value == "fresh"
        assert sensor(c, "gps").native_value == "stale"
        assert sensor(c, "gps").extra_state_attributes["data_age_seconds"] == 7200


@pytest.mark.parametrize(
    ("source", "age", "effective_interval", "configured_interval", "threshold"),
    [("telemetry", 60, 240, 60, 480), ("gps", 150, 300, 300, 600)],
)
def test_live_observed_attributes_follow_effective_not_configured_interval(
    source, age, effective_interval, configured_interval, threshold
):
    c = source_coordinator()
    c.poll_interval_seconds = configured_interval
    c.update_interval = timedelta(seconds=effective_interval)
    if source == "gps":
        c.data.gps.gps_timestamp = NOW - timedelta(seconds=age)
    else:
        c.data.realtime.timestamp = NOW - timedelta(seconds=age)
    with patch("custom_components.byd_vehicle.sensor.dt_util.utcnow", return_value=NOW):
        entity = sensor(c, source)
        assert entity.native_value == "fresh"
        assert entity.extra_state_attributes == {
            "data_age_seconds": age,
            "freshness_threshold_seconds": threshold,
            "polling_enabled": True,
        }


def test_old_gps_is_not_shifted_to_new_telemetry_time():
    c = source_coordinator()
    with patch("custom_components.byd_vehicle.sensor.dt_util.utcnow", return_value=NOW):
        assert sensor(c, "gps").native_value == "stale"
        c.data.gps.gps_timestamp = NOW + timedelta(hours=1)
        assert sensor(c, "gps").native_value is None


def test_successful_contact_does_not_freshen_old_vehicle_data():
    c = source_coordinator()
    c.last_successful_fetch = NOW
    c.data.realtime.timestamp = OLD
    with patch("custom_components.byd_vehicle.sensor.dt_util.utcnow", return_value=NOW):
        assert sensor(c).native_value == "stale"
        assert sensor(c, kind="last_successful_fetch").native_value == NOW


def test_clock_alone_ages_data_without_a_poll():
    c = source_coordinator()
    entity = sensor(c)
    with patch(
        "custom_components.byd_vehicle.sensor.dt_util.utcnow",
        return_value=NOW + timedelta(minutes=11),
    ):
        assert entity.native_value == "stale"
    entity.async_write_ha_state = Mock()
    entity._update_age(NOW)
    entity.async_write_ha_state.assert_called_once_with()
    assert c.last_successful_fetch is None


def test_paused_and_missing_data_are_not_claimed_fresh():
    c = source_coordinator()
    c.data = None
    entity = sensor(c)
    assert entity.available is True
    assert entity.native_value is None
    c.polling_enabled = False
    c.update_interval = None
    assert entity.native_value == "paused"
    assert entity.extra_state_attributes["data_age_seconds"] is None


def test_recovery_follows_source_timestamp_without_value_change():
    c = source_coordinator()
    c.data.realtime.timestamp = OLD
    entity = sensor(c)
    with patch("custom_components.byd_vehicle.sensor.dt_util.utcnow", return_value=NOW):
        assert entity.native_value == "stale"
        c.data.realtime.timestamp = NOW
        assert entity.native_value == "fresh"


def test_entities_are_opt_in_unique_and_do_not_export_payloads():
    c = source_coordinator()
    entities = [
        sensor(c, source, kind)
        for source in ["telemetry", "gps"]
        for kind in ["freshness", "last_successful_fetch"]
    ]
    assert len({e.unique_id for e in entities}) == 4
    assert all(e.entity_registry_enabled_default is False for e in entities)
    assert set(entities[0].extra_state_attributes) == {
        "data_age_seconds",
        "freshness_threshold_seconds",
        "polling_enabled",
    }
    assert entities[1].extra_state_attributes == {}


def polling_coordinator(cls):
    c = object.__new__(cls)
    state = SimpleNamespace(
        realtime=SimpleNamespace(timestamp=OLD),
        gps=SimpleNamespace(gps_timestamp=OLD),
        hvac=None,
    )
    car = SimpleNamespace(
        state=state,
        update_realtime=AsyncMock(),
        update_gps=AsyncMock(),
        update_charging=AsyncMock(),
    )
    c.data = state
    c._vin = "TESTVIN"
    c._vehicle = SimpleNamespace()
    c._force_next_refresh = False
    c._polling_enabled = True
    c.last_successful_fetch = None
    c._api = SimpleNamespace(debug_dumps_enabled=False)
    c._car = car
    if cls is BydDataUpdateCoordinator:
        c.update_pending = False
        c._realtime_endpoint_unsupported = False
        c._should_fetch_hvac = Mock(return_value=False)
        c._schedule_hvac_final_reconcile_if_needed = Mock()
        c._apply_charge_cadence = Mock()
    else:
        c._telemetry_coordinator = SimpleNamespace(car=car)
    return c, car


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", [BydDataUpdateCoordinator, BydGpsUpdateCoordinator])
async def test_only_actual_successful_source_fetch_records_contact(cls):
    c, car = polling_coordinator(cls)
    await c._async_update_data()
    assert c.last_successful_fetch is not None
    assert c.data.realtime.timestamp == OLD
    call = car.update_realtime if cls is BydDataUpdateCoordinator else car.update_gps
    call.assert_awaited_once()
    last_success = c.last_successful_fetch
    call.side_effect = BydTransportError("offline")
    await c._async_update_data()
    assert c.last_successful_fetch == last_success


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", [BydDataUpdateCoordinator, BydGpsUpdateCoordinator])
async def test_skipped_poll_or_auth_failure_does_not_record_contact(cls):
    c, car = polling_coordinator(cls)
    c._polling_enabled = False
    await c._async_update_data()
    assert c.last_successful_fetch is None
    c._polling_enabled = True
    call = car.update_realtime if cls is BydDataUpdateCoordinator else car.update_gps
    call.side_effect = BydAuthenticationError("re-auth required")
    with pytest.raises(BydAuthenticationError):
        await c._async_update_data()
    assert c.last_successful_fetch is None


def test_push_or_command_projection_does_not_record_http_contact():
    for cls in [BydDataUpdateCoordinator, BydGpsUpdateCoordinator]:
        c, _ = polling_coordinator(cls)
        c.async_update_listeners = Mock()
        if cls is BydDataUpdateCoordinator:
            c._apply_charge_cadence = Mock()
        c._async_handle_state_push(c.data)
        assert c.last_successful_fetch is None


@pytest.mark.asyncio
@pytest.mark.parametrize("with_gps", [True, False])
async def test_setup_registers_only_available_sources_opt_in(with_gps):
    c = source_coordinator()
    c.vehicle = SimpleNamespace()
    entry = SimpleNamespace(entry_id="test")
    hass = SimpleNamespace(
        data={
            "byd_vehicle": {
                "test": {
                    "coordinators": {"TESTVIN": c},
                    "gps_coordinators": {"TESTVIN": c} if with_gps else {},
                }
            }
        }
    )
    added = []
    with patch("custom_components.byd_vehicle.sensor.BydSensor"):
        await setup_sensors(hass, entry, added.extend)
    diagnostics = [e for e in added if isinstance(e, BydFreshnessSensor)]
    assert len(diagnostics) == (4 if with_gps else 2)
    assert all(e.entity_registry_enabled_default is False for e in diagnostics)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["freshness", "last_successful_fetch"])
async def test_enabled_freshness_timer_is_local_and_cleaned_up(kind):
    c = source_coordinator()
    listener_cleanup, timer_cleanup = Mock(), Mock()
    c.async_add_listener = Mock(return_value=listener_cleanup)
    e = sensor(c, kind=kind)
    e.hass = SimpleNamespace()
    with patch(
        "custom_components.byd_vehicle.sensor.async_track_time_interval",
        return_value=timer_cleanup,
    ) as track:
        await e.async_added_to_hass()
        if kind == "freshness":
            track.assert_called_once_with(e.hass, e._update_age, timedelta(minutes=1))
        else:
            track.assert_not_called()
        for cleanup in e._on_remove:
            cleanup()
    listener_cleanup.assert_called_once()
    assert timer_cleanup.call_count == (1 if kind == "freshness" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", [BydDataUpdateCoordinator, BydGpsUpdateCoordinator])
async def test_manual_source_fetch_records_success_and_retains_it_on_failure(cls):
    c, car = polling_coordinator(cls)
    c.async_update_listeners = Mock()
    method = (
        c.async_fetch_realtime if cls is BydDataUpdateCoordinator else c.async_fetch_gps
    )
    call = car.update_realtime if cls is BydDataUpdateCoordinator else car.update_gps
    await method()
    last_success = c.last_successful_fetch
    assert last_success is not None
    call.side_effect = BydTransportError("offline")
    await method()
    assert c.last_successful_fetch == last_success
