"""战役与角色卡就绪检查（Review gate A + B）。"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dnd.mechanics.sheets import CharacterSheet

_CAMPAIGN_BIBLE: tuple[tuple[str, str], ...] = (
    ("world", "世界观设定"),
    ("plot-outline", "剧情大纲"),
    ("characters", "角色概览"),
)


def _read_nonempty(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def character_sheet_missing(sheet: CharacterSheet | None, ability_keys: list[str]) -> list[str]:
    """返回角色卡（Gate B）仍缺失的字段说明。"""
    if sheet is None:
        return ["角色卡缺失"]

    missing: list[str] = []
    if not sheet.name.strip():
        missing.append("角色名")

    for key in ability_keys:
        if key not in sheet.abilities:
            missing.append(f"能力值 {key}")

    if sheet.hp_current <= 0 or sheet.hp_max <= 0:
        missing.append("HP（生命值须大于 0）")

    if not sheet.skills:
        missing.append("至少一项技能")

    return missing


def campaign_readiness(session_root: Path) -> list[str]:
    """返回战役圣经（Gate A）仍缺失的条目。"""
    root = Path(session_root)
    missing: list[str] = []

    for stem, label in _CAMPAIGN_BIBLE:
        path = root / "bible" / f"{stem}.md"
        if not path.is_file() or not _read_nonempty(path):
            missing.append(f"{label}（bible/{stem}.md）")

    gm_prompt = root / "gm-prompt.md"
    if not gm_prompt.is_file() or not _read_nonempty(gm_prompt):
        missing.append("GM 补充提示（gm-prompt.md）")

    return missing


def session_readiness(
    session_root: Path,
    enrolled_ids: Iterable[str],
    ability_keys: list[str],
) -> list[str]:
    """合并战役 Gate A 与每位报名玩家的角色卡 Gate B。"""
    root = Path(session_root)
    missing = campaign_readiness(root)

    for player_id in enrolled_ids:
        sheet_path = root / "players" / f"{player_id}.yaml"
        if not sheet_path.is_file():
            missing.append(f"玩家 {player_id} 角色卡（players/{player_id}.yaml）")
            continue

        text = sheet_path.read_text(encoding="utf-8")
        try:
            sheet = CharacterSheet.from_yaml(text)
        except ValueError as exc:
            missing.append(f"玩家 {player_id} 角色卡格式错误：{exc}")
            continue

        for item in character_sheet_missing(sheet, ability_keys):
            missing.append(f"玩家 {player_id}：{item}")

    return missing
