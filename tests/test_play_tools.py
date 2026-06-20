"""Play 查询与掷骰工具离线测试。"""

from __future__ import annotations

from pathlib import Path

import yaml

from dnd.mechanics.sheets import CharacterSheet
from dnd.play import execute_roll, query_bible, query_log
from dnd.store import SessionStore


def _write_player(path: Path) -> None:
    sheet = CharacterSheet(
        name="艾莉丝",
        abilities={"str": 10, "dex": 14, "con": 12, "int": 10, "wis": 12, "cha": 10},
        skills={"perception": 5},
        hp_current=8,
        hp_max=10,
    )
    path.write_text(sheet.to_yaml(), encoding="utf-8")


def test_execute_roll_formula_offline(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create_session(stream_id="g1", title="测试", creator_id="u1")
    result = execute_roll(record.root, "alice", formula="1d20+3", rng=lambda _n, _m: 10)
    assert result["success"] is True
    assert result["total"] == 13
    assert "=> 13" in str(result["content"])


def test_execute_roll_skill_check_via_mechanics_engine(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create_session(stream_id="g1", title="测试", creator_id="u1")
    _write_player(record.root / "players" / "alice.yaml")

    result = execute_roll(
        record.root,
        "alice",
        skill="perception",
        dc=13,
        rng=lambda _n, _m: 12,
    )
    assert result["success"] is True
    assert result["success_check"] is True
    assert result["total"] == 17
    assert "成功" in str(result["content"])


def test_query_bible_topic_and_list(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create_session(stream_id="g1", title="测试", creator_id="u1")
    (record.root / "bible" / "world.md").write_text("浮空群岛", encoding="utf-8")
    rules_dir = record.root / "bible" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "combat.md").write_text("先攻规则", encoding="utf-8")

    world = query_bible(record.root, "world")
    assert world["success"] is True
    assert world["content"] == "浮空群岛"

    rules = query_bible(record.root, "combat")
    assert rules["success"] is True
    assert "先攻" in str(rules["content"])

    listed = query_bible(record.root, "")
    assert listed["success"] is True
    assert "world" in str(listed["content"])
    assert "rules/combat" in str(listed["content"])


def test_query_log_reads_roll_entries(tmp_path: Path) -> None:
    import json

    store = SessionStore(tmp_path)
    record = store.create_session(stream_id="g1", title="测试", creator_id="u1")
    journal = record.root / "journal"
    journal.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": "2026-06-20T12:00:00+08:00",
        "beat_id": "b1",
        "kind": "skill_check",
        "actor": "alice",
        "skill": "perception",
        "formula": "1d20+5",
        "total": 18,
        "dc": 13,
        "success": True,
    }
    (journal / "rolls.jsonl").write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    result = query_log(record.root, limit=5)
    assert result["success"] is True
    assert "alice" in str(result["content"])
    assert "perception" in str(result["content"])
