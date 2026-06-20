"""GM 解析器与上下文组装测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd.config import DndConfig
from dnd.gm.context import build_gm_messages
from dnd.gm.parser import DND_BEAT_JSON_MARKER, parse_gm_response
from dnd.store import SessionStore
from dnd.turn.inbox import InboxMessage

SAMPLE = """一些叙述文字
===DND_BEAT_JSON===
{"narration":"艾莉丝躲进阴影","mechanics":[{"kind":"skill_check","actor":"a1","skill":"stealth","dc":12}],"feedback":[],"honored":["m1"],"turn_advance":{"to":"a1"}}
"""


def test_parse_gm_block() -> None:
    payload = parse_gm_response(SAMPLE)
    assert "艾莉丝" in payload.narration
    assert payload.mechanics[0]["kind"] == "skill_check"
    assert payload.honored_ids == ["m1"]
    assert payload.turn_advance == {"to": "a1"}


def test_parse_gm_block_missing_marker() -> None:
    with pytest.raises(ValueError, match=DND_BEAT_JSON_MARKER):
        parse_gm_response("只有叙述，没有 JSON")


def test_parse_gm_block_invalid_json() -> None:
    broken = f"叙述\n{DND_BEAT_JSON_MARKER}\n{{not json"
    with pytest.raises(ValueError, match="JSON"):
        parse_gm_response(broken)


def test_build_gm_messages_includes_core_sections(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create_session(stream_id="g1", title="测试战役", creator_id="u1")
    store.write_text(record.root / "gm-prompt.md", "强调悬疑氛围")
    store.write_text(record.root / "state" / "scene-state.md", "# 场景状态\n酒馆一楼，雨夜。")
    store.write_text(record.root / "bible" / "world.md", "浮空群岛")
    store.write_text(record.root / "bible" / "plot-outline.md", "寻找失落的王冠")
    store.write_text(
        record.root / "players" / "alice.yaml",
        "name: 艾莉丝\nabilities: {str: 10, dex: 14, con: 12, int: 10, wis: 12, cha: 10}\n"
        "skills: {stealth: 5}\nhp_current: 8\nhp_max: 8\n",
    )
    store.add_enrolled(record.session_id, stream_id="g1", user_id="alice")
    store.save_turn_state(record.session_id, stream_id="g1", active_player="alice", initiative=["alice"])

    inbox = [
        InboxMessage(player_id="alice", text="我躲到吧台后面", is_active=True, initiative_distance=0),
    ]
    messages = build_gm_messages(record, inbox, DndConfig())

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    system = messages[0]["content"]
    assert "悬疑氛围" in system
    assert "酒馆一楼" in system
    assert "浮空群岛" in system
    assert "alice" in system
    assert "吧台后面" in system
    assert DND_BEAT_JSON_MARKER in system


def test_build_gm_messages_clips_low_priority_first(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create_session(stream_id="g1", title="裁剪测试", creator_id="u1")
    store.write_text(record.root / "gm-prompt.md", "GM补充")
    store.write_text(record.root / "state" / "scene-state.md", "# 场景状态\n核心场景。")
    store.write_text(record.root / "bible" / "world.md", "世界观保留")
    store.write_text(record.root / "bible" / "plot-outline.md", "大纲保留")

    beats_path = record.root / "journal" / "beats.jsonl"
    for index in range(12):
        store.append_jsonl(
            beats_path,
            {"narration": f"历史节拍{index}-" + ("x" * 120)},
        )

    inbox = [
        InboxMessage(player_id="bob", text="低优先级收件箱-" + ("y" * 300), is_active=False),
    ]

    cfg = DndConfig()
    cfg.session.gm_context_char_budget = 2000

    messages = build_gm_messages(record, inbox, cfg)
    system = messages[0]["content"]

    assert "世界观保留" in system
    assert "核心场景。" in system
    assert "低优先级收件箱" not in system


def test_build_gm_messages_dictionary_hits(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create_session(stream_id="g1", title="词典", creator_id="u1")
    store.write_text(record.root / "gm-prompt.md", "ok")
    store.write_text(
        record.root / "bible" / "dictionary.json",
        json.dumps({"秘银": "银色金属，轻盈坚固"}, ensure_ascii=False),
    )

    inbox = [InboxMessage(player_id="alice", text="我检查秘银门环", is_active=True)]
    messages = build_gm_messages(record, inbox, DndConfig())

    assert "秘银" in messages[0]["content"]
