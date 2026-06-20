"""会话目录路径与安全文件名工具。"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path


def _safe_component(value: str) -> str:
    """把任意字符串清洗为安全的单段文件/目录名。"""
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value).strip())
    return sanitized.strip(". ")


def _safe_stream_dir(stream_id: str) -> str:
    """把 stream_id 映射为安全且稳定的工作区目录名。"""
    safe = _safe_component(stream_id)
    if safe:
        return safe
    return "s_" + hashlib.sha256(str(stream_id).encode("utf-8")).hexdigest()[:16]


def session_dir(data_root: Path, stream_id: str, session_id: str) -> Path:
    """返回指定聊天流与会话 ID 的根目录路径。"""
    return data_root / _safe_stream_dir(stream_id) / "sessions" / _safe_component(session_id)


def _atomic_write(path: Path, text: str) -> None:
    """原子写入文本文件（先写 .tmp 再 os.replace）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
