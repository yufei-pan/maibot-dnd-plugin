"""角色卡数据结构（Task 3 最小子集；完整校验见 Task 4）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CharacterSheet:
    """角色卡快照，供 MechanicsEngine 读取加值。"""

    name: str
    abilities: dict[str, int]
    skills: dict[str, int]
    hp_current: int
    hp_max: int
