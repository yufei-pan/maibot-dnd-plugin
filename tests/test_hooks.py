"""Task 10 hooks 辅助函数测试。"""

from __future__ import annotations

from pathlib import Path

from dnd.hooks import (
    build_player_briefing,
    extract_plain_text,
    is_running,
    load_character_name,
    load_scene_brief,
    resolve_stream_id,
    resolve_user_id,
)


def test_is_running_case_insensitive() -> None:
    assert is_running("RUNNING") is True
    assert is_running("running") is True
    assert is_running("setup") is False


def test_resolve_stream_id_from_top_level_then_message() -> None:
    assert resolve_stream_id({"stream_id": "g1"}) == "g1"
    assert resolve_stream_id({"session_id": "s1"}) == "s1"
    assert resolve_stream_id({"message": {"session_id": "m1"}}) == "m1"


def test_resolve_user_id_from_nested_message_info() -> None:
    payload = {"message": {"message_info": {"user_info": {"user_id": "u-nested"}}}}
    assert resolve_user_id(payload) == "u-nested"


def test_extract_plain_text_prefers_message() -> None:
    message = {"plain_text": "来自 message"}
    kwargs = {"plain_text": "来自 kwargs"}
    assert extract_plain_text(message, kwargs) == "来自 message"


def test_load_scene_brief_removes_heading(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "scene-state.md").write_text("# 场景状态\n洞穴里有火把。\n", encoding="utf-8")
    assert load_scene_brief(tmp_path) == "洞穴里有火把。"


def test_load_character_name_from_sheet(tmp_path: Path) -> None:
    players = tmp_path / "players"
    players.mkdir(parents=True, exist_ok=True)
    (players / "p1.yaml").write_text("name: 艾莉丝\nhp_current: 8\n", encoding="utf-8")
    assert load_character_name(tmp_path, "p1") == "艾莉丝"


def test_build_player_briefing_contains_required_sections() -> None:
    briefing = build_player_briefing("艾莉丝", "你们站在古堡大门前。")
    assert "你的角色名" in briefing
    assert "艾莉丝" in briefing
    assert "场景摘要" in briefing
