"""BYD inbox messages become Home Assistant notifications, once per message."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from pybyd.models.message_center import VehicleMsgItemInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.byd_vehicle import coordinator as coordinator_module  # noqa: E402
from custom_components.byd_vehicle.const import (  # noqa: E402
    CONF_BASE_URL,
    CONF_DEVICE_PROFILE,
    CONF_INBOX_NOTIFICATIONS,
)
from custom_components.byd_vehicle.coordinator import BydApi  # noqa: E402


class _FakeStore:
    """In-memory stand-in for ``homeassistant.helpers.storage.Store``."""

    saved: dict[str, Any] = {}

    def __init__(self, hass: Any, version: int, key: str) -> None:
        self._key = key

    async def async_load(self) -> Any:
        return self.saved.get(self._key)

    async def async_save(self, data: Any) -> None:
        self.saved[self._key] = data


def _message(message_id: int, minute: int, title: str = "Charging") -> VehicleMsgItemInfo:
    return VehicleMsgItemInfo.model_validate(
        {
            "pushId": message_id,
            "pushTime": int(datetime(2026, 11, 14, 10, minute, tzinfo=UTC).timestamp() * 1000),
            "title": title,
            "content": f"message {message_id}",
        }
    )


@pytest.fixture(autouse=True)
def _patch_store(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeStore.saved = {}
    monkeypatch.setattr(coordinator_module, "Store", _FakeStore)


@pytest.fixture
def notify(monkeypatch: pytest.MonkeyPatch) -> Mock:
    create = Mock()
    monkeypatch.setattr(coordinator_module.persistent_notification, "async_create", create)
    return create


def _api(enabled: bool | None, inbox: list[list[VehicleMsgItemInfo]]) -> tuple[BydApi, list[int]]:
    """Build a BydApi whose async_call serves *inbox* one fetch at a time."""
    hass: Any = SimpleNamespace(config=SimpleNamespace(time_zone="UTC", path=lambda *parts: "/tmp/byd"))
    options = {} if enabled is None else {CONF_INBOX_NOTIFICATIONS: enabled}
    entry: Any = SimpleNamespace(
        entry_id="entry",
        data={
            "username": "user",
            "password": "pass",
            CONF_BASE_URL: "https://example.invalid",
            CONF_DEVICE_PROFILE: {},
        },
        options=options,
    )
    api = BydApi(hass, entry, session=None)
    calls: list[int] = []

    async def _fake_call(handler: Any, **_: Any) -> Any:
        calls.append(1)
        return inbox[min(len(calls), len(inbox)) - 1]

    api.async_call = _fake_call  # type: ignore[method-assign]
    return api, calls


def test_inbox_is_off_by_default(notify: Mock) -> None:
    api, calls = _api(None, [[_message(1, 0)]])
    assert api.inbox_enabled is False
    asyncio.run(api.async_refresh_inbox())
    assert calls == []
    notify.assert_not_called()


def test_new_messages_notify_once_and_sort_newest_first(notify: Mock) -> None:
    older, newer = _message(101, 0, "Start"), _message(102, 5, "Stop")
    api, calls = _api(True, [[older, newer]])

    async def exercise() -> None:
        await api.async_refresh_inbox()
        await api.async_refresh_inbox()  # inside the fetch interval
        api._inbox_fetched_at = datetime.now(UTC) - timedelta(minutes=16)
        await api.async_refresh_inbox()  # same messages, already seen

    asyncio.run(exercise())
    assert len(calls) == 2
    assert {c.kwargs["notification_id"] for c in notify.call_args_list} == {
        "byd_vehicle_entry_message_101",
        "byd_vehicle_entry_message_102",
    }
    assert [m.message_id for m in api.inbox_messages] == [102, 101]


def test_seen_ids_survive_restart(notify: Mock) -> None:
    first, second = _message(1, 0), _message(2, 1)
    api, _ = _api(True, [[first]])
    asyncio.run(api.async_refresh_inbox())
    assert notify.call_count == 1

    restarted, _ = _api(True, [[first, second]])
    asyncio.run(restarted.async_refresh_inbox())
    assert notify.call_count == 2
    assert notify.call_args.kwargs["notification_id"] == "byd_vehicle_entry_message_2"


def test_read_messages_are_pruned_from_store(notify: Mock) -> None:
    api, _ = _api(True, [[_message(1, 0)], []])

    async def exercise() -> None:
        await api.async_refresh_inbox()
        api._inbox_fetched_at = None
        await api.async_refresh_inbox()

    asyncio.run(exercise())
    assert _FakeStore.saved["byd_vehicle_inbox_entry"] == []
    assert api.inbox_messages == []


def test_failed_fetch_backs_off(notify: Mock) -> None:
    api, calls = _api(True, [[]])

    async def _failing_call(handler: Any, **_: Any) -> Any:
        calls.append(1)
        raise coordinator_module.HomeAssistantError("endpoint not supported")

    api.async_call = _failing_call  # type: ignore[method-assign]

    async def exercise() -> None:
        with pytest.raises(coordinator_module.HomeAssistantError):
            await api.async_refresh_inbox()
        await api.async_refresh_inbox()

    asyncio.run(exercise())
    assert len(calls) == 1
