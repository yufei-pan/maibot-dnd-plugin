"""播报层单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from dnd.broadcast import broadcast_gm, broadcast_system, wake_mai_turn
from dnd.config import DndConfig

pytestmark = pytest.mark.anyio


@pytest.fixture
def cfg() -> DndConfig:
    return DndConfig()


@pytest.fixture
def mock_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.send.text = AsyncMock(return_value=True)
    ctx.maisaka.context.append = AsyncMock()
    ctx.maisaka.proactive.trigger = AsyncMock()
    ctx.logger = MagicMock()
    return ctx


async def test_broadcast_gm_sync_to_maisaka(mock_ctx: MagicMock, cfg: DndConfig) -> None:
    await broadcast_gm(mock_ctx, "stream-1", "叙述", cfg)
    mock_ctx.send.text.assert_awaited_once_with(
        f"{cfg.broadcast.system_prefix_gm}叙述",
        "stream-1",
        sync_to_maisaka_history=True,
        maisaka_source_kind="plugin:dnd-gm",
    )


async def test_broadcast_system_uses_system_prefix(mock_ctx: MagicMock, cfg: DndConfig) -> None:
    await broadcast_system(mock_ctx, "stream-1", "提示", cfg)
    mock_ctx.send.text.assert_awaited_once_with(
        f"{cfg.broadcast.system_prefix}提示",
        "stream-1",
        sync_to_maisaka_history=True,
        maisaka_source_kind="plugin:dnd",
    )


async def test_broadcast_gm_fallback_on_send_failure(mock_ctx: MagicMock, cfg: DndConfig) -> None:
    mock_ctx.send.text = AsyncMock(return_value=False)
    await broadcast_gm(mock_ctx, "stream-1", "失败测试", cfg)
    mock_ctx.logger.warning.assert_called_once()
    mock_ctx.maisaka.context.append.assert_awaited_once_with(
        stream_id="stream-1",
        segments=[{"type": "text", "content": f"{cfg.broadcast.system_prefix_gm}失败测试"}],
        source_kind="plugin:dnd-gm",
    )


async def test_wake_mai_turn_broadcasts_and_triggers(mock_ctx: MagicMock, cfg: DndConfig) -> None:
    metadata = {"session_id": "s1"}
    await wake_mai_turn(
        mock_ctx,
        "stream-1",
        "轮到你了",
        "dnd_player_turn",
        "active_player_changed",
        metadata,
        cfg,
    )
    mock_ctx.send.text.assert_awaited_once_with(
        f"{cfg.broadcast.system_prefix}轮到你了",
        "stream-1",
        sync_to_maisaka_history=True,
        maisaka_source_kind="plugin:dnd",
    )
    mock_ctx.maisaka.proactive.trigger.assert_awaited_once_with(
        stream_id="stream-1",
        intent="dnd_player_turn",
        reason="active_player_changed",
        metadata=metadata,
    )
