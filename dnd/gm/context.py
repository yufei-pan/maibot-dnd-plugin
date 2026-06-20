"""GM 节拍 LLM 上下文组装与字符预算裁剪。"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11
    import tomli as tomllib  # type: ignore[no-redef, unused-ignore]

from dnd.config import DndConfig
from dnd.gm.parser import DND_BEAT_JSON_MARKER
from dnd.mechanics.sheets import CharacterSheet
from dnd.store import SessionRecord
from dnd.turn.inbox import InboxMessage

_BASE_GM_SYSTEM = """你是地下城主（GM），负责根据玩家行动推进战役并输出结构化节拍。
规则：
- 所有骰点与数值由插件执行，你只输出 mechanics intent，不要编造骰面或最终数值。
- 叙述使用简体中文，语气沉浸但简洁。
- 必须 honoring 或拒绝偏离回合的行动；honored 列出本节拍采纳的消息 id。
- 回复末尾单独一行输出分隔符 {marker}，随后紧跟一行 JSON，字段：
  narration, mechanics, feedback, honored, turn_advance, scene_state_patch。
- mechanics 为对象数组；feedback 为按玩家定向反馈的对象数组；turn_advance 可为 {{"to": "<player_id>"}}。
"""

_USER_BEAT_PROMPT = "请处理本节拍待处理收件箱，输出叙述与结构化 JSON。"


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _load_session_meta(root: Path) -> dict[str, Any]:
    raw = _read_text(root / "session.toml")
    if not raw.strip():
        return {}
    data = tomllib.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("session.toml 根节点必须是表")
    return data


def _compact_sheet_text(sheet: CharacterSheet) -> str:
    abilities = ", ".join(f"{key}={value}" for key, value in sorted(sheet.abilities.items()))
    skills = ", ".join(f"{key}={value}" for key, value in sorted(sheet.skills.items()))
    return (
        f"- {sheet.name or '（未命名）'}: HP {sheet.hp_current}/{sheet.hp_max}; "
        f"能力 [{abilities}]; 技能 [{skills}]"
    )


def _load_player_snapshots(session_root: Path, enrolled: Iterable[str]) -> str:
    lines: list[str] = []
    for player_id in sorted({str(item).strip() for item in enrolled if str(item).strip()}):
        path = session_root / "players" / f"{player_id}.yaml"
        if not path.is_file():
            lines.append(f"- {player_id}: （角色卡缺失）")
            continue
        try:
            sheet = CharacterSheet.from_yaml(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            lines.append(f"- {player_id}: （角色卡无效：{exc}）")
            continue
        lines.append(f"- {player_id} / {_compact_sheet_text(sheet).lstrip('- ')}")
    return "\n".join(lines)


def _load_turn_summary(meta: Mapping[str, Any]) -> str:
    active = str(meta.get("active_player", "")).strip()
    initiative = meta.get("initiative")
    order: list[str] = []
    if isinstance(initiative, list):
        order = [str(item).strip() for item in initiative if str(item).strip()]
    parts = [f"当前行动玩家：{active or '（未设定）'}"]
    if order:
        parts.append("先攻顺序：" + " → ".join(order))
    return "\n".join(parts)


def _load_bible_excerpt(session_root: Path) -> str:
    chunks: list[str] = []
    for stem, label in (("world", "世界观"), ("plot-outline", "剧情大纲")):
        body = _read_text(session_root / "bible" / f"{stem}.md").strip()
        if body:
            chunks.append(f"【{label}】\n{body}")
    return "\n\n".join(chunks)


def _dictionary_hits(session_root: Path, inbox: Sequence[InboxMessage]) -> str:
    dict_path = session_root / "bible" / "dictionary.json"
    if not dict_path.is_file():
        return ""
    try:
        data = json.loads(dict_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict) or not data:
        return ""

    corpus = "\n".join(msg.text for msg in inbox)
    if not corpus.strip():
        return ""

    hits: list[str] = []
    for term, explanation in sorted(data.items(), key=lambda item: len(str(item[0])), reverse=True):
        term_text = str(term).strip()
        if not term_text:
            continue
        if re.search(re.escape(term_text), corpus, flags=re.IGNORECASE):
            hits.append(f"- {term_text}: {str(explanation).strip()}")
    return "\n".join(hits)


def _load_recent_beats(session_root: Path, limit: int) -> str:
    path = session_root / "journal" / "beats.jsonl"
    if not path.is_file() or limit <= 0:
        return ""

    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return ""

    selected = lines[-limit:]
    rendered: list[str] = []
    for line in selected:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            rendered.append(line)
            continue
        if isinstance(obj, dict):
            narration = str(obj.get("narration", "")).strip()
            if narration:
                rendered.append(narration)
            else:
                rendered.append(json.dumps(obj, ensure_ascii=False))
        else:
            rendered.append(str(obj))
    return "\n---\n".join(rendered)


def _format_inbox(inbox: Sequence[InboxMessage]) -> str:
    if not inbox:
        return "（本节拍无待处理消息）"

    lines: list[str] = []
    for index, msg in enumerate(inbox, start=1):
        tags: list[str] = []
        if msg.is_active:
            tags.append("当前回合")
        if msg.initiative_distance >= 0:
            tags.append(f"先攻距离={msg.initiative_distance}")
        if msg.ooc:
            tags.append("OOC")
        tag_text = f" [{' '.join(tags)}]" if tags else ""
        text = msg.text.strip()
        lines.append(f"m{index}{tag_text} <{msg.player_id}>: {text}")
    return "\n".join(lines)


def _clip_sections(sections: list[tuple[str, str]], budget: int) -> str:
    """按优先级从低至高裁剪上下文段落（列表末尾优先丢弃）。"""
    if budget <= 0:
        return ""

    bodies: list[tuple[str, str]] = []
    for label, body in sections:
        cleaned = (body or "").strip()
        if cleaned:
            bodies.append((label, cleaned))

    if not bodies:
        return ""

    blocks = [f"{label}\n{body}" for label, body in bodies]
    total = sum(len(block) + 2 for block in blocks) - 2
    if total <= budget:
        return "\n\n".join(blocks)

    # 从最低优先级（列表末尾）开始整段移除，最后在最高优先级段内截断。
    kept = list(bodies)
    while len(kept) > 1:
        kept.pop()
        blocks = [f"{label}\n{body}" for label, body in kept]
        total = sum(len(block) + 2 for block in blocks) - 2
        if total <= budget:
            return "\n\n".join(blocks)

    label, body = kept[0]
    block = f"{label}\n{body}"
    if len(block) <= budget:
        return block
    suffix = "……（略）"
    keep_len = max(0, budget - len(suffix))
    return block[:keep_len] + suffix


def build_gm_messages(
    session: SessionRecord,
    inbox: Sequence[InboxMessage],
    config: DndConfig,
) -> list[dict[str, str]]:
    """组装 GM LLM 消息列表，并在字符预算内裁剪上下文。"""
    root = session.root
    meta = _load_session_meta(root)
    enrolled = meta.get("enrolled", [])
    if not isinstance(enrolled, list):
        raise ValueError("session.toml 字段 enrolled 必须是数组")

    gm_prompt = _read_text(root / "gm-prompt.md").strip()
    system_core = _BASE_GM_SYSTEM.format(marker=DND_BEAT_JSON_MARKER)
    if gm_prompt:
        system_core = f"{system_core}\n\n【战役 GM 补充】\n{gm_prompt}"

    scene_state = _read_text(root / "state" / "scene-state.md").strip()
    turn_summary = _load_turn_summary(meta)
    player_snapshots = _load_player_snapshots(root, enrolled)
    if turn_summary:
        player_block = f"{turn_summary}\n{player_snapshots}".strip()
    else:
        player_block = player_snapshots

    sections: list[tuple[str, str]] = [
        ("【GM 系统】", system_core),
        ("【场景状态】", scene_state),
        ("【玩家快照】", player_block),
        ("【设定摘录】", _load_bible_excerpt(root)),
        ("【词典命中】", _dictionary_hits(root, inbox)),
        ("【近期节拍】", _load_recent_beats(root, config.session.recent_beats_limit)),
        ("【待处理收件箱】", _format_inbox(inbox)),
    ]

    budget = max(2000, int(config.session.gm_context_char_budget))
    user_prompt_len = len(_USER_BEAT_PROMPT)
    context_budget = max(0, budget - user_prompt_len - 32)
    context_text = _clip_sections(sections, context_budget)

    return [
        {"role": "system", "content": context_text},
        {"role": "user", "content": _USER_BEAT_PROMPT},
    ]
