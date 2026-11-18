"""Climate plan calendar (pyBYD#91 payloads)."""

from __future__ import annotations

import asyncio
import datetime
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.exceptions import HomeAssistantError
from pybyd.models.standby import StandbyPlanList

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.byd_vehicle.calendar import (  # noqa: E402
    BydPlanCalendar,
    apply_event,
    parse_weekly_rrule,
    plan_occurrences,
    time_span_for,
)

MADRID = ZoneInfo("Europe/Madrid")
_PARAMS = (
    '{"mainSettingTemp":5,"cycleMode":1,"remoteMode":4,"airConditioningMode":1,'
    '"airAccuracy":1,"copilotSettingTemp":5,"timeSpan":1}'
)
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
        {"commandId": "3", "commandType": "OPENAIR", "controlParamsMap": _PARAMS}
    ],
}


def _plans(**overrides: Any) -> StandbyPlanList:
    return StandbyPlanList.model_validate(
        {"vin": "VIN", "data": [{**_PLAN, **overrides}]}
    )


def test_occurrences_in_week() -> None:
    plan = _plans().plans[0]
    start = datetime.datetime(2026, 11, 16, tzinfo=MADRID)  # Monday
    events = plan_occurrences(plan, start, start + datetime.timedelta(days=7))
    assert [event.start for event in events] == [
        datetime.datetime(2026, 11, d, 13, 30, tzinfo=MADRID) for d in (20, 21, 22)
    ]
    assert events[0].end - events[0].start == datetime.timedelta(minutes=10)
    assert events[0].uid == "1216038691305533440"
    assert events[0].rrule == "FREQ=WEEKLY;BYDAY=FR,SA,SU"
    assert events[0].summary == "Conducción confort"


def test_running_event_is_included() -> None:
    plan = _plans().plans[0]
    now = datetime.datetime(2026, 11, 20, 13, 35, tzinfo=MADRID)
    events = plan_occurrences(plan, now, now + datetime.timedelta(hours=1))
    assert [event.start.day for event in events] == [20]


def test_unscheduled_plan_has_no_events() -> None:
    plan = _plans(startTime="", weeklyDays="").plans[0]
    start = datetime.datetime(2026, 11, 16, tzinfo=MADRID)
    assert plan_occurrences(plan, start, start + datetime.timedelta(days=7)) == []


@pytest.mark.parametrize(
    ("rrule", "expected"),
    [
        ("FREQ=WEEKLY;BYDAY=FR,SA,SU", [4, 5, 6]),
        ("RRULE:FREQ=WEEKLY;INTERVAL=1;BYDAY=MO", [0]),
    ],
)
def test_parse_weekly_rrule(rrule: str, expected: list[int]) -> None:
    assert parse_weekly_rrule(rrule) == expected


@pytest.mark.parametrize(
    "rrule",
    [
        None,
        "",
        "FREQ=DAILY",
        "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO",
        "FREQ=WEEKLY;COUNT=3;BYDAY=MO",
        "FREQ=WEEKLY",
    ],
)
def test_parse_weekly_rrule_rejects(rrule: str | None) -> None:
    with pytest.raises(HomeAssistantError):
        parse_weekly_rrule(rrule)


@pytest.mark.parametrize(
    ("minutes", "code"), [(5, 1), (10, 1), (15, 2), (22, 3), (30, 5), (60, 5)]
)
def test_time_span_for(minutes: float, code: int) -> None:
    assert time_span_for(minutes) == code


def test_apply_event() -> None:
    plan = _plans().plans[0]
    start = datetime.datetime(2026, 11, 23, 6, 45, tzinfo=datetime.UTC)  # 07:45 Madrid
    updated, start_time, days = apply_event(
        plan,
        {
            "dtstart": start,
            "dtend": start + datetime.timedelta(minutes=20),
            "summary": "Work",
            "rrule": "FREQ=WEEKLY;BYDAY=MO,TU",
        },
    )
    assert start_time == "07:45"
    assert days == [0, 1]
    assert updated.plan_name == "Work"
    assert updated.commands[0].control_params_map["timeSpan"] == 3
    assert updated.commands[0].control_params_map["mainSettingTemp"] == 5
    assert plan.commands[0].control_params_map["timeSpan"] == 1


def test_apply_event_rejects_all_day() -> None:
    plan = _plans().plans[0]
    with pytest.raises(HomeAssistantError):
        apply_event(
            plan,
            {
                "dtstart": datetime.date(2026, 11, 23),
                "dtend": datetime.date(2026, 11, 24),
                "rrule": "FREQ=WEEKLY;BYDAY=MO",
            },
        )


def _calendar(
    save_result: StandbyPlanList | None = None,
) -> tuple[BydPlanCalendar, AsyncMock]:
    entity: Any = object.__new__(BydPlanCalendar)
    save = AsyncMock(return_value=save_result or _plans())
    entity.coordinator = SimpleNamespace(async_save_standby_plan=save)
    entity._plans = _plans()
    entity._vin = "VIN"
    entity.async_write_ha_state = lambda: None
    return entity, save


def test_update_event_saves_plan() -> None:
    entity, save = _calendar()
    start = datetime.datetime(2026, 11, 23, 7, 45, tzinfo=MADRID)
    asyncio.run(
        entity.async_update_event(
            "1216038691305533440",
            {
                "dtstart": start,
                "dtend": start + datetime.timedelta(minutes=10),
                "rrule": "FREQ=WEEKLY;BYDAY=MO",
            },
        )
    )
    assert save.await_args.kwargs == {"start_time": "07:45", "weekly_days": [0]}


def test_update_single_occurrence_rejected() -> None:
    entity, save = _calendar()
    start = datetime.datetime(2026, 11, 23, 7, 45, tzinfo=MADRID)
    with pytest.raises(HomeAssistantError):
        asyncio.run(
            entity.async_update_event(
                "1216038691305533440",
                {"dtstart": start, "dtend": start, "rrule": "FREQ=WEEKLY;BYDAY=MO"},
                recurrence_id="20261123T074500",
            )
        )
    save.assert_not_awaited()


def test_delete_unschedules() -> None:
    entity, save = _calendar()
    asyncio.run(entity.async_delete_event("1216038691305533440"))
    assert save.await_args.kwargs == {"start_time": "", "weekly_days": []}


def test_unknown_plan() -> None:
    entity, _ = _calendar()
    with pytest.raises(HomeAssistantError):
        asyncio.run(entity.async_delete_event("nope"))
