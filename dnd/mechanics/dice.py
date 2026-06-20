"""骰子公式解析与投掷。"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass

_DICE_RE = re.compile(
    r"^\s*(?P<count>\d+)d(?P<sides>\d+)(?P<mod>[+-]\d+)?\s*$",
    re.IGNORECASE,
)

RollRng = Callable[[int, int], int]


def _default_rng(_count: int, sides: int) -> int:
    return secrets.randbelow(sides) + 1


@dataclass(frozen=True)
class RollResult:
    """一次公式投掷的结果。"""

    dice: list[int]
    modifier: int
    total: int
    formula: str


def roll_formula(formula: str, rng: RollRng | None = None) -> RollResult:
    """解析并投掷 NdM±mod 公式。"""
    match = _DICE_RE.match(formula)
    if match is None:
        raise ValueError(f"无效的骰子公式: {formula!r}")

    count = int(match.group("count"))
    sides = int(match.group("sides"))
    mod_text = match.group("mod")
    modifier = int(mod_text) if mod_text is not None else 0

    if count < 1:
        raise ValueError(f"骰子数量须 ≥1: {formula!r}")
    if sides < 1:
        raise ValueError(f"骰面数须 ≥1: {formula!r}")

    roll = rng if rng is not None else _default_rng
    dice = [roll(1, sides) for _ in range(count)]
    total = sum(dice) + modifier
    return RollResult(dice=dice, modifier=modifier, total=total, formula=formula.strip())
