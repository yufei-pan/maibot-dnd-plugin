from dnd.mechanics.dice import roll_formula
from dnd.mechanics.engine import MechanicsEngine
from dnd.mechanics.sheets import CharacterSheet


def test_roll_d20_plus_mod() -> None:
    r = roll_formula("1d20+5", rng=lambda n, m: 12)
    assert r.total == 17
    assert r.formula == "1d20+5"


def test_advantage_takes_higher() -> None:
    sheet = CharacterSheet(name="A", abilities={"wis": 14}, skills={"perception": 5}, hp_current=10, hp_max=10)
    engine = MechanicsEngine()
    outcome = engine.execute(
        {"kind": "skill_check", "actor": "a1", "skill": "perception", "dc": 13, "advantage": True},
        {"a1": sheet},
        rng=lambda n, m: 10,
    )
    assert outcome.success is True
    assert outcome.roll.total >= 15
