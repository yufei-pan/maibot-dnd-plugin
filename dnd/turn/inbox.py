"""回合收件箱与消息标注。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InboxMessage:
    """待送入 GM 节拍的一条玩家消息。"""

    player_id: str
    text: str
    is_active: bool = False
    initiative_distance: int = -1
    ooc: bool = False


class Inbox:
    """按到达顺序累积玩家消息。"""

    def __init__(self) -> None:
        self._messages: list[InboxMessage] = []

    def append(self, msg: InboxMessage) -> None:
        """追加一条已标注消息。"""
        self._messages.append(msg)

    def drain(self) -> list[InboxMessage]:
        """取出并清空全部消息。"""
        messages = list(self._messages)
        self._messages.clear()
        return messages

    def peek(self) -> list[InboxMessage]:
        """只读查看当前队列。"""
        return list(self._messages)

    def __len__(self) -> int:
        return len(self._messages)
