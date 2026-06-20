"""地下城播报层：聊天发送 + Maisaka 历史同步。"""

from __future__ import annotations

from typing import Any

from dnd.config import DndConfig

GM_SOURCE_KIND = "plugin:dnd-gm"
SYSTEM_SOURCE_KIND = "plugin:dnd"


async def _broadcast_text(
    ctx: Any,
    stream_id: str,
    full_text: str,
    cfg: DndConfig,
    *,
    source_kind: str,
) -> None:
    if not stream_id:
        return
    ok = await ctx.send.text(
        full_text,
        stream_id,
        sync_to_maisaka_history=cfg.broadcast.sync_to_maisaka_history,
        maisaka_source_kind=source_kind,
    )
    if not ok:
        ctx.logger.warning("send 失败，fallback context.append")
        await ctx.maisaka.context.append(
            stream_id=stream_id,
            segments=[{"type": "text", "content": full_text}],
            source_kind=source_kind,
        )


async def broadcast_gm(ctx: Any, stream_id: str, text: str, cfg: DndConfig) -> None:
    """播报 GM 系统消息（【地下城·GM】前缀）。"""
    full = f"{cfg.broadcast.system_prefix_gm}{text}"
    await _broadcast_text(ctx, stream_id, full, cfg, source_kind=GM_SOURCE_KIND)


async def broadcast_system(ctx: Any, stream_id: str, text: str, cfg: DndConfig) -> None:
    """播报普通系统消息（【地下城】前缀）。"""
    full = f"{cfg.broadcast.system_prefix}{text}"
    await _broadcast_text(ctx, stream_id, full, cfg, source_kind=SYSTEM_SOURCE_KIND)


async def wake_mai_turn(
    ctx: Any,
    stream_id: str,
    text: str,
    intent: str,
    reason: str,
    metadata: dict[str, Any] | None,
    cfg: DndConfig,
) -> None:
    """向聊天播报回合提示并唤醒 MaiBot 主动处理。"""
    await broadcast_system(ctx, stream_id, text, cfg)
    await ctx.maisaka.proactive.trigger(
        stream_id=stream_id,
        intent=intent,
        reason=reason,
        metadata=metadata or {},
    )
