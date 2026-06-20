"""Task 10 hooks 辅助函数。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

_SCENE_STATE_PATH = Path("state") / "scene-state.md"
_PLAYERS_DIR = Path("players")


def is_running(status: str) -> bool:
    """判断会话状态是否为 running。"""
    return str(status or "").strip().lower() == "running"


def resolve_stream_id(kwargs: Mapping[str, Any]) -> str:
    """从 Hook/Event 参数中解析 stream_id。"""
    for key in ("stream_id", "session_id", "chat_id"):
        value = str(kwargs.get(key) or "").strip()
        if value:
            return value
    message = kwargs.get("message")
    if isinstance(message, Mapping):
        for key in ("stream_id", "session_id", "chat_id"):
            value = str(message.get(key) or "").strip()
            if value:
                return value
    return ""


def resolve_user_id(kwargs: Mapping[str, Any]) -> str:
    """从 Hook/Event 参数中解析 user_id。"""
    direct = str(kwargs.get("user_id") or "").strip()
    if direct:
        return direct

    user_info = kwargs.get("user_info")
    if isinstance(user_info, Mapping):
        from_info = str(user_info.get("user_id") or "").strip()
        if from_info:
            return from_info

    message = kwargs.get("message")
    if isinstance(message, Mapping):
        message_user_id = str(message.get("user_id") or "").strip()
        if message_user_id:
            return message_user_id
        info = message.get("message_info")
        if isinstance(info, Mapping):
            inner_user_info = info.get("user_info")
            if isinstance(inner_user_info, Mapping):
                nested = str(inner_user_info.get("user_id") or "").strip()
                if nested:
                    return nested
    return ""


def extract_plain_text(message: Any, kwargs: Mapping[str, Any]) -> str:
    """提取消息纯文本。"""
    if isinstance(message, Mapping):
        from_message = str(message.get("plain_text") or "").strip()
        if from_message:
            return from_message
    from_kwargs = str(kwargs.get("plain_text") or "").strip()
    if from_kwargs:
        return from_kwargs
    return ""


def load_scene_brief(session_root: Path) -> str:
    """读取场景状态摘要。"""
    scene_path = Path(session_root) / _SCENE_STATE_PATH
    if not scene_path.is_file():
        return "（暂无场景摘要）"

    lines = scene_path.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].lstrip().startswith("#"):
        lines = lines[1:]
    merged = "\n".join(line.strip() for line in lines if line.strip()).strip()
    return merged or "（暂无场景摘要）"


def load_character_name(session_root: Path, player_id: str) -> str:
    """读取玩家角色名。"""
    fallback = str(player_id or "").strip() or "未知玩家"
    sheet_path = Path(session_root) / _PLAYERS_DIR / f"{fallback}.yaml"
    if not sheet_path.is_file():
        return fallback

    raw = sheet_path.read_text(encoding="utf-8").strip()
    if not raw:
        return fallback

    parsed = yaml.safe_load(raw)
    if parsed is None:
        return fallback
    if not isinstance(parsed, Mapping):
        raise ValueError(f"角色卡格式无效: {sheet_path}")

    name = str(parsed.get("name") or "").strip()
    return name or fallback


def build_player_briefing(character_name: str, scene_brief: str) -> str:
    """生成注入给 MaiBot replyer 的玩家简报。"""
    role_name = str(character_name or "").strip() or "未知角色"
    scene = str(scene_brief or "").strip() or "（暂无场景摘要）"
    return (
        "【地下城玩家简报】\n"
        f"- 你的角色名：{role_name}\n"
        "- 当前会话状态：RUNNING（进行中）\n"
        f"- 场景摘要：\n{scene}\n\n"
        "请仅以玩家身份行动与发言，不要代替 GM 做规则裁定。"
    )
