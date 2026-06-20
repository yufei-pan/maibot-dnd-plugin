"""软回合协调：收件箱、防抖与 proceed 触发。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any
from typing import Awaitable, Callable

from dnd.turn.inbox import Inbox, InboxMessage

FlushCallback = Callable[[str, list[InboxMessage]], Awaitable[None]]


class TurnCoordinator:
    """管理活跃玩家发言后的防抖计时与 inbox 冲刷。"""

    def __init__(self, *, debounce_seconds: float, flush_callback: FlushCallback | None = None) -> None:
        self.debounce_seconds = float(debounce_seconds)
        self.debounce_scheduled = False
        self.debounce_generation = 0
        self.processing = False
        self._inbox = Inbox()
        self._active_id: str = ""
        self._initiative: list[str] = []
        self._active_has_spoken = False
        self._debounce_task: asyncio.Task[None] | None = None
        self._flush_callback = flush_callback

    def set_active(self, player_id: str) -> None:
        """设置当前活跃玩家。"""
        self._active_id = str(player_id).strip()

    def set_initiative(self, order: list[str]) -> None:
        """设置先攻顺序（仅供标注 initiative_distance）。"""
        self._initiative = [str(item).strip() for item in order if str(item).strip()]

    def set_flush_callback(self, callback: FlushCallback | None) -> None:
        """设置 flush 完成后的异步回调。"""
        self._flush_callback = callback

    def append(self, msg: InboxMessage | Mapping[str, Any]) -> None:
        """追加消息并打上活跃/先攻距离标签。"""
        if isinstance(msg, InboxMessage):
            tagged = msg
        else:
            player_id = str(msg["player_id"])
            text = str(msg["text"])
            tagged = InboxMessage(
                player_id=player_id,
                text=text,
                is_active=player_id == self._active_id,
                initiative_distance=self._initiative_distance(player_id),
                ooc=bool(msg.get("ooc", False)),
            )
        self._inbox.append(tagged)

    def on_active_player_message(self, player_id: str) -> None:
        """活跃玩家发言后启动或重置防抖计时。"""
        if str(player_id).strip() != self._active_id:
            return
        self._active_has_spoken = True
        self.debounce_generation += 1
        generation = self.debounce_generation
        self._schedule_debounce(generation)

    def request_proceed(self) -> list[InboxMessage] | None:
        """任意报名玩家可手动推进；处理中返回 None。"""
        if self.processing:
            return None
        return self.flush("proceed")

    def request_skip(self) -> list[InboxMessage] | None:
        """创建者/管理员跳过等待活跃玩家发言。"""
        if self.processing:
            return None
        self._cancel_debounce()
        return self.flush("skip")

    def flush(self, reason: str) -> list[InboxMessage]:
        """清空 inbox 并进入处理锁。"""
        del reason
        self._cancel_debounce()
        self.processing = True
        self._active_has_spoken = False
        return self._inbox.drain()

    async def dispatch_flush(self, reason: str, flushed: list[InboxMessage]) -> None:
        """将已冲刷的消息交给外部回调处理。"""
        callback = self._flush_callback
        if callback is None:
            return
        await callback(reason, flushed)

    def requeue(self, messages: list[InboxMessage]) -> None:
        """当 beat 失败时将消息放回队列。"""
        self._inbox.extend_front(messages)

    def complete_processing(self) -> None:
        """GM 节拍结束后释放处理锁。"""
        self.processing = False

    @property
    def pending_count(self) -> int:
        """当前收件箱中待处理消息条数。"""
        return len(self._inbox)

    def _initiative_distance(self, player_id: str) -> int:
        if not self._initiative or not self._active_id:
            return -1
        try:
            active_idx = self._initiative.index(self._active_id)
            player_idx = self._initiative.index(player_id)
        except ValueError:
            return -1
        span = len(self._initiative)
        return (player_idx - active_idx) % span

    def _schedule_debounce(self, generation: int) -> None:
        self._cancel_debounce_task_only()
        self.debounce_scheduled = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.debounce_scheduled = False
            return
        self._debounce_task = loop.create_task(self._debounce_wait(generation))

    async def _debounce_wait(self, generation: int) -> None:
        try:
            await asyncio.sleep(self.debounce_seconds)
        except asyncio.CancelledError:
            return
        if generation != self.debounce_generation:
            return
        if self.processing:
            self.debounce_scheduled = False
            return
        self.debounce_scheduled = False
        flushed = self.flush("debounce")
        await self.dispatch_flush("debounce", flushed)

    def _cancel_debounce_task_only(self) -> None:
        task = self._debounce_task
        self._debounce_task = None
        if task is not None and not task.done():
            task.cancel()

    def _cancel_debounce(self) -> None:
        self.debounce_scheduled = False
        self._cancel_debounce_task_only()
