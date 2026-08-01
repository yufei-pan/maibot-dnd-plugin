"""帮助文案测试。"""

from __future__ import annotations

from dnd.help import build_help_message


def test_help_mentions_player_commands() -> None:
    text = build_help_message("测试酱")
    assert "/dnd join" in text
    assert "/dnd proceed" in text
    assert "/dnd turn" in text
    assert "/dnd help" in text
    assert "【地下城·GM】" in text
    assert "测试酱" in text
    assert "麦麦" not in text


def test_help_mentions_organizer_commands() -> None:
    text = build_help_message("测试酱")
    assert "/dnd new" in text
    assert "/dnd start" in text
    assert "/dnd review" in text
