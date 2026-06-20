"""地下城 (MaiBot D&D) 插件。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from maibot_sdk import Command, MaiBotPlugin

from dnd.broadcast import broadcast_system
from dnd.config import CURRENT_CONFIG_VERSION, DndConfig, _normalize_dnd_config
from dnd.gm.broker import run_beat
from dnd.session.lifecycle import LifecycleService
from dnd.session.permissions import can
from dnd.store import SessionRecord, SessionStore
from dnd.turn.coordinator import TurnCoordinator

__all__ = ["CURRENT_CONFIG_VERSION", "DndConfig", "DndPlugin", "create_plugin", "_normalize_dnd_config"]


class DndPlugin(MaiBotPlugin):
    """地下城插件主体。"""

    plugin_id = "maibot-dnd-plugin"
    config_model = DndConfig

    def __init__(self) -> None:
        super().__init__()
        self._plugin_dir = Path(__file__).resolve().parent
        self._coordinators: dict[str, TurnCoordinator] = {}
        self._mai_person_id = ""

    async def on_load(self) -> None:
        self.ctx.logger.info("地下城插件已加载")

    async def on_unload(self) -> None:
        self._coordinators.clear()
        self.ctx.logger.info("地下城插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        merged, _, notes = _normalize_dnd_config(config_data, DndConfig().model_dump(mode="python"))
        if notes:
            self.ctx.logger.info("配置迁移: %s", "; ".join(notes))

    def _data_root(self) -> Path:
        return self._plugin_dir / "data"

    def _store(self) -> SessionStore:
        return SessionStore(self._data_root())

    def _lifecycle(self) -> LifecycleService:
        return LifecycleService(self._store())

    @staticmethod
    def _resolve_stream_id(kwargs: dict[str, Any]) -> str:
        for key in ("stream_id", "session_id", "chat_id"):
            value = str(kwargs.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _resolve_user_id(kwargs: dict[str, Any]) -> str:
        direct = str(kwargs.get("user_id") or "").strip()
        if direct:
            return direct
        uinfo = kwargs.get("user_info")
        if isinstance(uinfo, dict):
            return str(uinfo.get("user_id") or "").strip()
        return ""

    def _session_meta(self, record: SessionRecord) -> dict[str, Any]:
        root = record.root
        raw = (root / "session.toml").read_text(encoding="utf-8")
        try:
            import tomllib
        except ModuleNotFoundError:  # pragma: no cover
            import tomli as tomllib  # type: ignore[no-redef]
        return dict(tomllib.loads(raw))

    def _permission_context(self) -> tuple[list[str], bool]:
        cfg = self.config
        return list(cfg.permissions.admin_qq_ids), bool(cfg.permissions.open_mode)

    def _check(
        self,
        user_id: str,
        action: str,
        record: SessionRecord | None,
        enrolled: set[str],
    ) -> bool:
        admin_ids, open_mode = self._permission_context()
        session = self._session_meta(record) if record is not None else None
        return can(user_id, action, session, admin_ids=admin_ids, open_mode=open_mode, enrolled=enrolled)

    def _coordinator_for(self, stream_id: str, record: SessionRecord) -> TurnCoordinator:
        existing = self._coordinators.get(stream_id)
        if existing is not None:
            return existing
        active, initiative = self._lifecycle().turn_state(record)
        coordinator = TurnCoordinator(debounce_seconds=float(self.config.session.debounce_seconds))
        coordinator.set_active(active)
        coordinator.set_initiative(initiative)
        coordinator.set_flush_callback(
            lambda reason, flushed: self._handle_flush(stream_id, coordinator, reason, flushed)
        )
        self._coordinators[stream_id] = coordinator
        return coordinator

    def _drop_coordinator(self, stream_id: str) -> None:
        self._coordinators.pop(stream_id, None)

    async def _send(self, stream_id: str, text: str) -> None:
        await broadcast_system(self.ctx, stream_id, text, self.config)

    async def _require_active(
        self,
        stream_id: str,
        user_id: str,
        action: str,
    ) -> tuple[SessionRecord | None, LifecycleService, set[str], str | None]:
        if not stream_id:
            return None, self._lifecycle(), set(), "无法识别当前聊天。"
        lifecycle = self._lifecycle()
        record = lifecycle.resolve_active(stream_id)
        if record is None:
            return None, lifecycle, set(), "当前聊天没有进行中的地下城会话。"
        enrolled = lifecycle.enrolled_ids(record)
        if not self._check(user_id, action, record, enrolled):
            return record, lifecycle, enrolled, "你没有权限执行此操作。"
        return record, lifecycle, enrolled, None

    async def _handle_flush(
        self,
        stream_id: str,
        coordinator: TurnCoordinator,
        reason: str,
        flushed: list[Any],
    ) -> None:
        lifecycle = self._lifecycle()
        record = lifecycle.resolve_active(stream_id)
        if record is None or record.status != "running":
            coordinator.complete_processing()
            return
        try:
            result = await run_beat(self.ctx, self, record, flushed, self.config, reason=reason)
            active, initiative = lifecycle.turn_state(record)
            coordinator.set_active(active)
            coordinator.set_initiative(initiative)
            self.ctx.logger.info(
                "地下城节拍完成（%s），beat=%s，收件=%d，掷骰=%d",
                reason,
                result.beat_id,
                result.inbox_count,
                result.roll_count,
            )
        except Exception as exc:
            coordinator.requeue(flushed)
            await self._send(stream_id, f"GM 节拍执行失败：{exc}。收件箱已保留，可稍后 /dnd proceed 重试。")
        finally:
            coordinator.complete_processing()

    async def _opening_beat_stub(self, stream_id: str) -> None:
        await self._send(stream_id, "会话已开始，等待 GM 开场…")

    @Command("dnd_new", description="创建新地下城会话", pattern=r"^/dnd\s+new(?:\s+(?P<title>.+))?\s*$")
    async def cmd_new(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        title = str(kwargs.get("title") or "").strip() or "未命名战役"
        if not self._check(user_id, "new", None, set()):
            await self._send(stream_id, "你没有权限创建会话。")
            return False, "权限不足", 2
        lifecycle = self._lifecycle()
        try:
            record = lifecycle.new(stream_id=stream_id, title=title, creator_id=user_id)
        except ValueError as exc:
            await self._send(stream_id, str(exc))
            return False, str(exc), 2
        await self._send(stream_id, f"已创建会话「{record.title}」（ID: {record.session_id}）。")
        return True, "已创建会话", 1

    @Command("dnd_list", description="列出本聊天的地下城会话", pattern=r"^/dnd\s+list\s*$")
    async def cmd_list(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        lifecycle = self._lifecycle()
        sessions = lifecycle.list_sessions(stream_id)
        if not sessions:
            await self._send(stream_id, "本聊天尚无地下城会话。")
            return True, "无会话", 1
        lines = ["本聊天地下城会话："]
        for item in sessions:
            lines.append(f"- {item.title} [{item.status}] id={item.session_id}")
        await self._send(stream_id, "\n".join(lines))
        return True, "已列出会话", 1

    @Command("dnd_status", description="查看当前会话状态", pattern=r"^/dnd\s+status\s*$")
    async def cmd_status(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        lifecycle = self._lifecycle()
        record = lifecycle.resolve_active(stream_id)
        if record is None:
            await self._send(stream_id, "当前没有活跃会话。")
            return True, "无活跃会话", 1
        enrolled = lifecycle.enrolled_ids(record)
        active, initiative = lifecycle.turn_state(record)
        lines = [
            f"会话：{record.title}",
            f"状态：{record.status}",
            f"创建者：{record.creator_id}",
            f"报名玩家：{', '.join(sorted(enrolled)) or '（无）'}",
            f"当前行动者：{active or '（未设定）'}",
        ]
        if initiative:
            lines.append(f"先攻顺序：{' → '.join(initiative)}")
        await self._send(stream_id, "\n".join(lines))
        return True, "已发送状态", 1

    @Command("dnd_start", description="启动地下城会话", pattern=r"^/dnd\s+start\s*$")
    async def cmd_start(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        record, lifecycle, enrolled, error = await self._require_active(stream_id, user_id, "start")
        if error:
            await self._send(stream_id, error)
            return False, error, 2
        assert record is not None
        missing = lifecycle.start(record, ability_keys=list(self.config.mechanics.ability_scores))
        if missing:
            checklist = "启动前仍需完成：\n" + "\n".join(f"- {item}" for item in missing)
            await self._send(stream_id, checklist)
            return False, "就绪检查未通过", 2
        record = lifecycle.resolve_active(stream_id)
        assert record is not None
        self._coordinator_for(stream_id, record)
        await self._opening_beat_stub(stream_id)
        await self._send(stream_id, "会话已进入进行中状态。")
        return True, "会话已启动", 1

    @Command("dnd_stop", description="停止进行中的地下城会话", pattern=r"^/dnd\s+stop\s*$")
    async def cmd_stop(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        record, lifecycle, enrolled, error = await self._require_active(stream_id, user_id, "stop")
        if error:
            await self._send(stream_id, error)
            return False, error, 2
        assert record is not None
        try:
            lifecycle.stop(record)
        except ValueError as exc:
            await self._send(stream_id, str(exc))
            return False, str(exc), 2
        self._drop_coordinator(stream_id)
        await self._send(stream_id, "会话已停止。")
        return True, "会话已停止", 1

    @Command(
        "dnd_restart",
        description="重启已停止的地下城会话",
        pattern=r"^/dnd\s+restart(?:\s+(?P<session_id>\S+))?\s*$",
    )
    async def cmd_restart(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        lifecycle = self._lifecycle()
        session_id = str(kwargs.get("session_id") or "").strip()
        if session_id:
            record = self._store().load_session(session_id, stream_id=stream_id)
        else:
            record = lifecycle.resolve_active(stream_id)
            if record is None:
                sessions = [item for item in lifecycle.list_sessions(stream_id) if item.status == "stopped"]
                if len(sessions) == 1:
                    record = sessions[0]
        if record is None:
            await self._send(stream_id, "找不到可重启的会话。")
            return False, "无会话", 2
        enrolled = lifecycle.enrolled_ids(record)
        if not self._check(user_id, "restart", record, enrolled):
            await self._send(stream_id, "你没有权限重启此会话。")
            return False, "权限不足", 2
        try:
            lifecycle.restart(record)
        except ValueError as exc:
            await self._send(stream_id, str(exc))
            return False, str(exc), 2
        await self._send(stream_id, f"会话「{record.title}」已重置为 setup，请重新 /dnd review 后 /dnd start。")
        return True, "会话已重启", 1

    @Command(
        "dnd_handoff",
        description="将会话创建者移交给其他玩家",
        pattern=r"^/dnd\s+handoff(?:\s+(?P<target>\S+))?\s*$",
    )
    async def cmd_handoff(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        target = str(kwargs.get("target") or "").strip()
        if not target:
            await self._send(stream_id, "请指定移交对象，例如 /dnd handoff @bob")
            return False, "缺少目标", 2
        record, lifecycle, enrolled, error = await self._require_active(stream_id, user_id, "handoff")
        if error:
            await self._send(stream_id, error)
            return False, error, 2
        assert record is not None
        lifecycle.handoff(record, target)
        await self._send(stream_id, f"会话创建者已移交给 {target}。")
        return True, "已移交", 1

    @Command("dnd_join", description="报名加入当前地下城会话", pattern=r"^/dnd\s+join\s*$")
    async def cmd_join(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        lifecycle = self._lifecycle()
        record = lifecycle.resolve_active(stream_id)
        if record is None:
            await self._send(stream_id, "当前没有可加入的会话。")
            return False, "无会话", 2
        enrolled = lifecycle.enrolled_ids(record)
        if not self._check(user_id, "join", record, enrolled):
            await self._send(stream_id, "你没有权限加入。")
            return False, "权限不足", 2
        if user_id in enrolled:
            await self._send(stream_id, "你已报名本局。")
            return True, "已报名", 1
        lifecycle.join(record, user_id)
        await self._send(stream_id, f"已报名。请完善角色卡 players/{user_id}.yaml 后等待开局。")
        return True, "已报名", 1

    @Command("dnd_leave", description="退出当前地下城会话报名", pattern=r"^/dnd\s+leave\s*$")
    async def cmd_leave(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        record, lifecycle, enrolled, error = await self._require_active(stream_id, user_id, "leave")
        if error:
            await self._send(stream_id, error)
            return False, error, 2
        assert record is not None
        try:
            lifecycle.leave(record, user_id)
        except ValueError as exc:
            await self._send(stream_id, str(exc))
            return False, str(exc), 2
        coordinator = self._coordinators.get(stream_id)
        if coordinator is not None:
            active, initiative = lifecycle.turn_state(record)
            coordinator.set_active(active)
            coordinator.set_initiative(initiative)
        await self._send(stream_id, "已退出本局报名。")
        return True, "已退出", 1

    @Command("dnd_proceed", description="手动推进 GM 节拍", pattern=r"^/dnd\s+proceed\s*$")
    async def cmd_proceed(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        record, lifecycle, enrolled, error = await self._require_active(stream_id, user_id, "proceed")
        if error:
            await self._send(stream_id, error)
            return False, error, 2
        assert record is not None
        if record.status != "running":
            await self._send(stream_id, "仅进行中的会话可推进节拍。")
            return False, "未进行中", 2
        coordinator = self._coordinator_for(stream_id, record)
        flushed = coordinator.request_proceed()
        if flushed is None:
            await self._send(stream_id, "GM 节拍处理中，请稍后再试。")
            return False, "处理中", 2
        await coordinator.dispatch_flush("proceed", flushed)
        await self._send(stream_id, f"已推进节拍（收件 {len(flushed)} 条）。")
        return True, "已推进", 1

    @Command("dnd_turn", description="查看当前回合信息", pattern=r"^/dnd\s+turn\s*$")
    async def cmd_turn(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        record, lifecycle, enrolled, error = await self._require_active(stream_id, user_id, "turn")
        if error:
            await self._send(stream_id, error)
            return False, error, 2
        assert record is not None
        active, initiative = lifecycle.turn_state(record)
        if not active:
            await self._send(stream_id, "当前尚未设定行动者。")
            return True, "无行动者", 1
        lines = [f"当前行动者：{active}"]
        if initiative:
            lines.append(f"先攻顺序：{' → '.join(initiative)}")
        coordinator = self._coordinators.get(stream_id)
        if coordinator is not None:
            pending = coordinator.pending_count
            lines.append(f"待处理消息：{pending} 条")
            if coordinator.processing:
                lines.append("状态：GM 节拍处理中")
            elif coordinator.debounce_scheduled:
                lines.append("状态：活跃玩家发言后防抖计时中")
        await self._send(stream_id, "\n".join(lines))
        return True, "已发送回合信息", 1

    @Command("dnd_skip", description="跳过等待活跃玩家发言", pattern=r"^/dnd\s+skip\s*$")
    async def cmd_skip(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        record, lifecycle, enrolled, error = await self._require_active(stream_id, user_id, "skip")
        if error:
            await self._send(stream_id, error)
            return False, error, 2
        assert record is not None
        if record.status != "running":
            await self._send(stream_id, "仅进行中的会话可跳过等待。")
            return False, "未进行中", 2
        coordinator = self._coordinator_for(stream_id, record)
        flushed = coordinator.request_skip()
        if flushed is None:
            await self._send(stream_id, "GM 节拍处理中，请稍后再试。")
            return False, "处理中", 2
        await coordinator.dispatch_flush("skip", flushed)
        await self._send(stream_id, f"已跳过等待并冲刷节拍（收件 {len(flushed)} 条）。")
        return True, "已跳过", 1

    @Command(
        "dnd_ooc",
        description="发送场外信息到收件箱",
        pattern=r"^/dnd\s+ooc(?:\s+(?P<text>.+))?\s*$",
    )
    async def cmd_ooc(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        text = str(kwargs.get("text") or "").strip()
        if not text:
            await self._send(stream_id, "请附带场外内容，例如 /dnd ooc 我去倒杯水")
            return False, "缺少内容", 2
        record, lifecycle, enrolled, error = await self._require_active(stream_id, user_id, "ooc")
        if error:
            await self._send(stream_id, error)
            return False, error, 2
        assert record is not None
        if record.status != "running":
            await self._send(stream_id, "仅进行中的会话可发送场外信息。")
            return False, "未进行中", 2
        coordinator = self._coordinator_for(stream_id, record)
        coordinator.append({"player_id": user_id, "text": text, "ooc": True})
        await self._send(stream_id, "场外信息已记入收件箱。")
        return True, "已记录 OOC", 1


def create_plugin() -> DndPlugin:
    return DndPlugin()
