"""筹备阶段：圣经、词典、规则书导入与就绪检查。"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

import httpx
import yaml

from dnd.mechanics.items import execute_spawn_item
from dnd.mechanics.sheets import CharacterSheet
from dnd.paths import _atomic_write, _safe_component
from dnd.session.lifecycle import format_readiness_checklist
from dnd.session.readiness import session_readiness

RULEBOOK_SPLIT_MARKER = "===DND_RULEBOOK_JSON==="

RULEBOOK_SPLIT_SYSTEM = (
    "你是 TRPG 规则书整理助手。给定规则书原文，按主题拆分为多个 Markdown 小节。\n"
    "输出格式：\n"
    "1) 可选一行简短说明\n"
    f"2) 单独一行 {RULEBOOK_SPLIT_MARKER}\n"
    "3) 下一行是 JSON 对象：键为 topic slug（英文小写连字符），值为该主题的 Markdown 正文。\n"
    "不要输出 markdown 代码块包裹 JSON。"
)


def _read_text(path: Path) -> str:
    """读取文本文件；文件不存在时返回空串。"""
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return ""


def _coalesce_text(primary: str, kwargs: Mapping[str, Any], *aliases: str) -> str:
    """取正文：优先显式参数，否则回退 kwargs 同义键。"""
    if str(primary or "").strip():
        return str(primary).strip()
    for key in aliases:
        value = kwargs.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalize_topic(topic: str) -> str:
    return _safe_component(topic).lower().replace(" ", "-")


def write_bible(
    session_root: Path,
    topic: str,
    content: str,
    mode: str,
    *,
    label: str | None = None,
) -> dict[str, Any]:
    """写入 bible/<topic>.md，支持 append / replace。"""
    topic_name = _normalize_topic(topic)
    if not topic_name:
        return {"success": False, "content": "请提供有效的设定主题 topic。"}

    body = str(content or "").strip()
    label_text = label or f"设定「{topic}」"
    if not body:
        return {
            "success": False,
            "content": f"{label_text}内容为空，未做任何改动。请把正文放进 content 参数后重试（已保留原有内容）。",
        }

    path = session_root / "bible" / f"{topic_name}.md"
    if str(mode).strip().lower() == "append":
        existing = _read_text(path)
        merged = (existing.rstrip() + "\n\n" + body).strip() if existing.strip() else body
        _atomic_write(path, merged + "\n")
    else:
        _atomic_write(path, body + "\n")

    return {"success": True, "content": f"已更新 {label_text}（bible/{topic_name}.md）。"}


def write_gm_prompt(session_root: Path, content: str, mode: str) -> dict[str, Any]:
    """写入 gm-prompt.md。"""
    body = str(content or "").strip()
    if not body:
        return {
            "success": False,
            "content": "GM 补充提示内容为空，未做任何改动。请把正文放进 content 参数后重试（已保留原有内容）。",
        }

    path = session_root / "gm-prompt.md"
    if str(mode).strip().lower() == "append":
        existing = _read_text(path)
        merged = (existing.rstrip() + "\n\n" + body).strip() if existing.strip() else body
        _atomic_write(path, merged + "\n")
    else:
        _atomic_write(path, body + "\n")

    return {"success": True, "content": "已更新 GM 补充提示（gm-prompt.md）。"}


def write_character_sheet(
    session_root: Path,
    player_id: str,
    content: str,
    mode: str = "replace",
) -> dict[str, Any]:
    """写入 players/<player_id>.yaml。"""
    pid = _safe_component(player_id)
    if not pid:
        return {"success": False, "content": "请提供有效的 player_id。"}

    body = str(content or "").strip()
    if not body:
        return {"success": False, "content": "角色卡内容为空，未写入。"}

    try:
        parsed = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        return {"success": False, "content": f"角色卡 YAML 解析失败：{exc}"}

    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        return {"success": False, "content": "角色卡 YAML 根节点必须是映射。"}

    path = session_root / "players" / f"{pid}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)

    if str(mode).strip().lower() == "append" and path.is_file():
        try:
            existing = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            return {"success": False, "content": f"现有角色卡 YAML 解析失败：{exc}"}
        if existing is None:
            existing = {}
        if not isinstance(existing, dict):
            return {"success": False, "content": "现有角色卡 YAML 根节点必须是映射。"}
        existing.update(parsed)
        parsed = existing

    try:
        CharacterSheet.from_yaml(yaml.dump(parsed, allow_unicode=True, sort_keys=False, default_flow_style=False))
    except ValueError as exc:
        return {"success": False, "content": f"角色卡字段校验失败：{exc}"}

    text = yaml.dump(parsed, allow_unicode=True, sort_keys=False, default_flow_style=False)
    if not text.endswith("\n"):
        text += "\n"
    _atomic_write(path, text)
    return {"success": True, "content": f"已更新玩家 {pid} 的角色卡（players/{pid}.yaml）。"}


def _load_dictionary(session_root: Path) -> dict[str, str]:
    path = session_root / "bible" / "dictionary.json"
    raw = _read_text(path).strip()
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("dictionary.json 根节点必须是对象")
    return {str(key).strip(): str(value).strip() for key, value in data.items() if str(key).strip()}


def dict_set(session_root: Path, term: str, explanation: str) -> dict[str, Any]:
    """写入 bible/dictionary.json 词条。"""
    key = str(term or "").strip()
    value = str(explanation or "").strip()
    if not key:
        return {"success": False, "content": "请提供词条 term。"}
    if not value:
        return {"success": False, "content": "请提供词条解释 explanation。"}

    path = session_root / "bible" / "dictionary.json"
    data = _load_dictionary(session_root)
    data[key] = value
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return {"success": True, "content": f"已写入词典词条「{key}」。"}


def dict_query(session_root: Path, term: str = "") -> dict[str, Any]:
    """查询 bible/dictionary.json 词条；term 为空时列出全部。"""
    try:
        data = _load_dictionary(session_root)
    except (json.JSONDecodeError, ValueError) as exc:
        return {"success": False, "content": f"词典文件无效：{exc}"}

    query = str(term or "").strip()
    if not query:
        if not data:
            return {"success": True, "content": "词典为空。"}
        lines = [f"- {key}: {value}" for key, value in sorted(data.items())]
        return {"success": True, "content": "\n".join(lines)}

    if query not in data:
        return {"success": False, "content": f"未找到词条「{query}」。"}
    return {"success": True, "content": f"{query}: {data[query]}"}


def review_ready(session_root: Path, enrolled_ids: list[str], ability_keys: list[str]) -> dict[str, Any]:
    """返回战役与角色卡就绪检查结果。"""
    missing = session_readiness(session_root, enrolled_ids, ability_keys)
    if not missing:
        return {"success": True, "content": "就绪检查已通过，可以 /dnd start 开跑。"}
    return {"success": True, "content": format_readiness_checklist(missing)}


def spawn_item(session_root: Path, item: Mapping[str, Any], give_to: str = "") -> dict[str, Any]:
    """生成物品到玩家背包或场景。"""
    if not isinstance(item, Mapping) or not item:
        return {"success": False, "content": "请提供 item 对象。"}
    try:
        result = execute_spawn_item(session_root, {"item": dict(item), "give_to": str(give_to or "").strip()})
    except (ValueError, FileNotFoundError) as exc:
        return {"success": False, "content": str(exc)}

    target = str(result.get("give_to") or "").strip()
    name = str(result.get("item_name") or result.get("item_id") or "")
    if target:
        return {"success": True, "content": f"已生成物品「{name}」并给予 {target}。"}
    return {"success": True, "content": f"已生成场景物品「{name}」。"}


async def fetch_rulebook_text(url: str, *, max_bytes: int, timeout: float = 30.0) -> str:
    """抓取规则书 URL 文本，超过 max_bytes 时抛出 ValueError。"""
    clean_url = str(url or "").strip()
    if not clean_url:
        raise ValueError("请提供规则书 URL。")
    if max_bytes <= 0:
        raise ValueError("规则书大小上限无效。")

    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(timeout)) as client:
        async with client.stream("GET", clean_url) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"规则书超过大小上限（{max_bytes} 字节），已中止下载。")
                chunks.append(chunk)

    return b"".join(chunks).decode("utf-8", errors="replace")


def parse_rulebook_split(response: str) -> dict[str, str]:
    """解析 LLM 规则书拆分响应为 topic -> markdown。"""
    text = str(response or "").strip()
    if RULEBOOK_SPLIT_MARKER not in text:
        raise ValueError(f"规则书拆分响应缺少 {RULEBOOK_SPLIT_MARKER}")

    _, _, tail = text.partition(RULEBOOK_SPLIT_MARKER)
    json_text = tail.strip()
    if not json_text:
        raise ValueError("规则书拆分 JSON 为空")

    match = re.search(r"\{[\s\S]*\}", json_text)
    if match is None:
        raise ValueError("规则书拆分响应中找不到 JSON 对象")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("规则书拆分 JSON 必须是对象")

    topics: dict[str, str] = {}
    for key, value in data.items():
        topic = _normalize_topic(str(key))
        body = str(value).strip()
        if topic and body:
            topics[topic] = body
    if not topics:
        raise ValueError("规则书拆分结果为空")
    return topics


def write_rulebook_topics(session_root: Path, topics: Mapping[str, str]) -> list[str]:
    """把拆分后的规则主题写入 bible/rules/<topic>.md。"""
    rules_dir = session_root / "bible" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for topic, body in topics.items():
        topic_name = _normalize_topic(topic)
        if not topic_name:
            continue
        path = rules_dir / f"{topic_name}.md"
        _atomic_write(path, body.strip() + "\n")
        written.append(topic_name)
    if not written:
        raise ValueError("没有可写入的规则主题")
    return written


async def import_rulebook(
    llm_generate: Callable[..., Awaitable[Any]],
    session_root: Path,
    url: str,
    *,
    max_bytes: int,
    model: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """抓取 URL 并经 LLM 拆分后写入 bible/rules/。"""
    clean_url = str(url or "").strip()
    if not clean_url:
        return {"success": False, "content": "请提供规则书 URL。"}

    model_name = str(model or "").strip()
    if not model_name:
        raise ValueError("未配置 session.gm_model")

    raw_text = await fetch_rulebook_text(clean_url, max_bytes=max_bytes, timeout=timeout)
    if not raw_text.strip():
        return {"success": False, "content": "抓取到的规则书内容为空。"}

    messages = [
        {"role": "system", "content": RULEBOOK_SPLIT_SYSTEM},
        {"role": "user", "content": f"请拆分以下规则书原文（URL: {clean_url}）：\n\n{raw_text}"},
    ]
    result = await llm_generate(prompt=messages, model=model_name)
    if not isinstance(result, dict):
        raise ValueError("LLM 返回值无效")
    if not bool(result.get("success")):
        raise ValueError(str(result.get("error") or "LLM 拆分失败"))

    response = str(result.get("response") or "").strip()
    if not response:
        raise ValueError("LLM 返回空响应")

    topics = parse_rulebook_split(response)
    written = write_rulebook_topics(session_root, topics)
    return {
        "success": True,
        "content": f"已导入规则书，写入 {len(written)} 个主题：{', '.join(written)}。",
    }
