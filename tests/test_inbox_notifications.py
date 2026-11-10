"""Account inbox messages create Home Assistant notifications once per ID."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from custom_components.byd_vehicle.coordinator import BydApi, persistent_notification


def test_inbox_creates_one_notification_per_message(monkeypatch):
    messages = [
        SimpleNamespace(message_id=101, title="Charging", content="Started"),
        SimpleNamespace(message_id=102, title="Charging", content="Stopped"),
    ]
    api = BydApi.__new__(BydApi)
    api._hass = object()
    api._entry = SimpleNamespace(entry_id="entry")
    api._notifications = []
    api._notifications_fetched_at = None
    api._notified_message_ids = set()
    fetch = AsyncMock(return_value=messages)
    api._ensure_client = AsyncMock(
        return_value=SimpleNamespace(get_notifications=fetch)
    )
    create = Mock()
    monkeypatch.setattr(persistent_notification, "async_create", create)

    async def exercise():
        assert await api.async_get_notifications() == messages
        assert await api.async_get_notifications() == messages
        api._notifications_fetched_at = datetime.now(UTC) - timedelta(minutes=16)
        assert await api.async_get_notifications() == messages

    asyncio.run(exercise())
    assert fetch.await_count == 2
    assert create.call_count == 2
    assert {call.kwargs["notification_id"] for call in create.call_args_list} == {
        "byd_vehicle_entry_message_101",
        "byd_vehicle_entry_message_102",
    }
    assert [call.args[1] for call in create.call_args_list] == ["Started", "Stopped"]
