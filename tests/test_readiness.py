from pathlib import Path

from dnd.mechanics.sheets import CharacterSheet, ability_modifier
from dnd.session.readiness import campaign_readiness, character_sheet_missing, session_readiness

_ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"]


def test_ability_modifier() -> None:
    assert ability_modifier(10) == 0
    assert ability_modifier(14) == 2
    assert ability_modifier(8) == -1


def test_character_sheet_yaml_roundtrip() -> None:
    sheet = CharacterSheet(
        name="Li",
        abilities={"str": 10, "dex": 12},
        skills={"athletics": 2},
        hp_current=8,
        hp_max=10,
    )
    loaded = CharacterSheet.from_yaml(sheet.to_yaml())
    assert loaded == sheet


def test_character_gate_b() -> None:
    ok = CharacterSheet(
        name="Li",
        abilities={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        skills={"athletics": 2},
        hp_current=8,
        hp_max=8,
    )
    assert character_sheet_missing(ok, _ABILITY_KEYS) == []

    bad = CharacterSheet(name="Li", abilities={"str": 10}, skills={}, hp_current=0, hp_max=0)
    assert "HP" in " ".join(character_sheet_missing(bad, _ABILITY_KEYS))


def test_campaign_gate_a(tmp_path: Path) -> None:
    (tmp_path / "bible").mkdir()
    (tmp_path / "bible" / "world.md").write_text("sky islands", encoding="utf-8")
    missing = campaign_readiness(tmp_path)
    assert any("plot-outline" in m for m in missing)


def test_session_readiness_combines_campaign_and_players(tmp_path: Path) -> None:
    (tmp_path / "bible").mkdir()
    (tmp_path / "players").mkdir()
    for stem in ("world", "plot-outline", "characters"):
        (tmp_path / "bible" / f"{stem}.md").write_text(f"{stem} content", encoding="utf-8")
    (tmp_path / "gm-prompt.md").write_text("gm voice", encoding="utf-8")

    good = CharacterSheet(
        name="A",
        abilities=dict.fromkeys(_ABILITY_KEYS, 10),
        skills={"perception": 1},
        hp_current=5,
        hp_max=5,
    )
    (tmp_path / "players" / "p1.yaml").write_text(good.to_yaml(), encoding="utf-8")
    (tmp_path / "players" / "p2.yaml").write_text("name: B\n", encoding="utf-8")

    missing = session_readiness(tmp_path, ["p1", "p2", "p3"], _ABILITY_KEYS)
    assert not any("bible/" in m for m in missing)
    assert any("p2" in m for m in missing)
    assert any("p3" in m for m in missing)
