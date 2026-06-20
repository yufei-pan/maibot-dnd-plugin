"""会话文件系统读写。"""

from __future__ import annotations

import json
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11
    import tomli as tomllib  # type: ignore[no-redef, unused-ignore]

import tomli_w

from dnd.paths import _atomic_write, _safe_stream_dir, session_dir

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
            "enrolled": [],
            "active_player": "",
            "initiative": [],
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

    def _sessions_root(self, stream_id: str) -> Path:
        return self._data_root / _safe_stream_dir(stream_id) / "sessions"

    @staticmethod
    def _read_meta(root: Path) -> dict[str, Any]:
        raw = (root / "session.toml").read_text(encoding="utf-8")
        return dict(tomllib.loads(raw))

    @staticmethod
    def _write_meta(root: Path, meta: Mapping[str, Any]) -> None:
        _atomic_write(root / "session.toml", tomli_w.dumps(_toml_safe(meta)))

    @staticmethod
    def _record_from_meta(root: Path, meta: Mapping[str, Any]) -> SessionRecord:
        return SessionRecord(
            session_id=str(meta["session_id"]),
            stream_id=str(meta["stream_id"]),
            title=str(meta["title"]),
            creator_id=str(meta["creator_id"]),
            status=str(meta["status"]),
            root=root,
        )

    def load_session(self, session_id: str, *, stream_id: str) -> SessionRecord:
        root = session_dir(self._data_root, stream_id, session_id)
        meta = self._read_meta(root)
        return self._record_from_meta(root, meta)

    def list_sessions(self, stream_id: str) -> list[SessionRecord]:
        root = self._sessions_root(stream_id)
        if not root.is_dir():
            return []

        records: list[SessionRecord] = []
        for child in sorted(root.iterdir()):
            meta_path = child / "session.toml"
            if not child.is_dir() or not meta_path.is_file():
                continue
            meta = self._read_meta(child)
            records.append(self._record_from_meta(child, meta))
        return records

    def find_active_session(self, stream_id: str) -> SessionRecord | None:
        for record in self.list_sessions(stream_id):
            if record.status != "stopped":
                return record
        return None

    def load_enrolled(self, session_id: str, *, stream_id: str) -> set[str]:
        root = session_dir(self._data_root, stream_id, session_id)
        meta = self._read_meta(root)
        raw = meta.get("enrolled", [])
        if not isinstance(raw, list):
            raise ValueError(f"会话 {session_id} 的 enrolled 字段无效")
        return {str(item).strip() for item in raw if str(item).strip()}

    def update_status(self, session_id: str, *, stream_id: str, status: str) -> SessionRecord:
        root = session_dir(self._data_root, stream_id, session_id)
        meta = self._read_meta(root)
        meta["status"] = status
        self._write_meta(root, meta)
        return self._record_from_meta(root, meta)

    def update_creator(self, session_id: str, *, stream_id: str, creator_id: str) -> SessionRecord:
        root = session_dir(self._data_root, stream_id, session_id)
        meta = self._read_meta(root)
        meta["creator_id"] = creator_id
        self._write_meta(root, meta)
        return self._record_from_meta(root, meta)

    def add_enrolled(self, session_id: str, *, stream_id: str, user_id: str) -> None:
        uid = str(user_id).strip()
        if not uid:
            raise ValueError("无效玩家 ID")
        root = session_dir(self._data_root, stream_id, session_id)
        meta = self._read_meta(root)
        enrolled = self.load_enrolled(session_id, stream_id=stream_id)
        enrolled.add(uid)
        meta["enrolled"] = sorted(enrolled)
        self._write_meta(root, meta)

    def remove_enrolled(self, session_id: str, *, stream_id: str, user_id: str) -> None:
        uid = str(user_id).strip()
        root = session_dir(self._data_root, stream_id, session_id)
        meta = self._read_meta(root)
        enrolled = self.load_enrolled(session_id, stream_id=stream_id)
        if uid not in enrolled:
            raise ValueError("你尚未报名本局")
        enrolled.remove(uid)
        meta["enrolled"] = sorted(enrolled)
        if str(meta.get("active_player", "")).strip() == uid:
            meta["active_player"] = ""
        initiative = meta.get("initiative")
        if isinstance(initiative, list):
            meta["initiative"] = [item for item in initiative if str(item).strip() != uid]
        self._write_meta(root, meta)

    def load_turn_state(self, session_id: str, *, stream_id: str) -> tuple[str, list[str]]:
        root = session_dir(self._data_root, stream_id, session_id)
        meta = self._read_meta(root)
        active = str(meta.get("active_player", "")).strip()
        raw = meta.get("initiative")
        if not isinstance(raw, list):
            return active, []
        order = [str(item).strip() for item in raw if str(item).strip()]
        return active, order

    def save_turn_state(
        self,
        session_id: str,
        *,
        stream_id: str,
        active_player: str,
        initiative: Iterable[str] | None = None,
    ) -> None:
        root = session_dir(self._data_root, stream_id, session_id)
        meta = self._read_meta(root)
        meta["active_player"] = str(active_player).strip()
        if initiative is not None:
            meta["initiative"] = [str(item).strip() for item in initiative if str(item).strip()]
        self._write_meta(root, meta)

    def ensure_turn_state(self, session_id: str, *, stream_id: str, enrolled: set[str]) -> SessionRecord:
        root = session_dir(self._data_root, stream_id, session_id)
        meta = self._read_meta(root)
        meta["status"] = "running"
        if not str(meta.get("active_player", "")).strip() and enrolled:
            ordered = sorted(enrolled)
            meta["initiative"] = ordered
            meta["active_player"] = ordered[0]
        self._write_meta(root, meta)
        return self._record_from_meta(root, meta)

    @staticmethod
    def write_text(path: Path, text: str) -> None:
        _atomic_write(path, text)

    @staticmethod
    def append_jsonl(path: Path, obj: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(dict(obj), ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
