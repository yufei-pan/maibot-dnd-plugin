"""地下城 (MaiBot D&D) 插件。"""

from __future__ import annotations

import sys
from pathlib import Path

# Host 仅将 plugins/ 父目录加入 sys.path；本子包位于插件目录内，须显式加入以便 import dnd.*
_PLUGIN_DIR = Path(__file__).resolve().parent
_plugin_dir_str = str(_PLUGIN_DIR)
if _plugin_dir_str not in sys.path:
    sys.path.insert(0, _plugin_dir_str)

from typing import Any

import httpx
from maibot_sdk import Command, EventHandler, HookHandler, MaiBotPlugin, Tool
from maibot_sdk.types import EventType, HookMode, ToolParameterInfo, ToolParamType

from dnd import play as dnd_play
from dnd import setup as dnd_setup
from dnd.broadcast import broadcast_system
from dnd.config import CURRENT_CONFIG_VERSION, DndConfig, _normalize_dnd_config
from dnd.gm.broker import run_beat
from dnd.hooks import (
    build_player_briefing,
    extract_plain_text,
    is_running,
    load_character_name,
    load_scene_brief,
    resolve_stream_id,
    resolve_user_id,
)
from dnd.render import (
    build_card_html,
    build_card_markdown,
    load_character_sheet,
    load_template,
    render_card,
)
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
        await self._resolve_mai_person_id()
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
        return resolve_stream_id(kwargs)

    @staticmethod
    def _resolve_user_id(kwargs: dict[str, Any]) -> str:
        return resolve_user_id(kwargs)

    def _resolve_running_session(self, stream_id: str) -> tuple[LifecycleService, SessionRecord | None]:
        lifecycle = self._lifecycle()
        record = lifecycle.resolve_active(stream_id)
        if record is None or not is_running(record.status):
            return lifecycle, None
        return lifecycle, record

    def _append_inbox_message(self, *, stream_id: str, player_id: str, text: str, ooc: bool = False) -> None:
        lifecycle, record = self._resolve_running_session(stream_id)
        if record is None:
            return

        enrolled = lifecycle.enrolled_ids(record)
        if player_id not in enrolled:
            return

        coordinator = self._coordinator_for(stream_id, record)
        coordinator.append({"player_id": player_id, "text": text, "ooc": ooc})
        active_player, _ = lifecycle.turn_state(record)
        if active_player == player_id:
            coordinator.on_active_player_message(player_id)

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

    def _lifecycle_actor_kwargs(self, user_id: str) -> dict[str, Any]:
        admin_ids, open_mode = self._permission_context()
        return {"actor_id": user_id, "admin_ids": admin_ids, "open_mode": open_mode}

    async def _resolve_mai_person_id(self) -> None:
        override = str(self.config.session.maibot_person_id or "").strip()
        if override:
            self._mai_person_id = override
            return
        qq_account = await self.ctx.config.get("bot.qq_account", "")
        if not qq_account:
            self.ctx.logger.warning("地下城：未配置 bot.qq_account，无法解析麦麦 person_id")
            return
        person_id = await self.ctx.person.get_id("qq", str(qq_account))
        if not person_id:
            self.ctx.logger.warning("地下城：无法解析麦麦 person_id（qq=%s）", qq_account)
            return
        self._mai_person_id = str(person_id)
        self.ctx.logger.info("地下城：麦麦 person_id=%s", self._mai_person_id)

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

    async def _require_setup(
        self,
        stream_id: str,
        user_id: str,
    ) -> tuple[SessionRecord | None, LifecycleService, set[str], str | None]:
        return await self._require_active(stream_id, user_id, "setup")

    async def _tool_setup_session(
        self,
        kwargs: dict[str, Any],
    ) -> tuple[SessionRecord | None, str | None]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        record, _, _, error = await self._require_setup(stream_id, user_id)
        if error:
            return None, error
        assert record is not None
        return record, None

    async def _tool_play_session(
        self,
        kwargs: dict[str, Any],
        *,
        require_running: bool = False,
    ) -> tuple[SessionRecord | None, str | None]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        lifecycle = self._lifecycle()
        record = lifecycle.resolve_active(stream_id)
        if record is None:
            return None, "当前聊天没有进行中的地下城会话。"
        enrolled = lifecycle.enrolled_ids(record)
        if user_id and user_id not in enrolled:
            return None, "你尚未报名本局。"
        if require_running and record.status != "running":
            return None, "仅进行中的会话可执行此操作。"
        return record, None

    async def _dispatch_proceed(self, stream_id: str, record: SessionRecord) -> tuple[bool, str, int]:
        if record.status != "running":
            return False, "仅进行中的会话可推进节拍。", 2
        coordinator = self._coordinator_for(stream_id, record)
        flushed = coordinator.request_proceed()
        if flushed is None:
            return False, "GM 节拍处理中，请稍后再试。", 2
        await coordinator.dispatch_flush("proceed", flushed)
        return True, f"已推进节拍（收件 {len(flushed)} 条）。", 1

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
        admin_ids, open_mode = self._permission_context()
        result = lifecycle.new(
            stream_id=stream_id,
            title=title,
            creator_id=user_id,
            admin_ids=admin_ids,
            open_mode=open_mode,
        )
        if not result.ok:
            await self._send(stream_id, result.message)
            return False, result.message, 2
        await self._send(stream_id, result.message)
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
        result = lifecycle.start(
            stream_id=stream_id,
            ability_keys=list(self.config.mechanics.ability_scores),
            **self._lifecycle_actor_kwargs(user_id),
        )
        if not result.ok:
            await self._send(stream_id, result.message)
            return False, "就绪检查未通过", 2
        record = result.session
        assert record is not None
        self._coordinator_for(stream_id, record)
        await self._opening_beat_stub(stream_id)
        await self._send(stream_id, result.message)
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
        result = lifecycle.stop(stream_id=stream_id, **self._lifecycle_actor_kwargs(user_id))
        if not result.ok:
            await self._send(stream_id, result.message)
            return False, result.message, 2
        self._drop_coordinator(stream_id)
        await self._send(stream_id, result.message)
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
        result = lifecycle.restart(
            stream_id=stream_id,
            session_id=record.session_id,
            **self._lifecycle_actor_kwargs(user_id),
        )
        if not result.ok:
            await self._send(stream_id, result.message)
            return False, result.message, 2
        await self._send(stream_id, result.message)
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
        result = lifecycle.handoff(
            stream_id=stream_id,
            new_creator_id=target,
            **self._lifecycle_actor_kwargs(user_id),
        )
        if not result.ok:
            await self._send(stream_id, result.message)
            return False, result.message, 2
        await self._send(stream_id, result.message)
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
        ok, message, code = await self._dispatch_proceed(stream_id, record)
        await self._send(stream_id, message)
        return ok, message, code

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

    @Tool(
        "dnd_setup_bible",
        brief_description="【地下城·筹备】写入/追加战役圣经 bible/<topic>.md（world、plot-outline、characters 等）。",
        parameters=[
            ToolParameterInfo(name="topic", param_type=ToolParamType.STRING, required=True, description="设定主题，如 world / plot-outline / characters"),
            ToolParameterInfo(name="content", param_type=ToolParamType.STRING, required=True, description="设定内容（Markdown）"),
            ToolParameterInfo(
                name="mode",
                param_type=ToolParamType.STRING,
                required=False,
                default="append",
                enum_values=["append", "replace"],
                description="追加或覆盖",
            ),
        ],
    )
    async def tool_setup_bible(
        self,
        topic: str = "",
        content: str = "",
        mode: str = "append",
        **kwargs: Any,
    ) -> dict[str, Any]:
        record, error = await self._tool_setup_session(kwargs)
        if error:
            return {"success": False, "content": error}
        assert record is not None
        body = dnd_setup._coalesce_text(content, kwargs, "text", "body", "markdown")
        return dnd_setup.write_bible(record.root, topic, body, mode)

    @Tool(
        "dnd_setup_gm_prompt",
        brief_description="【地下城·筹备】写入/追加 GM 补充提示 gm-prompt.md。",
        parameters=[
            ToolParameterInfo(name="content", param_type=ToolParamType.STRING, required=True, description="GM 补充提示（Markdown）"),
            ToolParameterInfo(
                name="mode",
                param_type=ToolParamType.STRING,
                required=False,
                default="replace",
                enum_values=["append", "replace"],
                description="追加或覆盖",
            ),
        ],
    )
    async def tool_setup_gm_prompt(self, content: str = "", mode: str = "replace", **kwargs: Any) -> dict[str, Any]:
        record, error = await self._tool_setup_session(kwargs)
        if error:
            return {"success": False, "content": error}
        assert record is not None
        body = dnd_setup._coalesce_text(content, kwargs, "text", "body", "markdown", "prompt")
        return dnd_setup.write_gm_prompt(record.root, body, mode)

    @Tool(
        "dnd_setup_character",
        brief_description="【地下城·筹备】写入玩家角色卡 players/<player_id>.yaml。",
        parameters=[
            ToolParameterInfo(name="player_id", param_type=ToolParamType.STRING, required=True, description="玩家 ID"),
            ToolParameterInfo(name="content", param_type=ToolParamType.STRING, required=True, description="角色卡 YAML 正文"),
            ToolParameterInfo(
                name="mode",
                param_type=ToolParamType.STRING,
                required=False,
                default="replace",
                enum_values=["append", "replace"],
                description="覆盖或合并字段（append 时合并 YAML 映射）",
            ),
        ],
    )
    async def tool_setup_character(
        self,
        player_id: str = "",
        content: str = "",
        mode: str = "replace",
        **kwargs: Any,
    ) -> dict[str, Any]:
        record, error = await self._tool_setup_session(kwargs)
        if error:
            return {"success": False, "content": error}
        assert record is not None
        body = dnd_setup._coalesce_text(content, kwargs, "yaml", "text", "body", "sheet")
        return dnd_setup.write_character_sheet(record.root, player_id, body, mode)

    @Tool(
        "dnd_import_rulebook",
        brief_description="【地下城·筹备】从 URL 抓取规则书，经 LLM 拆分写入 bible/rules/<topic>.md。",
        parameters=[
            ToolParameterInfo(name="url", param_type=ToolParamType.STRING, required=True, description="规则书 URL"),
        ],
    )
    async def tool_import_rulebook(self, url: str = "", **kwargs: Any) -> dict[str, Any]:
        record, error = await self._tool_setup_session(kwargs)
        if error:
            return {"success": False, "content": error}
        assert record is not None
        target_url = dnd_setup._coalesce_text(url, kwargs, "link", "source")
        try:
            return await dnd_setup.import_rulebook(
                self.ctx.llm.generate,
                record.root,
                target_url,
                max_bytes=int(self.config.session.rulebook_import_max_bytes),
                model=str(self.config.session.gm_model),
            )
        except (ValueError, httpx.HTTPError) as exc:
            return {"success": False, "content": str(exc)}

    @Tool(
        "dnd_dict_set",
        brief_description="【地下城·筹备】写入战役词典 bible/dictionary.json 词条。",
        parameters=[
            ToolParameterInfo(name="term", param_type=ToolParamType.STRING, required=True, description="词条"),
            ToolParameterInfo(name="explanation", param_type=ToolParamType.STRING, required=True, description="解释"),
        ],
    )
    async def tool_dict_set(self, term: str = "", explanation: str = "", **kwargs: Any) -> dict[str, Any]:
        record, error = await self._tool_setup_session(kwargs)
        if error:
            return {"success": False, "content": error}
        assert record is not None
        key = dnd_setup._coalesce_text(term, kwargs, "word", "name")
        value = dnd_setup._coalesce_text(explanation, kwargs, "definition", "text", "meaning")
        return dnd_setup.dict_set(record.root, key, value)

    @Tool(
        "dnd_dict_query",
        brief_description="【地下城·筹备/查询】查询战役词典；term 留空时列出全部词条。",
        parameters=[
            ToolParameterInfo(name="term", param_type=ToolParamType.STRING, required=False, default="", description="词条；留空列出全部"),
        ],
    )
    async def tool_dict_query(self, term: str = "", **kwargs: Any) -> dict[str, Any]:
        stream_id = self._resolve_stream_id(kwargs)
        lifecycle = self._lifecycle()
        record = lifecycle.resolve_active(stream_id)
        if record is None:
            return {"success": False, "content": "当前聊天没有进行中的地下城会话。"}
        query = dnd_setup._coalesce_text(term, kwargs, "word", "name")
        return dnd_setup.dict_query(record.root, query)

    @Tool(
        "dnd_review_ready",
        brief_description="【地下城·筹备】检查战役圣经、GM 提示与报名玩家角色卡是否满足开跑条件。",
        parameters=[],
    )
    async def tool_review_ready(self, **kwargs: Any) -> dict[str, Any]:
        record, error = await self._tool_setup_session(kwargs)
        if error:
            return {"success": False, "content": error}
        assert record is not None
        lifecycle = self._lifecycle()
        enrolled = sorted(lifecycle.enrolled_ids(record))
        return dnd_setup.review_ready(record.root, enrolled, list(self.config.mechanics.ability_scores))

    @Tool(
        "dnd_spawn_item",
        brief_description="【地下城·筹备】生成物品到玩家背包或场景（state/scene-items.yaml）。",
        parameters=[
            ToolParameterInfo(name="item", param_type=ToolParamType.OBJECT, required=True, description="物品对象，至少含 id"),
            ToolParameterInfo(name="give_to", param_type=ToolParamType.STRING, required=False, default="", description="给予的玩家 ID；留空则放入场景"),
        ],
    )
    async def tool_spawn_item(self, item: Any = None, give_to: str = "", **kwargs: Any) -> dict[str, Any]:
        record, error = await self._tool_setup_session(kwargs)
        if error:
            return {"success": False, "content": error}
        assert record is not None
        payload = item if isinstance(item, dict) else kwargs.get("item")
        if not isinstance(payload, dict):
            return {"success": False, "content": "请提供 item 对象。"}
        target = dnd_setup._coalesce_text(give_to, kwargs, "player_id", "actor")
        return dnd_setup.spawn_item(record.root, payload, target)

    @Command(
        "dnd_bible",
        description="写入/追加战役圣经",
        pattern=r"^/dnd\s+bible(?:\s+(?P<mode>append|replace))?\s+(?P<topic>\S+)\s+(?P<content>.+)\s*$",
    )
    async def cmd_bible(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        record, error = await self._require_setup(stream_id, user_id)
        if error:
            await self._send(stream_id, error)
            return False, error, 2
        assert record is not None
        topic = str(kwargs.get("topic") or "").strip()
        content = str(kwargs.get("content") or "").strip()
        mode = str(kwargs.get("mode") or "append").strip().lower()
        result = dnd_setup.write_bible(record.root, topic, content, mode)
        await self._send(stream_id, str(result["content"]))
        return bool(result["success"]), str(result["content"]), 1 if result["success"] else 2

    @Command(
        "dnd_gm_prompt",
        description="写入/追加 GM 补充提示",
        pattern=r"^/dnd\s+gm-prompt(?:\s+(?P<mode>append|replace))?\s+(?P<content>.+)\s*$",
    )
    async def cmd_gm_prompt(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        record, error = await self._require_setup(stream_id, user_id)
        if error:
            await self._send(stream_id, error)
            return False, error, 2
        assert record is not None
        content = str(kwargs.get("content") or "").strip()
        mode = str(kwargs.get("mode") or "replace").strip().lower()
        result = dnd_setup.write_gm_prompt(record.root, content, mode)
        await self._send(stream_id, str(result["content"]))
        return bool(result["success"]), str(result["content"]), 1 if result["success"] else 2

    @Command("dnd_review", description="检查战役就绪状态", pattern=r"^/dnd\s+review\s*$")
    async def cmd_review(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        record, lifecycle, enrolled, error = await self._require_setup(stream_id, user_id)
        if error:
            await self._send(stream_id, error)
            return False, error, 2
        assert record is not None
        result = dnd_setup.review_ready(record.root, sorted(enrolled), list(self.config.mechanics.ability_scores))
        await self._send(stream_id, str(result["content"]))
        return bool(result["success"]), str(result["content"]), 1

    @Command(
        "dnd_import_rules",
        description="从 URL 导入规则书",
        pattern=r"^/dnd\s+import-rules\s+(?P<url>\S+)\s*$",
    )
    async def cmd_import_rules(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        record, error = await self._require_setup(stream_id, user_id)
        if error:
            await self._send(stream_id, error)
            return False, error, 2
        assert record is not None
        url = str(kwargs.get("url") or "").strip()
        try:
            result = await dnd_setup.import_rulebook(
                self.ctx.llm.generate,
                record.root,
                url,
                max_bytes=int(self.config.session.rulebook_import_max_bytes),
                model=str(self.config.session.gm_model),
            )
        except (ValueError, httpx.HTTPError) as exc:
            message = str(exc)
            await self._send(stream_id, message)
            return False, message, 2
        await self._send(stream_id, str(result["content"]))
        return bool(result["success"]), str(result["content"]), 1 if result["success"] else 2

    @Command(
        "dnd_dict_set",
        description="写入战役词典词条",
        pattern=r"^/dnd\s+dict\s+set\s+(?P<term>\S+)\s+(?P<explanation>.+)\s*$",
    )
    async def cmd_dict_set(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        record, error = await self._require_setup(stream_id, user_id)
        if error:
            await self._send(stream_id, error)
            return False, error, 2
        assert record is not None
        term = str(kwargs.get("term") or "").strip()
        explanation = str(kwargs.get("explanation") or "").strip()
        result = dnd_setup.dict_set(record.root, term, explanation)
        await self._send(stream_id, str(result["content"]))
        return bool(result["success"]), str(result["content"]), 1 if result["success"] else 2

    @Command(
        "dnd_dict",
        description="查询战役词典",
        pattern=r"^/dnd\s+dict(?:\s+(?P<term>\S+))?\s*$",
    )
    async def cmd_dict(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        lifecycle = self._lifecycle()
        record = lifecycle.resolve_active(stream_id)
        if record is None:
            await self._send(stream_id, "当前聊天没有进行中的地下城会话。")
            return False, "无会话", 2
        term = str(kwargs.get("term") or "").strip()
        result = dnd_setup.dict_query(record.root, term)
        await self._send(stream_id, str(result["content"]))
        return bool(result["success"]), str(result["content"]), 1 if result["success"] else 2

    @Command(
        "dnd_card",
        description="查看角色卡（PNG 或 Markdown 回退）",
        pattern=r"^/dnd\s+card(?:\s+(?P<target>\S+))?\s*$",
    )
    async def cmd_card(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        lifecycle = self._lifecycle()
        record = lifecycle.resolve_active(stream_id)
        if record is None:
            await self._send(stream_id, "当前聊天没有进行中的地下城会话。")
            return False, "无会话", 2

        target = str(kwargs.get("target") or "").strip() or user_id
        try:
            sheet, mugshot_path = load_character_sheet(record.root, target)
        except FileNotFoundError as exc:
            await self._send(stream_id, str(exc))
            return False, str(exc), 2

        template = load_template(self._plugin_dir, "character_card.html")
        fragment = build_card_html(
            template,
            sheet,
            session_root=record.root,
            mugshot_path=mugshot_path,
            player_id=target,
        )
        image_b64 = await render_card(self.ctx, fragment)
        if image_b64:
            await self.ctx.send.image(image_b64, stream_id)
            return True, "已发送角色卡图片", 1

        markdown = build_card_markdown(sheet, player_id=target)
        await self._send(
            stream_id,
            "（图片渲染暂不可用，先用文字版角色卡。Host 浏览器环境就绪后即可出图。）\n\n" + markdown,
        )
        return True, "已发送文字版角色卡", 1

    @Command(
        "dnd_sheet",
        description="查看角色卡 YAML",
        pattern=r"^/dnd\s+sheet(?:\s+(?P<player_id>\S+))?\s*$",
    )
    async def cmd_sheet(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        lifecycle = self._lifecycle()
        record = lifecycle.resolve_active(stream_id)
        if record is None:
            await self._send(stream_id, "当前聊天没有进行中的地下城会话。")
            return False, "无会话", 2
        target = str(kwargs.get("player_id") or user_id).strip()
        result = dnd_play.format_sheet(record.root, target)
        await self._send(stream_id, str(result["content"]))
        return bool(result["success"]), str(result["content"]), 1 if result["success"] else 2

    @Command(
        "dnd_roll",
        description="掷骰或技能检定",
        pattern=r"^/dnd\s+roll(?:\s+(?P<formula>.+))?\s*$",
    )
    async def cmd_roll(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        user_id = self._resolve_user_id(kwargs)
        record, error = await self._tool_play_session(kwargs)
        if error:
            await self._send(stream_id, error)
            return False, error, 2
        assert record is not None
        formula = str(kwargs.get("formula") or "").strip()
        result = dnd_play.execute_roll(record.root, user_id, formula=formula)
        await self._send(stream_id, str(result["content"]))
        return bool(result["success"]), str(result["content"]), 1 if result["success"] else 2

    @Command("dnd_log", description="查看掷骰记录", pattern=r"^/dnd\s+log\s*$")
    async def cmd_log(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        record, error = await self._tool_play_session(kwargs)
        if error:
            await self._send(stream_id, error)
            return False, error, 2
        assert record is not None
        result = dnd_play.query_log(record.root, limit=int(self.config.session.recent_beats_limit))
        await self._send(stream_id, str(result["content"]))
        return bool(result["success"]), str(result["content"]), 1

    @Command(
        "dnd_map",
        description="查看战役地图",
        pattern=r"^/dnd\s+map(?:\s+(?P<name>\S+))?\s*$",
    )
    async def cmd_map(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = self._resolve_stream_id(kwargs)
        lifecycle = self._lifecycle()
        record = lifecycle.resolve_active(stream_id)
        if record is None:
            await self._send(stream_id, "当前聊天没有进行中的地下城会话。")
            return False, "无会话", 2
        name = str(kwargs.get("name") or "").strip()
        result = dnd_play.query_map(record.root, name)
        await self._send(stream_id, str(result["content"]))
        return bool(result["success"]), str(result["content"]), 1 if result["success"] else 2

    @Tool(
        "dnd_proceed",
        brief_description="【地下城·进行中】手动推进 GM 节拍。",
        parameters=[],
    )
    async def tool_proceed(self, **kwargs: Any) -> dict[str, Any]:
        record, error = await self._tool_play_session(kwargs, require_running=True)
        if error:
            return {"success": False, "content": error}
        assert record is not None
        stream_id = self._resolve_stream_id(kwargs)
        ok, message, _ = await self._dispatch_proceed(stream_id, record)
        return {"success": ok, "content": message}

    @Tool(
        "dnd_query_bible",
        brief_description="【地下城·查询】检索战役圣经主题；topic 留空时列出可用主题。",
        parameters=[
            ToolParameterInfo(
                name="topic",
                param_type=ToolParamType.STRING,
                required=False,
                default="",
                description="设定主题，如 world / plot-outline / combat-rules",
            ),
        ],
    )
    async def tool_query_bible(self, topic: str = "", **kwargs: Any) -> dict[str, Any]:
        record, error = await self._tool_play_session(kwargs)
        if error:
            return {"success": False, "content": error}
        assert record is not None
        query = dnd_setup._coalesce_text(topic, kwargs, "subject", "name")
        return dnd_play.query_bible(record.root, query)

    @Tool(
        "dnd_query_log",
        brief_description="【地下城·查询】查看最近掷骰记录。",
        parameters=[
            ToolParameterInfo(
                name="limit",
                param_type=ToolParamType.INTEGER,
                required=False,
                default=20,
                description="返回条目数上限",
            ),
        ],
    )
    async def tool_query_log(self, limit: int = 20, **kwargs: Any) -> dict[str, Any]:
        record, error = await self._tool_play_session(kwargs)
        if error:
            return {"success": False, "content": error}
        assert record is not None
        try:
            return dnd_play.query_log(record.root, limit=int(limit))
        except ValueError as exc:
            return {"success": False, "content": str(exc)}

    @Tool(
        "dnd_roll",
        brief_description="【地下城·进行中】掷骰或技能检定。",
        parameters=[
            ToolParameterInfo(
                name="formula",
                param_type=ToolParamType.STRING,
                required=False,
                default="",
                description="骰子公式，如 1d20+3",
            ),
            ToolParameterInfo(
                name="skill",
                param_type=ToolParamType.STRING,
                required=False,
                default="",
                description="技能名（与 dc 联用作检定）",
            ),
            ToolParameterInfo(
                name="dc",
                param_type=ToolParamType.INTEGER,
                required=False,
                default=0,
                description="技能检定 DC",
            ),
            ToolParameterInfo(
                name="advantage",
                param_type=ToolParamType.BOOLEAN,
                required=False,
                default=False,
                description="优势",
            ),
            ToolParameterInfo(
                name="disadvantage",
                param_type=ToolParamType.BOOLEAN,
                required=False,
                default=False,
                description="劣势",
            ),
        ],
    )
    async def tool_roll(
        self,
        formula: str = "",
        skill: str = "",
        dc: int = 0,
        advantage: bool = False,
        disadvantage: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        record, error = await self._tool_play_session(kwargs)
        if error:
            return {"success": False, "content": error}
        assert record is not None
        user_id = self._resolve_user_id(kwargs)
        formula_text = dnd_setup._coalesce_text(formula, kwargs, "dice", "expression")
        skill_name = dnd_setup._coalesce_text(skill, kwargs, "skill_name")
        dc_value = kwargs.get("dc", dc)
        parsed_dc: int | None
        if skill_name:
            if dc_value in (None, "", 0):
                parsed_dc = None
            else:
                parsed_dc = int(dc_value)
        else:
            parsed_dc = None
        return dnd_play.execute_roll(
            record.root,
            user_id,
            formula=formula_text,
            skill=skill_name,
            dc=parsed_dc,
            advantage=bool(kwargs.get("advantage", advantage)),
            disadvantage=bool(kwargs.get("disadvantage", disadvantage)),
        )

    @HookHandler("maisaka.replyer.after_response", mode=HookMode.BLOCKING)
    async def hook_capture_mai_reply(self, **kwargs: Any) -> dict[str, Any]:
        """捕获 MaiBot 回复并写入 DND 回合收件箱。"""
        stream_id = resolve_stream_id(kwargs)
        if not stream_id:
            return {"action": "continue"}

        bot_person_id = str(self._mai_person_id or "").strip()
        if not bot_person_id:
            return {"action": "continue"}

        lifecycle, record = self._resolve_running_session(stream_id)
        if record is None:
            return {"action": "continue"}
        if bot_person_id not in lifecycle.enrolled_ids(record):
            return {"action": "continue"}

        response = str(kwargs.get("response") or "").strip()
        if not response:
            return {"action": "continue"}

        self._append_inbox_message(stream_id=stream_id, player_id=bot_person_id, text=response)
        return {"action": "continue"}

    @HookHandler("maisaka.replyer.before_model_request", mode=HookMode.BLOCKING)
    async def hook_inject_mai_player_briefing(self, **kwargs: Any) -> dict[str, Any]:
        """在 MaiBot replyer 请求模型前注入玩家简报。"""
        stream_id = resolve_stream_id(kwargs)
        if not stream_id:
            return {"action": "continue"}

        bot_person_id = str(self._mai_person_id or "").strip()
        if not bot_person_id:
            return {"action": "continue"}

        lifecycle, record = self._resolve_running_session(stream_id)
        if record is None:
            return {"action": "continue"}
        if bot_person_id not in lifecycle.enrolled_ids(record):
            return {"action": "continue"}

        messages = kwargs.get("messages")
        if not isinstance(messages, list):
            return {"action": "continue"}

        character_name = load_character_name(record.root, bot_person_id)
        scene_brief = load_scene_brief(record.root)
        briefing = build_player_briefing(character_name, scene_brief)

        insert_at = 0
        for index, item in enumerate(messages):
            if isinstance(item, dict) and item.get("role") == "system":
                insert_at = index + 1
        messages.insert(insert_at, {"role": "user", "content": briefing})
        kwargs["messages"] = messages
        return {"action": "continue", "modified_kwargs": kwargs}

    @EventHandler("dnd_capture_enrolled_human_message", event_type=EventType.ON_MESSAGE)
    async def event_capture_enrolled_human_message(self, message: Any = None, **kwargs: Any) -> None:
        """捕获进行中会话里报名人类玩家发言并写入 inbox。"""
        payload: dict[str, Any] = dict(kwargs)
        if message is not None:
            payload["message"] = message

        stream_id = resolve_stream_id(payload)
        if not stream_id:
            return None

        user_id = resolve_user_id(payload)
        if not user_id:
            return None

        bot_person_id = str(self._mai_person_id or "").strip()
        if bot_person_id and user_id == bot_person_id:
            return None

        text = extract_plain_text(message, payload)
        if not text or text.startswith("/dnd"):
            return None

        self._append_inbox_message(stream_id=stream_id, player_id=user_id, text=text)
        return None


def create_plugin() -> DndPlugin:
    return DndPlugin()
