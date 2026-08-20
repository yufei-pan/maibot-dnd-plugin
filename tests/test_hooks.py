"""Task 10 hooks 辅助函数测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from plugin import DndPlugin

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


@pytest.mark.anyio
async def test_replyer_briefing_supports_maibot_1_2_context_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1.2 只提供 items 时，玩家简报仍须插入 system 后。"""
    players = tmp_path / "players"
    players.mkdir(parents=True)
    (players / "mai.yaml").write_text("name: 麦麦\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir(parents=True)
    (state / "scene-state.md").write_text("# 场景状态\n古堡门前。\n", encoding="utf-8")

    class Lifecycle:
        @staticmethod
        def enrolled_ids(_record: object) -> set[str]:
            return {"mai"}

    plugin = DndPlugin()
    plugin._mai_person_id = "mai"
    record = SimpleNamespace(root=tmp_path)
    monkeypatch.setattr(plugin, "_resolve_running_session", lambda _stream_id: (Lifecycle(), record))

    system_item = {
        "item_type": "SystemMessageItem",
        "meta": {
            "item_id": "system-1",
            "logical_turn_id": None,
            "timestamp": "2026-08-19T12:00:00-07:00",
        },
        "parts": [{"type": "text", "text": "system"}],
    }
    existing_user_item = {
        "item_type": "UserMessageItem",
        "meta": {
            "item_id": "user-1",
            "logical_turn_id": "turn-1",
            "timestamp": "2026-08-19T12:00:01-07:00",
        },
        "parts": [
            {"type": "text", "text": "继续冒险"},
            {"type": "image", "image_format": "png", "image_base64": "unchanged"},
        ],
    }

    result = await plugin.hook_inject_mai_player_briefing(
        items=[system_item, existing_user_item],
        item_schema_version=1,
        session_id="stream-1",
    )

    items = result["modified_kwargs"]["items"]
    assert items[0] == system_item
    assert items[1]["item_type"] == "UserMessageItem"
    assert "麦麦" in items[1]["parts"][0]["text"]
    assert "古堡门前" in items[1]["parts"][0]["text"]
    assert items[2] == existing_user_item


@pytest.mark.anyio
async def test_replyer_briefing_keeps_legacy_messages_compatible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """仍受支持的旧 Host messages 载荷不得回归。"""
    players = tmp_path / "players"
    players.mkdir(parents=True)
    (players / "mai.yaml").write_text("name: 麦麦\n", encoding="utf-8")

    class Lifecycle:
        @staticmethod
        def enrolled_ids(_record: object) -> set[str]:
            return {"mai"}

    plugin = DndPlugin()
    plugin._mai_person_id = "mai"
    record = SimpleNamespace(root=tmp_path)
    monkeypatch.setattr(plugin, "_resolve_running_session", lambda _stream_id: (Lifecycle(), record))

    result = await plugin.hook_inject_mai_player_briefing(
        messages=[{"role": "system", "content": "system"}],
        session_id="stream-1",
    )

    messages = result["modified_kwargs"]["messages"]
    assert messages[0] == {"role": "system", "content": "system"}
    assert messages[1]["role"] == "user"
    assert "麦麦" in messages[1]["content"]


@pytest.mark.anyio
async def test_replyer_briefing_uses_stream_reported_bot_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多账号时应按当前 stream 的 adapter account 找到麦麦玩家。"""
    players = tmp_path / "players"
    players.mkdir(parents=True)
    (players / "person-bot-2.yaml").write_text("name: 麦麦二号\n", encoding="utf-8")

    class Lifecycle:
        @staticmethod
        def enrolled_ids(_record: object) -> set[str]:
            return {"person-bot-2"}

    async def get_all_streams(*, platform: str) -> list[dict[str, object]]:
        assert platform == "all_platforms"
        return [
            {
                "session_id": "stream-2",
                "stream_id": "stream-2",
                "platform": "qq",
                "user_id": "human-1",
                "user_nickname": "玩家",
                "user_cardname": "",
                "group_id": "group-1",
                "group_name": "测试群",
                "account_id": "bot-2",
                "scope": "default",
                "is_group_session": True,
                "chat_type": "group",
            }
        ]

    async def get_person_id(platform: str, user_id: str) -> str:
        return "person-bot-2" if (platform, user_id) == ("qq", "bot-2") else ""

    plugin = DndPlugin()
    plugin.set_plugin_config(plugin.config_model().model_dump(mode="python"))
    plugin._mai_person_id = "person-bot-1"
    plugin._set_context(
        SimpleNamespace(
            chat=SimpleNamespace(get_all_streams=get_all_streams),
            person=SimpleNamespace(get_id=get_person_id),
            logger=MagicMock(),
        )
    )
    record = SimpleNamespace(root=tmp_path)
    monkeypatch.setattr(plugin, "_resolve_running_session", lambda _stream_id: (Lifecycle(), record))

    result = await plugin.hook_inject_mai_player_briefing(
        messages=[{"role": "system", "content": "system"}],
        session_id="stream-2",
    )

    injected = result["modified_kwargs"]["messages"][1]["content"]
    assert "麦麦二号" in injected


@pytest.mark.anyio
async def test_broker_resolves_stream_specific_bot_before_fallback() -> None:
    """GM broker 唤醒麦麦时也必须使用当前 stream 的账号身份。"""
    from dnd.gm import broker

    class Plugin:
        _mai_person_id = "fallback-person"

        @staticmethod
        async def _get_mai_person_id(stream_id: str) -> str:
            return "stream-person" if stream_id == "stream-2" else ""

    assert await broker._resolve_plugin_bot_person_id(Plugin(), "stream-2") == "stream-person"
    assert await broker._resolve_plugin_bot_person_id(Plugin(), "unknown-stream") == "fallback-person"


@pytest.mark.anyio
async def test_stream_bot_identity_falls_back_when_stream_lookup_fails() -> None:
    """旧 Host 或瞬时 RPC 失败时应保留全局账号解析结果。"""

    async def get_all_streams(*, platform: str) -> list[dict[str, object]]:
        assert platform == "all_platforms"
        raise RuntimeError("capability unavailable")

    plugin = DndPlugin()
    plugin.set_plugin_config(plugin.config_model().model_dump(mode="python"))
    plugin._mai_person_id = "fallback-person"
    plugin._set_context(
        SimpleNamespace(
            chat=SimpleNamespace(get_all_streams=get_all_streams),
            person=SimpleNamespace(get_id=MagicMock()),
        )
    )

    assert await plugin._get_mai_person_id("stream-1") == "fallback-person"


@pytest.mark.anyio
async def test_configured_bot_identity_precedes_stream_lookup() -> None:
    """显式 maibot_person_id 配置必须在新旧 Host 上都具有最高优先级。"""

    async def unexpected_stream_lookup(*, platform: str) -> list[dict[str, object]]:
        raise AssertionError(f"不应查询聊天流: {platform}")

    plugin = DndPlugin()
    config = plugin.config_model().model_dump(mode="python")
    config["session"]["maibot_person_id"] = "configured-person"
    plugin.set_plugin_config(config)
    plugin._mai_person_id = "fallback-person"
    plugin._set_context(
        SimpleNamespace(
            chat=SimpleNamespace(get_all_streams=unexpected_stream_lookup),
            person=SimpleNamespace(get_id=MagicMock()),
        )
    )

    assert await plugin._get_mai_person_id("stream-1") == "configured-person"


@pytest.mark.anyio
async def test_hooks_skip_stream_lookup_without_running_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有进行中的战役时不得为解析麦麦身份去列举全部聊天流。"""

    async def unexpected_stream_lookup(*, platform: str) -> list[dict[str, object]]:
        raise AssertionError(f"不应查询聊天流: {platform}")

    plugin = DndPlugin()
    plugin.set_plugin_config(plugin.config_model().model_dump(mode="python"))
    plugin._set_context(
        SimpleNamespace(
            chat=SimpleNamespace(get_all_streams=unexpected_stream_lookup),
            person=SimpleNamespace(get_id=MagicMock()),
            logger=MagicMock(),
        )
    )
    monkeypatch.setattr(plugin, "_resolve_running_session", lambda _stream_id: (object(), None))

    inject = await plugin.hook_inject_mai_player_briefing(
        session_id="stream-1",
        messages=[{"role": "system", "content": "system"}],
    )
    assert inject == {"action": "continue"}

    capture = await plugin.hook_capture_mai_reply(session_id="stream-1", response="我去开门")
    assert capture == {"action": "continue"}

    await plugin.event_capture_enrolled_human_message(
        message={
            "session_id": "stream-1",
            "processed_plain_text": "我去开门",
            "message_info": {"user_info": {"user_id": "human-1"}},
        }
    )
