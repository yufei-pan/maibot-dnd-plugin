"""会话操作权限矩阵（设计 spec § Session administration）。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

LIFECYCLE_ACTIONS = frozenset({"new", "start", "stop", "restart", "handoff", "setup"})
PLAY_ACTIONS = frozenset({"join", "proceed"})
VALID_ACTIONS = LIFECYCLE_ACTIONS | PLAY_ACTIONS

_OPEN_MODE_LIFECYCLE = frozenset({"setup", "start", "stop", "restart", "handoff", "new"})


def _admin_ids_set(admin_ids: Iterable[str]) -> set[str]:
    return {str(item).strip() for item in admin_ids if str(item).strip()}


def _enrolled_set(enrolled: Iterable[str]) -> set[str]:
    return {str(item).strip() for item in enrolled if str(item).strip()}


def _is_config_admin(user_id: str, admin_ids: Iterable[str]) -> bool:
    return user_id in _admin_ids_set(admin_ids)


def _session_creator_id(session: Mapping[str, Any]) -> str:
    return str(session.get("creator_id", "") or "").strip()


def _session_status(session: Mapping[str, Any]) -> str:
    return str(session.get("status", "") or "").strip().lower()


def can(
    user_id: str,
    action: str,
    session: Mapping[str, Any] | None,
    admin_ids: Iterable[str],
    open_mode: bool,
    enrolled: Iterable[str],
) -> bool:
    """判断用户是否可对当前会话执行指定操作。"""
    actor = str(user_id or "").strip()
    if not actor:
        return False

    verb = str(action or "").strip().lower()
    if verb not in VALID_ACTIONS:
        return False

    enrolled_ids = _enrolled_set(enrolled)
    is_enrolled = actor in enrolled_ids

    if verb == "new":
        return True

    if session is None:
        return False

    config_admin = _is_config_admin(actor, admin_ids)
    creator = actor == _session_creator_id(session)
    status = _session_status(session)

    if verb == "proceed":
        return is_enrolled and status == "running"

    if verb == "join":
        return True

    if open_mode and verb in _OPEN_MODE_LIFECYCLE:
        if verb == "stop":
            return status == "running"
        if verb == "restart":
            return status == "stopped"
        return True

    if config_admin:
        if verb in {"setup", "start", "handoff"}:
            return True
        if verb == "stop":
            return status == "running"
        if verb == "restart":
            return status == "stopped"
        return False

    if verb in {"setup", "start"}:
        return creator

    if verb == "stop":
        return status == "running" and (creator or is_enrolled)

    if verb == "restart":
        return status == "stopped" and creator

    if verb == "handoff":
        return creator

    return False
