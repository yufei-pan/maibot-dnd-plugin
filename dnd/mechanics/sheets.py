"""角色卡数据结构、YAML 序列化与能力调整值。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml


def ability_modifier(score: int) -> int:
    """D&D 式能力调整值：(score - 10) // 2。"""
    return (score - 10) // 2


def _coerce_int_map(raw: Any, field: str) -> dict[str, int]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{field} 必须是映射")
    result: dict[str, int] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"{field} 键必须是字符串")
        if not isinstance(value, int):
            raise ValueError(f"{field}.{key} 必须是整数")
        result[key] = value
    return result


@dataclass
class CharacterSheet:
    """角色卡快照，供 MechanicsEngine 读取加值。"""

    name: str
    abilities: dict[str, int]
    skills: dict[str, int]
    hp_current: int
    hp_max: int

    @classmethod
    def from_yaml(cls, text: str) -> CharacterSheet:
        """从 YAML 文本解析角色卡。"""
        data = yaml.safe_load(text)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ValueError("角色卡 YAML 根节点必须是映射")

        name = data.get("name", "")
        if name is not None and not isinstance(name, str):
            raise ValueError("name 必须是字符串")

        hp_current = data.get("hp_current", 0)
        hp_max = data.get("hp_max", 0)
        if not isinstance(hp_current, int):
            raise ValueError("hp_current 必须是整数")
        if not isinstance(hp_max, int):
            raise ValueError("hp_max 必须是整数")

        return cls(
            name=str(name),
            abilities=_coerce_int_map(data.get("abilities"), "abilities"),
            skills=_coerce_int_map(data.get("skills"), "skills"),
            hp_current=hp_current,
            hp_max=hp_max,
        )

    def to_yaml(self) -> str:
        """序列化为 YAML 文本。"""
        payload = {
            "name": self.name,
            "abilities": self.abilities,
            "skills": self.skills,
            "hp_current": self.hp_current,
            "hp_max": self.hp_max,
        }
        return yaml.dump(payload, allow_unicode=True, sort_keys=False, default_flow_style=False)
