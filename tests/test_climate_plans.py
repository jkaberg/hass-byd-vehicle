"""Climate plan service helpers (pyBYD#91 payloads)."""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from homeassistant.exceptions import HomeAssistantError
from pybyd.models.standby import StandbyPlan, StandbyPlanList, StandbySchedule

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.byd_vehicle.plans import (  # noqa: E402
    commands_from_call,
    find_plan,
    next_run,
    plan_summary,
    schedule_from_call,
)

MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime.datetime(2026, 11, 18, 15, 42, tzinfo=MADRID)  # Wednesday
_OPENAIR = {
    "mainSettingTemp": 5,
    "cycleMode": 1,
    "remoteMode": 4,
    "airConditioningMode": 1,
    "airAccuracy": 1,
    "copilotSettingTemp": 5,
    "timeSpan": 1,
}
_SEATS = {
    "mainHeat": 1,
    "mainVentilation": 3,
    "copilotHeat": 3,
    "copilotVentilation": 1,
    "chairType": 8,
}
_PLAN = {
    "id": 1216038691305533440,
    "planName": "Conducción confort",
    "planType": 1,
    "defaultPlan": 1,
    "executeType": "2",
    "startTime": "13:30",
    "weeklyDays": "4,5,6",
    "executeTime": 1795177800000,
    "timeZone": "Europe/Madrid",
    "controlParamsList": [
        {
            "commandId": "3",
            "commandType": "OPENAIR",
            "controlParamsMap": json.dumps(_OPENAIR),
        }
    ],
}


def _plan(**overrides: Any) -> StandbyPlan:
    return StandbyPlanList.model_validate({"data": [{**_PLAN, **overrides}]}).plans[0]


def _full_plan() -> StandbyPlan:
    return _plan(
        controlParamsList=[
            {"commandType": "OPENAIR", "controlParamsMap": json.dumps(_OPENAIR)},
            {
                "commandType": "VENTILATIONHEATING",
                "controlParamsMap": json.dumps(_SEATS),
            },
            {
                "commandType": "STEERINGWHEELHEATING",
                "controlParamsMap": '{"steeringWheelHeatState":1,"chairType":5}',
            },
        ]
    )


def _all(_: str) -> bool:
    return True


def _none(_: str) -> bool:
    return False


# --- next run -----------------------------------------------------------


def test_next_run_weekly() -> None:
    assert next_run(_plan(), NOW) == datetime.datetime(
        2026, 11, 20, 13, 30, tzinfo=MADRID
    )


def test_next_run_daily_ignores_stale_execute_time() -> None:
    # 23:12 every day, executeTime from a week ago
    plan = _plan(
        executeType="1", startTime=None, weeklyDays="", executeTime=1794435120000
    )
    assert next_run(plan, NOW) == datetime.datetime(2026, 11, 18, 23, 12, tzinfo=MADRID)


def test_next_run_once_in_the_past() -> None:
    plan = _plan(
        executeType="0", startTime=None, weeklyDays="", executeTime=1795371000000
    )
    assert next_run(plan, NOW) == datetime.datetime(2026, 11, 22, 19, 10, tzinfo=MADRID)
    assert next_run(plan, NOW + datetime.timedelta(days=7)) is None


def test_next_run_unscheduled() -> None:
    assert next_run(_plan(startTime="", weeklyDays=""), NOW) is None


# --- summary --------------------------------------------------------------


def test_summary() -> None:
    summary = plan_summary(_full_plan(), temp_offset=14, now=NOW)
    assert summary == {
        "id": "1216038691305533440",
        "name": "Conducción confort",
        "preset": True,
        "default": True,
        "repeat": "custom",
        "start_time": "13:30",
        "weekdays": ["fri", "sat", "sun"],
        "next_run": "2026-11-20T13:30:00+01:00",
        "climate": True,
        "temperature": 19.0,
        "duration": 10,
        "driver_seat_heat": "high",
        "driver_seat_ventilation": "off",
        "passenger_seat_heat": "off",
        "passenger_seat_ventilation": "high",
        "steering_wheel_heat": True,
    }


def test_summary_once() -> None:
    plan = _plan(
        executeType="0", startTime=None, weeklyDays="", executeTime=1795371000000
    )
    summary = plan_summary(plan, temp_offset=14, now=NOW)
    assert summary["repeat"] == "single"
    assert summary["date"] == "2026-11-22"
    assert summary["start_time"] == "19:10"


# --- lookup ---------------------------------------------------------------


def test_find_plan() -> None:
    plans = [_plan(), _plan(id=2, planName="Work", planType=2)]
    assert find_plan(plans, "2").plan_name == "Work"
    assert find_plan(plans, "Work").id == "2"
    with pytest.raises(HomeAssistantError):
        find_plan(plans, "Home")
    with pytest.raises(HomeAssistantError):
        find_plan([*plans, _plan(id=3, planName="Work")], "Work")


# --- schedule ---------------------------------------------------------------


def _schedule(data: dict[str, Any], current: StandbySchedule | None = None) -> Any:
    return schedule_from_call(data, current=current, zone=MADRID, now=NOW)


