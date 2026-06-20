"""进行中查询与掷骰服务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dnd.gm.broker import _format_roll_line
from dnd.mechanics.dice import RollRng, roll_formula
from dnd.mechanics.engine import MechanicsEngine
from dnd.mechanics.sheets import CharacterSheet
from dnd.setup import _normalize_topic, _read_text


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        data = json.loads(stripped)
        if isinstance(data, dict):
            entries.append(data)
    return entries


def _resolve_bible_path(session_root: Path, topic: str) -> Path | None:
    topic_name = _normalize_topic(topic)
    if not topic_name:
        return None

    direct = session_root / "bible" / f"{topic_name}.md"
    if direct.is_file():
        return direct

    rules = session_root / "bible" / "rules" / f"{topic_name}.md"
    if rules.is_file():
        return rules
    return None


def query_bible(session_root: Path, topic: str) -> dict[str, Any]:
    """读取 bible/<topic>.md 或 bible/rules/<topic>.md。"""
    query = str(topic or "").strip()
    if not query:
        topics: list[str] = []
        bible_dir = session_root / "bible"
        if bible_dir.is_dir():
            for path in sorted(bible_dir.glob("*.md")):
                topics.append(path.stem)
        rules_dir = bible_dir / "rules"
        if rules_dir.is_dir():
            for path in sorted(rules_dir.glob("*.md")):
                topics.append(f"rules/{path.stem}")
        if not topics:
            return {"success": True, "content": "战役圣经尚无可用主题。"}
        return {"success": True, "content": "可用主题：\n" + "\n".join(f"- {item}" for item in topics)}

    path = _resolve_bible_path(session_root, query)
    if path is None:
        return {"success": False, "content": f"未找到设定主题「{query}」。"}

    body = _read_text(path).strip()
    if not body:
        return {"success": False, "content": f"设定主题「{query}」存在但内容为空。"}
    return {"success": True, "content": body}


def query_log(session_root: Path, *, limit: int = 20) -> dict[str, Any]:
    """读取 journal/rolls.jsonl 最近条目。"""
    if limit < 1:
        raise ValueError("limit 须 ≥1")

    entries = _read_jsonl(session_root / "journal" / "rolls.jsonl")
    if not entries:
        return {"success": True, "content": "尚无掷骰记录。"}

    tail = entries[-limit:]
    lines = [_format_roll_line(entry) for entry in tail]
    return {"success": True, "content": "\n".join(lines)}


def _load_player_sheet(session_root: Path, player_id: str) -> CharacterSheet:
    path = session_root / "players" / f"{player_id}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"未找到玩家 {player_id} 的角色卡。")
    return CharacterSheet.from_yaml(path.read_text(encoding="utf-8"))


def format_sheet(session_root: Path, player_id: str) -> dict[str, Any]:
    """返回玩家角色卡 YAML 文本。"""
    pid = str(player_id or "").strip()
    if not pid:
        return {"success": False, "content": "请提供玩家 ID。"}

    path = session_root / "players" / f"{pid}.yaml"
    if not path.is_file():
        return {"success": False, "content": f"未找到玩家 {pid} 的角色卡。"}

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {"success": False, "content": f"玩家 {pid} 的角色卡为空。"}
    return {"success": True, "content": text}


def query_map(session_root: Path, map_name: str = "") -> dict[str, Any]:
    """列出或读取地图 Markdown（渲染由 Task 13 提供）。"""
    maps_dir = session_root / "bible" / "maps"
    name = _normalize_topic(map_name)

    if not name:
        if not maps_dir.is_dir():
            return {"success": True, "content": "尚无地图文件。"}
        names = sorted(path.stem for path in maps_dir.glob("*.md"))
        if not names:
            return {"success": True, "content": "尚无地图文件。"}
        return {"success": True, "content": "可用地图：\n" + "\n".join(f"- {item}" for item in names)}

    path = maps_dir / f"{name}.md"
    if not path.is_file():
        return {"success": False, "content": f"未找到地图「{name}」。"}

    body = _read_text(path).strip()
    if not body:
        return {"success": False, "content": f"地图「{name}」存在但内容为空。"}

    meta_path = maps_dir / f"{name}.meta.yaml"
    meta_note = ""
    if meta_path.is_file():
        meta_note = f"\n\n元数据（{name}.meta.yaml）：\n{meta_path.read_text(encoding='utf-8').strip()}"

    return {
        "success": True,
        "content": f"【地图·{name}】\n{body}{meta_note}\n\n（地图 PNG 渲染尚未就绪。）",
    }


def execute_roll(
    session_root: Path,
    player_id: str,
    *,
    formula: str = "",
    skill: str = "",
    dc: int | None = None,
    advantage: bool = False,
    disadvantage: bool = False,
    rng: RollRng | None = None,
) -> dict[str, Any]:
    """执行自由掷骰或技能检定。"""
    pid = str(player_id or "").strip()
    skill_name = str(skill or "").strip()
    formula_text = str(formula or "").strip()

    if skill_name:
        if not pid:
            return {"success": False, "content": "技能检定需要 actor（玩家 ID）。"}
        if dc is None:
            return {"success": False, "content": "技能检定需要 dc。"}

        try:
            sheet = _load_player_sheet(session_root, pid)
        except FileNotFoundError as exc:
            return {"success": False, "content": str(exc)}
        except ValueError as exc:
            return {"success": False, "content": f"角色卡无效：{exc}"}

        engine = MechanicsEngine()
        try:
            outcome = engine.execute(
                {
                    "kind": "skill_check",
                    "actor": pid,
                    "skill": skill_name,
                    "dc": int(dc),
                    "advantage": bool(advantage),
                    "disadvantage": bool(disadvantage),
                },
                {pid: sheet},
                rng=rng,
            )
        except (KeyError, ValueError) as exc:
            return {"success": False, "content": str(exc)}

        verdict = "成功" if outcome.success else "失败"
        return {
            "success": True,
            "content": (
                f"检定 {pid} / {skill_name}：{outcome.roll.formula} => {outcome.roll.total} "
                f"(DC {outcome.dc}, {verdict})"
            ),
            "total": outcome.roll.total,
            "success_check": outcome.success,
        }

    if not formula_text:
        return {"success": False, "content": "请提供 formula（如 1d20+3）或 skill + dc。"}

    try:
        result = roll_formula(formula_text, rng=rng)
    except ValueError as exc:
        return {"success": False, "content": str(exc)}

    dice_text = ", ".join(str(value) for value in result.dice)
    mod_sign = "+" if result.modifier >= 0 else ""
    return {
        "success": True,
        "content": f"掷骰 {result.formula}：[{dice_text}]{mod_sign}{result.modifier} => {result.total}",
        "total": result.total,
    }
