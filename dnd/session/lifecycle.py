"""会话生命周期：创建、列表、开跑、停止、重启与 creator 移交。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from dnd.session.permissions import can
from dnd.session.readiness import session_readiness
from dnd.store import SessionRecord, SessionStore


@dataclass(frozen=True)
class LifecycleResult:
    """生命周期操作结果。"""

    ok: bool
    message: str
    session: SessionRecord | None = None
    checklist: list[str] | None = None


def format_readiness_checklist(missing: list[str]) -> str:
    """将会话就绪缺失项格式化为用户可见清单。"""
    if not missing:
        return ""
    lines = ["尚未满足开跑条件，请先完成以下项："]
    for item in missing:
        lines.append(f"· {item}")
    return "\n".join(lines)


class LifecycleService:
    """基于 SessionStore 的会话生命周期服务。"""

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def new(
        self,
        *,
        stream_id: str,
        title: str,
        creator_id: str,
        admin_ids: list[str],
        open_mode: bool,
    ) -> LifecycleResult:
        active = self._store.find_active_session(stream_id)
        if active is not None:
            return LifecycleResult(
                ok=False,
                message=f"本聊天已有进行中的会话「{active.title}」（{active.session_id}），请先 /dnd stop 或 /dnd restart。",
                session=active,
            )

        if not can(creator_id, "new", None, admin_ids, open_mode, set()):
            return LifecycleResult(ok=False, message="无权创建新会话。")

        clean_title = title.strip() or "未命名战役"
        record = self._store.create_session(stream_id=stream_id, title=clean_title, creator_id=creator_id)
        return LifecycleResult(
            ok=True,
            message=f"已创建战役「{record.title}」（ID: {record.session_id}）。请完善圣经与角色卡后 /dnd start。",
            session=record,
        )

    def list_sessions(self, stream_id: str) -> list[SessionRecord]:
        return self._store.list_sessions(stream_id)

    def resolve_active(self, stream_id: str) -> SessionRecord | None:
        return self._store.find_active_session(stream_id)

    def enrolled_ids(self, record: SessionRecord) -> set[str]:
        return self._store.load_enrolled(record.session_id, stream_id=record.stream_id)

    def join(self, record: SessionRecord, user_id: str) -> None:
        self._store.add_enrolled(record.session_id, stream_id=record.stream_id, user_id=user_id)

    def leave(self, record: SessionRecord, user_id: str) -> None:
        self._store.remove_enrolled(record.session_id, stream_id=record.stream_id, user_id=user_id)

    def status_text(self, stream_id: str) -> str:
        active = self._store.find_active_session(stream_id)
        if active is None:
            stopped = [rec for rec in self._store.list_sessions(stream_id) if rec.status == "stopped"]
            if not stopped:
                return "本聊天暂无地下城会话。使用 /dnd new <标题> 创建。"
            lines = ["本聊天暂无进行中的会话。", "", "已停止的会话："]
            for rec in stopped:
                lines.append(f"· {rec.title} [{rec.session_id}] — {rec.status}")
            return "\n".join(lines)

        enrolled = self._store.load_enrolled(active.session_id, stream_id=stream_id)
        lines = [
            f"战役：{active.title}",
            f"ID：{active.session_id}",
            f"状态：{active.status}",
            f"创建者：{active.creator_id}",
            f"已报名：{len(enrolled)} 人",
        ]
        if enrolled:
            lines.append("玩家：" + "、".join(sorted(enrolled)))
        active_player, initiative = self._store.load_turn_state(active.session_id, stream_id=stream_id)
        if active_player:
            lines.append(f"当前行动玩家：{active_player}")
        if initiative:
            lines.append("先攻顺序：" + " → ".join(initiative))
        return "\n".join(lines)

    def start(
        self,
        *,
        stream_id: str,
        actor_id: str,
        admin_ids: list[str],
        open_mode: bool,
        ability_keys: list[str],
    ) -> LifecycleResult:
        active = self._store.find_active_session(stream_id)
        if active is None:
            return LifecycleResult(ok=False, message="本聊天没有可开跑的会话。请先 /dnd new。")

        enrolled = self._store.load_enrolled(active.session_id, stream_id=stream_id)
        session_meta = self._session_meta(active, enrolled)
        if not can(actor_id, "start", session_meta, admin_ids, open_mode, enrolled):
            return LifecycleResult(ok=False, message="无权开跑此会话。")

        if active.status == "running":
            return LifecycleResult(ok=False, message="会话已在进行中。", session=active)

        if active.status == "stopped":
            return LifecycleResult(
                ok=False,
                message=f"会话已停止，请使用 /dnd restart {active.session_id}。",
                session=active,
            )

        missing = session_readiness(active.root, enrolled, ability_keys)
        if missing:
            return LifecycleResult(
                ok=False,
                message=format_readiness_checklist(missing),
                session=active,
                checklist=missing,
            )

        updated = self._store.ensure_turn_state(active.session_id, stream_id=stream_id, enrolled=enrolled)
        return LifecycleResult(
            ok=True,
            message=f"战役「{updated.title}」已开跑！（开场 GM 节拍将在后续任务接入）",
            session=updated,
        )

    def stop(
        self,
        *,
        stream_id: str,
        actor_id: str,
        admin_ids: list[str],
        open_mode: bool,
    ) -> LifecycleResult:
        active = self._store.find_active_session(stream_id)
        if active is None:
            return LifecycleResult(ok=False, message="本聊天没有进行中的会话。")

        enrolled = self._store.load_enrolled(active.session_id, stream_id=stream_id)
        session_meta = self._session_meta(active, enrolled)
        if not can(actor_id, "stop", session_meta, admin_ids, open_mode, enrolled):
            return LifecycleResult(ok=False, message="无权停止此会话。")

        if active.status != "running":
            return LifecycleResult(ok=False, message=f"会话当前为「{active.status}」，仅运行中可停止。", session=active)

        updated = self._store.update_status(active.session_id, stream_id=stream_id, status="stopped")
        return LifecycleResult(
            ok=True,
            message=f"战役「{updated.title}」已停止。可用 /dnd restart {updated.session_id} 重新准备。",
            session=updated,
        )

    def restart(
        self,
        *,
        stream_id: str,
        session_id: str,
        actor_id: str,
        admin_ids: list[str],
        open_mode: bool,
    ) -> LifecycleResult:
        active = self._store.find_active_session(stream_id)
        if active is not None and active.session_id != session_id:
            return LifecycleResult(
                ok=False,
                message=f"本聊天已有进行中的会话「{active.title}」（{active.session_id}），请先停止后再重启其他会话。",
                session=active,
            )

        try:
            record = self._store.load_session(session_id, stream_id=stream_id)
        except (FileNotFoundError, OSError, KeyError, ValueError) as exc:
            return LifecycleResult(ok=False, message=f"未找到会话 {session_id}：{exc}")

        enrolled = self._store.load_enrolled(session_id, stream_id=stream_id)
        session_meta = self._session_meta(record, enrolled)
        if not can(actor_id, "restart", session_meta, admin_ids, open_mode, enrolled):
            return LifecycleResult(ok=False, message="无权重启此会话。")

        if record.status != "stopped":
            return LifecycleResult(
                ok=False,
                message=f"会话「{record.title}」当前为「{record.status}」，仅已停止的会话可重启。",
                session=record,
            )

        updated = self._store.update_status(session_id, stream_id=stream_id, status="setup")
        return LifecycleResult(
            ok=True,
            message=f"战役「{updated.title}」已回到准备阶段，请重新 /dnd review 后 /dnd start。",
            session=updated,
        )

    def handoff(
        self,
        *,
        stream_id: str,
        new_creator_id: str,
        actor_id: str,
        admin_ids: list[str],
        open_mode: bool,
    ) -> LifecycleResult:
        active = self._store.find_active_session(stream_id)
        if active is None:
            return LifecycleResult(ok=False, message="本聊天没有可移交的会话。")

        target = new_creator_id.strip()
        if not target:
            return LifecycleResult(ok=False, message="请指定移交对象，例如：/dnd handoff @bob")

        enrolled = self._store.load_enrolled(active.session_id, stream_id=stream_id)
        session_meta = self._session_meta(active, enrolled)
        if not can(actor_id, "handoff", session_meta, admin_ids, open_mode, enrolled):
            return LifecycleResult(ok=False, message="无权移交 creator。")

        if target == active.creator_id:
            return LifecycleResult(ok=False, message="对方已是当前 creator。", session=active)

        updated = self._store.update_creator(active.session_id, stream_id=stream_id, creator_id=target)
        return LifecycleResult(
            ok=True,
            message=f"creator 已移交给 {target}。",
            session=updated,
        )

    def turn_state(self, record: SessionRecord) -> tuple[str, list[str]]:
        return self._store.load_turn_state(record.session_id, stream_id=record.stream_id)

    def set_turn_state(
        self,
        record: SessionRecord,
        *,
        active_player: str,
        initiative: Iterable[str] | None = None,
    ) -> None:
        self._store.save_turn_state(
            record.session_id,
            stream_id=record.stream_id,
            active_player=active_player,
            initiative=initiative,
        )

    @staticmethod
    def _session_meta(record: SessionRecord, enrolled: set[str]) -> dict[str, Any]:
        return {
            "session_id": record.session_id,
            "stream_id": record.stream_id,
            "title": record.title,
            "creator_id": record.creator_id,
            "status": record.status,
            "enrolled": sorted(enrolled),
        }