def test_schedule_untouched() -> None:
    assert _schedule({"temperature": 20}) is None


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"repeat": "off"}, StandbySchedule.off()),
        (
            {"repeat": "single", "start_time": "07:15"},
            StandbySchedule.once(datetime.datetime(2026, 11, 19, 7, 15, tzinfo=MADRID)),
        ),
        (
            {"repeat": "single", "start_time": "19:10", "date": "2026-11-22"},
            StandbySchedule.once(
                datetime.datetime(2026, 11, 22, 19, 10, tzinfo=MADRID)
            ),
        ),
        (
            {"repeat": "every_day", "start_time": datetime.time(23, 12)},
            StandbySchedule.daily(
                datetime.datetime(2026, 11, 18, 23, 12, tzinfo=MADRID)
            ),
        ),
        (
            {"repeat": "weekdays", "start_time": "07:17"},
            StandbySchedule.weekly("07:17", [0, 1, 2, 3, 4]),
        ),
        (
            {"repeat": "weekends", "start_time": "09:00:00"},
            StandbySchedule.weekly("09:00", [5, 6]),
        ),
        (
            {"repeat": "custom", "start_time": "07:17", "weekdays": ["mon", "wed"]},
            StandbySchedule.weekly("07:17", [0, 2]),
        ),
        # start_time alone on create means a single run
        (
            {"start_time": "16:00"},
            StandbySchedule.once(datetime.datetime(2026, 11, 18, 16, 0, tzinfo=MADRID)),
        ),
    ],
)
def test_schedule_from_call(data: dict[str, Any], expected: StandbySchedule) -> None:
    assert _schedule(data) == expected


def test_schedule_keeps_current_values() -> None:
    current = StandbySchedule.weekly("13:30", [4, 5, 6])
    assert _schedule({"start_time": "08:00"}, current) == StandbySchedule.weekly(
        "08:00", [4, 5, 6]
    )
    assert _schedule({"weekdays": ["mon"]}, current) == StandbySchedule.weekly(
        "13:30", [0]
    )
    assert _schedule({"repeat": "every_day"}, current) == StandbySchedule.daily(
        datetime.datetime(2026, 11, 19, 13, 30, tzinfo=MADRID)
    )


@pytest.mark.parametrize(
    "data",
    [
        {"repeat": "single"},
        {"repeat": "single", "start_time": "07:00", "date": "2026-11-18"},
        {"repeat": "custom", "start_time": "07:00"},
        {"repeat": "custom", "start_time": "07:00", "weekdays": ["xyz"]},
        {"repeat": "monthly", "start_time": "07:00"},
        {"repeat": "weekdays", "start_time": "25:00"},
    ],
)
def test_schedule_rejects(data: dict[str, Any]) -> None:
    with pytest.raises(HomeAssistantError):
        _schedule(data)


# --- commands ---------------------------------------------------------------


def _types(commands: list[Any]) -> list[str]:
    return [command.command_type for command in commands]


def test_commands_copy_base() -> None:
    plan = _full_plan()
    commands = commands_from_call({}, base=plan, temp_offset=14, supports=_all)
    assert [c.control_params_map for c in commands] == [
        c.control_params_map for c in plan.commands
    ]


def test_commands_override_temperature_keeps_other_ac_settings() -> None:
    plan = _plan(
        controlParamsList=[
            {
                "commandType": "OPENAIR",
                "controlParamsMap": json.dumps({**_OPENAIR, "cycleMode": 2}),
            }
        ]
    )
    (climate,) = commands_from_call(
        {"temperature": 22, "duration": 20}, base=plan, temp_offset=14, supports=_all
    )
    assert climate.control_params_map["mainSettingTemp"] == 8
    assert climate.control_params_map["copilotSettingTemp"] == 8
    assert climate.control_params_map["timeSpan"] == 3
    assert climate.control_params_map["cycleMode"] == 2


def test_commands_drop_and_add() -> None:
    commands = commands_from_call(
        {"climate": False, "driver_seat_heat": "low", "steering_wheel_heat": True},
        base=_plan(),
        temp_offset=14,
        supports=_all,
    )
    assert _types(commands) == ["VENTILATIONHEATING", "STEERINGWHEELHEATING"]
    assert commands[0].control_params_map["mainHeat"] == 2
    assert commands[0].control_params_map["copilotHeat"] == 3


def test_commands_seats_all_off_drops_seat_command() -> None:
    commands = commands_from_call(
        {"driver_seat_heat": "off", "passenger_seat_ventilation": "off"},
        base=_full_plan(),
        temp_offset=14,
        supports=_all,
    )
    assert _types(commands) == ["OPENAIR", "STEERINGWHEELHEATING"]


def test_commands_without_base_use_defaults() -> None:
    (climate,) = commands_from_call(
        {"climate": True}, base=None, temp_offset=14, supports=_all
    )
    assert climate.control_params_map["mainSettingTemp"] == 7  # 21 °C
    assert climate.control_params_map["timeSpan"] == 1


@pytest.mark.parametrize(
    "data",
    [
        {"climate": False},
        {"temperature": 40},
        {"driver_seat_heat": "high"},
        {"steering_wheel_heat": True},
    ],
)
def test_commands_reject(data: dict[str, Any]) -> None:
    with pytest.raises(HomeAssistantError):
        commands_from_call(data, base=_plan(), temp_offset=14, supports=_none)
