"""TurnCoordinator 防抖与 inbox 单元测试。"""

from __future__ import annotations

import asyncio

import pytest

from dnd.turn.coordinator import TurnCoordinator

pytestmark = pytest.mark.anyio


async def test_no_debounce_until_active_speaks() -> None:
    tc = TurnCoordinator(debounce_seconds=0.05)
    tc.set_active("alice")
    tc.append({"player_id": "bob", "text": "wait"})
    assert tc.debounce_scheduled is False
    tc.on_active_player_message("alice")
    assert tc.debounce_scheduled is True


async def test_active_resets_debounce() -> None:
    tc = TurnCoordinator(debounce_seconds=0.05)
    tc.set_active("alice")
    tc.on_active_player_message("alice")
    first = tc.debounce_generation
    tc.on_active_player_message("alice")
    assert tc.debounce_generation == first + 1


async def test_inbox_tags_active_and_initiative() -> None:
    tc = TurnCoordinator(debounce_seconds=0.05)
    tc.set_active("alice")
    tc.set_initiative(["alice", "bob", "carol"])
    tc.append({"player_id": "bob", "text": "hold"})
    messages = tc._inbox.peek()
    assert len(messages) == 1
    assert messages[0].is_active is False
    assert messages[0].initiative_distance == 1


async def test_flush_sets_processing_lock() -> None:
    tc = TurnCoordinator(debounce_seconds=0.05)
    tc.append({"player_id": "alice", "text": "act"})
    flushed = tc.flush("test")
    assert len(flushed) == 1
    assert tc.processing is True
    assert len(tc._inbox) == 0
    tc.complete_processing()
    assert tc.processing is False


async def test_request_proceed_busy_while_processing() -> None:
    tc = TurnCoordinator(debounce_seconds=0.05)
    tc.processing = True
    assert tc.request_proceed() is None


async def test_debounce_fires_after_timeout() -> None:
    tc = TurnCoordinator(debounce_seconds=0.05)
    tc.set_active("alice")
    tc.append({"player_id": "alice", "text": "hello"})
    tc.on_active_player_message("alice")
    await asyncio.sleep(0.08)
    assert tc.processing is True
