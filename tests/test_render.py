from pathlib import Path

import pytest

from dnd.mechanics.sheets import CharacterSheet
from dnd.render import (
    build_card_html,
    build_card_markdown,
    build_map_html,
    load_character_sheet,
    load_template,
)


@pytest.fixture
def card_template(plugin_dir: Path) -> str:
    return load_template(plugin_dir, "character_card.html")


@pytest.fixture
def map_template(plugin_dir: Path) -> str:
    return load_template(plugin_dir, "map.html")


@pytest.fixture
def plugin_dir() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_sheet() -> CharacterSheet:
    return CharacterSheet(
        name="艾莉丝",
        abilities={"str": 10, "dex": 14, "con": 12, "int": 10, "wis": 12, "cha": 10},
        skills={"stealth": 5, "perception": 3},
        hp_current=8,
        hp_max=10,
    )


def test_build_card_html_contains_name_and_hp(card_template: str, sample_sheet: CharacterSheet) -> None:
    html = build_card_html(card_template, sample_sheet, player_id="p1")
    assert "艾莉丝" in html
    assert "8/10" in html
    assert "stealth" in html
    assert "p1" in html


def test_build_card_html_shows_ability_modifiers(card_template: str, sample_sheet: CharacterSheet) -> None:
    html = build_card_html(card_template, sample_sheet)
    assert "14 (+2)" in html
    assert "10 (+0)" in html


def test_build_card_markdown_contains_name_and_hp(sample_sheet: CharacterSheet) -> None:
    markdown = build_card_markdown(sample_sheet, player_id="p1")
    assert "艾莉丝" in markdown
    assert "8/10" in markdown
    assert "stealth" in markdown


def test_build_map_html_contains_title_and_body(map_template: str) -> None:
    html = build_map_html(
        map_template,
        title="地下城一层",
        body="入口在北，走廊通向中央大厅。",
        legend_items=["■ 已探索", "□ 未探索"],
    )
    assert "地下城一层" in html
    assert "入口在北" in html
    assert "已探索" in html


def test_load_character_sheet_with_mugshot(tmp_path: Path) -> None:
    players = tmp_path / "players"
    players.mkdir()
    (players / "alice.yaml").write_text(
        "\n".join(
            [
                "name: 艾莉丝",
                "abilities: {str: 10, dex: 14, con: 12, int: 10, wis: 12, cha: 10}",
                "skills: {stealth: 5}",
                "hp_current: 8",
                "hp_max: 10",
                "mugshot: assets/mugshot.png",
            ]
        ),
        encoding="utf-8",
    )

    sheet, mugshot = load_character_sheet(tmp_path, "alice")
    assert sheet.name == "艾莉丝"
    assert sheet.hp_current == 8
    assert mugshot == "assets/mugshot.png"


def test_build_card_html_embeds_mugshot_when_file_exists(
    card_template: str,
    sample_sheet: CharacterSheet,
    tmp_path: Path,
) -> None:
    mug_dir = tmp_path / "assets"
    mug_dir.mkdir()
    mug_path = mug_dir / "mugshot.png"
    mug_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    html = build_card_html(
        card_template,
        sample_sheet,
        session_root=tmp_path,
        mugshot_path="assets/mugshot.png",
    )
    assert "data:image/png;base64," in html
    assert 'class="mugshot"' in html
