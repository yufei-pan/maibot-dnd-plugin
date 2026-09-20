"""GM beat 管线：LLM、解析、执行、播报与落盘。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from dnd.broadcast import broadcast_gm, wake_mai_turn
from dnd.config import DndConfig
from dnd.gm.context import build_gm_messages
from dnd.gm.parser import DND_BEAT_JSON_MARKER, GMBeatPayload, parse_gm_response
from dnd.llm_route import host_generate
from dnd.mechanics.engine import MechanicsEngine, MechanicsOutcome
from dnd.mechanics.items import execute_spawn_item, execute_use_item
from dnd.mechanics.sheets import CharacterSheet
from dnd.store import SessionRecord, SessionStore
from dnd.turn.inbox import InboxMessage

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef, unused-ignore]

import tomli_w


@dataclass(frozen=True)
class BeatResult:
    """单次 GM beat 执行结果。"""

    beat_id: str
    inbox_count: int
    honored_ids: list[str]
    roll_count: int
    active_player: str
    narration: str


@dataclass(frozen=True)
class ExecutionResult:
    """结构化 payload 的执行结果。"""

    mechanics_results: list[dict[str, Any]]
    roll_entries: list[dict[str, Any]]
    roll_lines: list[str]
    feedback_lines: list[str]


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_session_meta(root: Path) -> dict[str, Any]:
    raw = (root / "session.toml").read_text(encoding="utf-8")
    data = tomllib.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("session.toml 根节点必须是表")
    return dict(data)


def _write_session_meta(root: Path, meta: dict[str, Any]) -> None:
    SessionStore.write_text(root / "session.toml", tomli_w.dumps(meta))


def _load_sheet_map(session_root: Path, enrolled: list[str]) -> dict[str, CharacterSheet]:
    result: dict[str, CharacterSheet] = {}
    for player_id in enrolled:
        pid = str(player_id).strip()
        if not pid:
            continue
        path = session_root / "players" / f"{pid}.yaml"
        if not path.is_file():
            continue
        result[pid] = CharacterSheet.from_yaml(path.read_text(encoding="utf-8"))
    return result


def _format_roll_line(entry: dict[str, Any]) -> str:
    if entry["kind"] == "skill_check":
        return (
            f"- 检定 {entry['actor']} / {entry['skill']}: 掷骰 {entry['formula']} "
            f"=> {entry['total']} (DC {entry['dc']}, {'成功' if entry['success'] else '失败'})"
        )
    if entry["kind"] == "use_item_heal":
        return (
            f"- 物品 {entry['actor']} 使用 {entry['item_id']}: 掷骰 {entry['formula']} "
            f"=> 治疗 {entry['healed']}，HP {entry['hp_before']}→{entry['hp_after']}"
        )
    return f"- 掷骰 {entry.get('formula', '未知')} => {entry.get('total', '?')}"


def _feedback_lines(feedback: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in feedback:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        visibility = str(item.get("visibility") or "").strip()
        player_id = str(item.get("player_id") or item.get("actor") or "").strip()
        if visibility == "direct" and player_id:
            lines.append(f"- 对 {player_id}：{text}")
        else:
            lines.append(f"- {text}")
    return lines


def _turn_advance(meta: dict[str, Any], turn_advance: dict[str, Any] | None) -> str:
    active = str(meta.get("active_player") or "").strip()
    if turn_advance is None:
        return active

    to_player = str(turn_advance.get("to") or "").strip()
    if to_player:
        active = to_player
        initiative = meta.get("initiative")
        if isinstance(initiative, list):
            normalized = [str(item).strip() for item in initiative if str(item).strip()]
            if to_player not in normalized:
                normalized.append(to_player)
            meta["initiative"] = normalized
        meta["active_player"] = to_player
    return active


def _merge_scene_state(session_root: Path, scene_state_patch: str | None) -> None:
    if scene_state_patch is None:
        return
    patch = scene_state_patch.strip()
    if not patch:
        return
    path = session_root / "state" / "scene-state.md"
    current = path.read_text(encoding="utf-8").rstrip()
    merged = f"{current}\n\n## 节拍更新 {_now_iso()}\n{patch}\n"
    SessionStore.write_text(path, merged)


def _write_turn_yaml(session_root: Path, active_player: str, initiative: list[str], reason: str) -> None:
    payload = {
        "updated_at": _now_iso(),
        "active_player": active_player,
        "initiative": initiative,
        "reason": reason,
    }
    SessionStore.write_text(
        session_root / "state" / "turn.yaml",
        yaml.dump(payload, allow_unicode=True, sort_keys=False, default_flow_style=False),
    )


async def _call_gm_once(ctx: Any, messages: list[dict[str, str]], model: str) -> str:
    result = await host_generate(ctx.llm, messages, model)
    if not isinstance(result, dict):
        raise ValueError("GM 模型返回值无效")
    if not bool(result.get("success")):
        raise ValueError(str(result.get("error") or "GM 模型生成失败"))
    text = str(result.get("response") or "").strip()
    if not text:
        raise ValueError("GM 模型返回空响应")
    return text


async def _llm_payload(ctx: Any, session: SessionRecord, inbox: list[InboxMessage], config: DndConfig) -> GMBeatPayload:
    messages = build_gm_messages(session, inbox, config)
    model = str(config.session.gm_model).strip()
    if not model:
        raise ValueError("未配置 session.gm_model")

    first = await _call_gm_once(ctx, messages, model)
    try:
        return parse_gm_response(first)
    except ValueError as first_exc:
        repair_messages = [
            *messages,
            {"role": "assistant", "content": first},
            {
                "role": "user",
                "content": (
                    "上次输出无法解析，请严格按如下格式重写：\n"
                    f"1) 正文叙述\n2) 单独一行 {DND_BEAT_JSON_MARKER}\n3) 下一行为合法 JSON。"
                    f"\n解析错误：{first_exc}"
                ),
            },
        ]
        second = await _call_gm_once(ctx, repair_messages, model)
        return parse_gm_response(second)


def _execute_payload(session: SessionRecord, payload: GMBeatPayload) -> ExecutionResult:
    meta = _load_session_meta(session.root)
    enrolled_raw = meta.get("enrolled", [])
    if not isinstance(enrolled_raw, list):
        raise ValueError("session.toml 字段 enrolled 必须是数组")
    enrolled = [str(item).strip() for item in enrolled_raw if str(item).strip()]
    sheets = _load_sheet_map(session.root, enrolled)
    engine = MechanicsEngine()

    mechanics_results: list[dict[str, Any]] = []
    roll_entries: list[dict[str, Any]] = []
    roll_lines: list[str] = []
    for intent in payload.mechanics:
        kind = str(intent.get("kind") or "").strip()
        if kind == "skill_check":
            outcome: MechanicsOutcome = engine.execute(intent, sheets)
            outcome_dict = {
                "kind": outcome.kind,
                "actor": outcome.actor,
                "skill": outcome.skill,
                "dc": outcome.dc,
                "success": outcome.success,
                "formula": outcome.roll.formula,
                "total": outcome.roll.total,
                "dice": list(outcome.roll.dice),
                "modifier": outcome.roll.modifier,
            }
            mechanics_results.append(outcome_dict)
            roll_entry = {
                "kind": "skill_check",
                "actor": outcome.actor,
                "skill": outcome.skill,
                "dc": outcome.dc,
                "success": bool(outcome.success),
                "formula": outcome.roll.formula,
                "total": outcome.roll.total,
                "dice": list(outcome.roll.dice),
                "modifier": outcome.roll.modifier,
            }
            roll_entries.append(roll_entry)
            roll_lines.append(_format_roll_line(roll_entry))
            continue

        if kind == "use_item":
            result, roll = execute_use_item(session.root, intent)
            mechanics_results.append(result)
            if roll is not None:
                hp_before = int(result["hp_current"]) - int(result["healed"])
                roll_entry = {
                    "kind": "use_item_heal",
                    "actor": result["actor"],
                    "item_id": result["item_id"],
                    "formula": roll.formula,
                    "total": roll.total,
                    "dice": list(roll.dice),
                    "modifier": roll.modifier,
                    "healed": int(result["healed"]),
                    "hp_before": hp_before,
                    "hp_after": int(result["hp_current"]),
                }
                roll_entries.append(roll_entry)
                roll_lines.append(_format_roll_line(roll_entry))
            continue

        if kind == "spawn_item":
            result = execute_spawn_item(session.root, intent)
            mechanics_results.append(result)
            continue

        raise ValueError(f"不支持的 mechanics kind: {kind}")

    return ExecutionResult(
        mechanics_results=mechanics_results,
        roll_entries=roll_entries,
        roll_lines=roll_lines,
        feedback_lines=_feedback_lines(payload.feedback),
    )


def _append_rolls(session: SessionRecord, beat_id: str, rolls: list[dict[str, Any]]) -> None:
    path = session.root / "journal" / "rolls.jsonl"
    for entry in rolls:
        SessionStore.append_jsonl(path, {"ts": _now_iso(), "beat_id": beat_id, **entry})


def _append_beat(
    session: SessionRecord,
    beat_id: str,
    payload: GMBeatPayload,
    execution: ExecutionResult,
    inbox: list[InboxMessage],
    reason: str,
    active_player: str,
) -> None:
    beat_record = {
        "ts": _now_iso(),
        "beat_id": beat_id,
        "reason": reason,
        "honored_ids": list(payload.honored_ids),
        "active_player": active_player,
        "narration": payload.narration,
        "feedback": payload.feedback,
        "mechanics": payload.mechanics,
        "execution": execution.mechanics_results,
        "inbox": [asdict(item) for item in inbox],
    }
    SessionStore.append_jsonl(session.root / "journal" / "beats.jsonl", beat_record)


async def run_beat(
    ctx: Any,
    plugin_instance: Any,
    session: SessionRecord,
    inbox: list[InboxMessage],
    config: DndConfig,
    *,
    reason: str = "proceed",
) -> BeatResult:
    """执行一次完整 GM beat。"""
    payload = await _llm_payload(ctx, session, inbox, config)
    execution = _execute_payload(session, payload)

    meta = _load_session_meta(session.root)
    active_player = _turn_advance(meta, payload.turn_advance)
    initiative_raw = meta.get("initiative", [])
    if not isinstance(initiative_raw, list):
        raise ValueError("session.toml 字段 initiative 必须是数组")
    initiative = [str(item).strip() for item in initiative_raw if str(item).strip()]
    _write_session_meta(session.root, meta)
    _write_turn_yaml(session.root, active_player, initiative, reason)
    _merge_scene_state(session.root, payload.scene_state_patch)

    beat_id = datetime.now().astimezone().strftime("%Y%m%d%H%M%S%f")
    _append_rolls(session, beat_id, execution.roll_entries)
    _append_beat(session, beat_id, payload, execution, inbox, reason, active_player)

    message_parts: list[str] = []
    narration = payload.narration.strip()
    if narration:
        message_parts.append(narration)
    if execution.roll_lines:
        message_parts.append("检定结果：\n" + "\n".join(execution.roll_lines))
    if execution.feedback_lines:
        message_parts.append("反馈：\n" + "\n".join(execution.feedback_lines))
    await broadcast_gm(ctx, session.stream_id, "\n\n".join(message_parts).strip(), config)

    bot_person_id = await _resolve_plugin_bot_person_id(plugin_instance, session.stream_id)
    if bot_person_id and active_player == bot_person_id:
        await wake_mai_turn(
            ctx,
            session.stream_id,
            "轮到麦麦行动，请继续剧情。",
            "dnd_player_turn",
            "active_player_changed",
            {"session_id": session.session_id, "active_player": active_player},
            config,
        )

    return BeatResult(
        beat_id=beat_id,
        inbox_count=len(inbox),
        honored_ids=list(payload.honored_ids),
        roll_count=len(execution.roll_entries),
        active_player=active_player,
        narration=payload.narration,
    )


async def _resolve_plugin_bot_person_id(plugin_instance: Any, stream_id: str) -> str:
    """解析当前聊天流的麦麦 person_id，并兼容旧测试替身与插件实例。"""

    resolver = getattr(plugin_instance, "_get_mai_person_id", None)
    if callable(resolver):
        resolved = str(await resolver(stream_id) or "").strip()
        if resolved:
            return resolved
    return str(getattr(plugin_instance, "_mai_person_id", "") or "").strip()
