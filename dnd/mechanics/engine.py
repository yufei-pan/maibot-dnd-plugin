"""纯 Python 判定引擎。"""

from __future__ import annotations

from dataclasses import dataclass

from dnd.mechanics.dice import RollRng, RollResult, roll_formula
from dnd.mechanics.sheets import CharacterSheet


@dataclass(frozen=True)
class MechanicsOutcome:
    """单次 mechanics intent 的执行结果。"""

    kind: str
    actor: str
    success: bool | None
    roll: RollResult
    dc: int | None = None
    skill: str | None = None


class MechanicsEngine:
    """执行 GM 下发的 mechanics intent。"""

    def execute(
        self,
        intent: dict,
        sheets: dict[str, CharacterSheet],
        *,
        rng: RollRng | None = None,
    ) -> MechanicsOutcome:
        kind = intent["kind"]
        if kind == "skill_check":
            return self._skill_check(intent, sheets, rng=rng)
        raise ValueError(f"不支持的 mechanics kind: {kind!r}")

    def _skill_check(
        self,
        intent: dict,
        sheets: dict[str, CharacterSheet],
        *,
        rng: RollRng | None,
    ) -> MechanicsOutcome:
        actor = intent["actor"]
        skill = intent["skill"]
        dc = int(intent["dc"])
        advantage = bool(intent.get("advantage", False))
        disadvantage = bool(intent.get("disadvantage", False))

        if advantage and disadvantage:
            advantage = False
            disadvantage = False

        sheet = sheets[actor]
        if skill not in sheet.skills:
            raise KeyError(f"角色 {actor!r} 缺少技能 {skill!r}")

        modifier = sheet.skills[skill]
        roll = self._d20_check(modifier, advantage, disadvantage, rng=rng)

        return MechanicsOutcome(
            kind="skill_check",
            actor=actor,
            success=roll.total >= dc,
            roll=roll,
            dc=dc,
            skill=skill,
        )

    def _d20_check(
        self,
        modifier: int,
        advantage: bool,
        disadvantage: bool,
        *,
        rng: RollRng | None,
    ) -> RollResult:
        if advantage or disadvantage:
            first = roll_formula("1d20", rng=rng)
            second = roll_formula("1d20", rng=rng)
            if advantage:
                chosen = max(first.dice[0], second.dice[0])
            else:
                chosen = min(first.dice[0], second.dice[0])
            dice = [first.dice[0], second.dice[0], chosen]
            total = chosen + modifier
            sign = "+" if modifier >= 0 else ""
            formula = f"2d20{'kh1' if advantage else 'kl1'}{sign}{modifier}"
            return RollResult(dice=dice, modifier=modifier, total=total, formula=formula)

        base = roll_formula("1d20", rng=rng)
        total = base.dice[0] + modifier
        sign = "+" if modifier >= 0 else ""
        formula = f"1d20{sign}{modifier}"
        return RollResult(dice=base.dice, modifier=modifier, total=total, formula=formula)
