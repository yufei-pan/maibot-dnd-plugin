"""GM LLM 输出解析：叙述正文 + ===DND_BEAT_JSON=== 结构化节拍。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

DND_BEAT_JSON_MARKER = "===DND_BEAT_JSON==="


@dataclass(frozen=True)
class GMBeatPayload:
    """GM 节拍结构化载荷。"""

    narration: str
    mechanics: list[dict[str, Any]]
    feedback: list[dict[str, Any]]
    turn_advance: dict[str, Any] | None
    scene_state_patch: str | None
    honored_ids: list[str]


def _require_list(value: Any, field: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"GM 节拍 JSON 字段 {field} 必须是数组")
    return value


def _require_dict_or_none(value: Any, field: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"GM 节拍 JSON 字段 {field} 必须是对象")
    return value


def parse_gm_response(text: str) -> GMBeatPayload:
    """从 GM LLM 输出中解析叙述与节拍 JSON。"""
    raw = str(text or "")
    idx = raw.find(DND_BEAT_JSON_MARKER)
    if idx == -1:
        raise ValueError(f"GM 输出缺少分隔符 {DND_BEAT_JSON_MARKER}")

    preamble = raw[:idx].strip()
    tail = raw[idx + len(DND_BEAT_JSON_MARKER) :].strip()
    if not tail:
        raise ValueError("GM 输出在分隔符后缺少 JSON 正文")

    try:
        payload = json.loads(tail)
    except json.JSONDecodeError as exc:
        raise ValueError(f"GM 节拍 JSON 解析失败: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("GM 节拍 JSON 根节点必须是对象")

    narration = payload.get("narration", "")
    if narration is not None and not isinstance(narration, str):
        raise ValueError("GM 节拍 JSON 字段 narration 必须是字符串")
    narration = str(narration or "").strip()
    if preamble and not narration:
        narration = preamble
    elif preamble and narration:
        narration = f"{preamble}\n\n{narration}"

    mechanics_raw = _require_list(payload.get("mechanics"), "mechanics")
    mechanics: list[dict[str, Any]] = []
    for item in mechanics_raw:
        if not isinstance(item, dict):
            raise ValueError("GM 节拍 JSON 字段 mechanics 的元素必须是对象")
        mechanics.append(dict(item))

    feedback_raw = _require_list(payload.get("feedback"), "feedback")
    feedback: list[dict[str, Any]] = []
    for item in feedback_raw:
        if not isinstance(item, dict):
            raise ValueError("GM 节拍 JSON 字段 feedback 的元素必须是对象")
        feedback.append(dict(item))

    turn_advance = _require_dict_or_none(payload.get("turn_advance"), "turn_advance")

    scene_state_patch = payload.get("scene_state_patch")
    if scene_state_patch is not None and not isinstance(scene_state_patch, str):
        raise ValueError("GM 节拍 JSON 字段 scene_state_patch 必须是字符串")

    honored_raw = payload.get("honored", payload.get("honored_ids"))
    honored_ids: list[str] = []
    if honored_raw is not None:
        if not isinstance(honored_raw, list):
            raise ValueError("GM 节拍 JSON 字段 honored 必须是数组")
        honored_ids = [str(item).strip() for item in honored_raw if str(item).strip()]

    return GMBeatPayload(
        narration=narration,
        mechanics=mechanics,
        feedback=feedback,
        turn_advance=turn_advance,
        scene_state_patch=scene_state_patch,
        honored_ids=honored_ids,
    )
