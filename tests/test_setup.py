from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd.setup import dict_query, dict_set, parse_rulebook_split, write_bible, write_rulebook_topics
from dnd.store import SessionStore


def test_write_bible_replace(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create_session(stream_id="g1", title="Test", creator_id="u1")
    root = record.root

    first = write_bible(root, "world", "sky islands", "replace")
    assert first["success"] is True
    assert (root / "bible" / "world.md").read_text(encoding="utf-8") == "sky islands\n"

    second = write_bible(root, "world", "floating cities", "replace")
    assert second["success"] is True
    assert (root / "bible" / "world.md").read_text(encoding="utf-8") == "floating cities\n"


def test_write_bible_append(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create_session(stream_id="g1", title="Test", creator_id="u1")
    root = record.root

    write_bible(root, "characters", "Hero: Aria", "replace")
    result = write_bible(root, "characters", "Hero: Bob", "append")
    assert result["success"] is True

    body = (root / "bible" / "characters.md").read_text(encoding="utf-8")
    assert body == "Hero: Aria\n\nHero: Bob\n"


def test_write_bible_rejects_empty_content(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create_session(stream_id="g1", title="Test", creator_id="u1")
    root = record.root

    (root / "bible" / "world.md").write_text("keep me", encoding="utf-8")
    result = write_bible(root, "world", "   ", "replace")
    assert result["success"] is False
    assert (root / "bible" / "world.md").read_text(encoding="utf-8") == "keep me"


def test_dictionary_set_and_query(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create_session(stream_id="g1", title="Test", creator_id="u1")
    root = record.root

    set_result = dict_set(root, "Arcane", "魔法相关术语")
    assert set_result["success"] is True

    query_result = dict_query(root, "Arcane")
    assert query_result["success"] is True
    assert query_result["content"] == "Arcane: 魔法相关术语"

    all_result = dict_query(root)
    assert all_result["success"] is True
    assert "Arcane: 魔法相关术语" in all_result["content"]

    data = json.loads((root / "bible" / "dictionary.json").read_text(encoding="utf-8"))
    assert data["Arcane"] == "魔法相关术语"


def test_parse_rulebook_split_and_write_topics(tmp_path: Path) -> None:
    response = (
        "已拆分。\n"
        "===DND_RULEBOOK_JSON===\n"
        '{"combat-rules": "## 战斗\\n先攻", "spells": "## 法术\\n环位"}'
    )
    topics = parse_rulebook_split(response)
    assert topics["combat-rules"].startswith("## 战斗")
    assert "环位" in topics["spells"]

    written = write_rulebook_topics(tmp_path, topics)
    assert written == ["combat-rules", "spells"]
    assert (tmp_path / "bible" / "rules" / "combat-rules.md").is_file()
    assert (tmp_path / "bible" / "rules" / "spells.md").is_file()


def test_parse_rulebook_split_missing_marker() -> None:
    with pytest.raises(ValueError, match="===DND_RULEBOOK_JSON==="):
        parse_rulebook_split('{"combat": "x"}')
