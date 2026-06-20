"""会话文件系统读写。"""

from __future__ import annotations

import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11
    import tomli as tomllib  # type: ignore[no-redef, unused-ignore]

import tomli_w

from dnd.paths import _atomic_write, session_dir

_BIBLE_STEMS = ("world", "plot-outline", "characters")
_SCENE_STATE_HEADING = "# 场景状态\n"


@dataclass(frozen=True)
class SessionRecord:
    """已加载的会话元数据与根目录。"""

    session_id: str
    stream_id: str
    title: str
    creator_id: str
    status: str
    root: Path


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _toml_safe(meta: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in meta.items() if value is not None}


class SessionStore:
    """按聊天流与会话 ID 管理地下城会话目录。"""

    def __init__(self, data_root: Path) -> None:
        self._data_root = Path(data_root)

    def create_session(self, *, stream_id: str, title: str, creator_id: str) -> SessionRecord:
        session_id = secrets.token_hex(8)
        root = session_dir(self._data_root, stream_id, session_id)
        if root.exists():
            raise FileExistsError(f"会话目录已存在: {root}")

        for sub in ("bible/maps", "bible/rules", "players", "state", "journal", "summaries"):
            (root / sub).mkdir(parents=True, exist_ok=True)

        for stem in _BIBLE_STEMS:
            _atomic_write(root / "bible" / f"{stem}.md", "")

        _atomic_write(root / "bible" / "dictionary.json", "{}\n")
        _atomic_write(root / "gm-prompt.md", "")
        _atomic_write(root / "state" / "scene-state.md", _SCENE_STATE_HEADING)
        _atomic_write(root / "state" / "turn.yaml", "")

        meta: dict[str, Any] = {
            "session_id": session_id,
            "stream_id": stream_id,
            "title": title,
            "creator_id": creator_id,
            "status": "setup",
            "created": _now(),
        }
        _atomic_write(root / "session.toml", tomli_w.dumps(_toml_safe(meta)))

        return SessionRecord(
            session_id=session_id,
            stream_id=stream_id,
            title=title,
            creator_id=creator_id,
            status="setup",
            root=root,
        )

    def load_session(self, session_id: str, *, stream_id: str) -> SessionRecord:
        root = session_dir(self._data_root, stream_id, session_id)
        raw = (root / "session.toml").read_text(encoding="utf-8")
        meta = dict(tomllib.loads(raw))
        return SessionRecord(
            session_id=str(meta["session_id"]),
            stream_id=str(meta["stream_id"]),
            title=str(meta["title"]),
            creator_id=str(meta["creator_id"]),
            status=str(meta["status"]),
            root=root,
        )

    @staticmethod
    def write_text(path: Path, text: str) -> None:
        _atomic_write(path, text)

    @staticmethod
    def append_jsonl(path: Path, obj: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(dict(obj), ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
