"""Host LLM 任务名 / 具体模型名路由（SDK 2.8.1）。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def resolve_llm_route(
    configured: str,
    available_tasks: Sequence[str] | None,
) -> tuple[str | None, str | None]:
    """把配置值拆成 Host 的 ``task_name`` / ``model_name``。

    命中 ``llm.get_available_models()`` 任务名则走 ``task_name``；否则走 ``model_name``。
    列表不可用时按任务名，避免 SDK 2.8.1 把 ``planner`` 当成具体模型。
    """
    name = str(configured or "").strip()
    if not name:
        return None, None
    tasks = {str(item).strip() for item in (available_tasks or []) if str(item).strip()}
    if not tasks:
        return name, None
    if name in tasks:
        return name, None
    return None, name


async def list_host_tasks(llm: Any) -> list[str] | None:
    getter = getattr(llm, "get_available_models", None)
    if getter is None:
        return None
    try:
        raw = await getter()
    except Exception:
        return None
    if not isinstance(raw, (list, tuple, set)):
        return None
    return [str(item).strip() for item in raw if str(item).strip()]


async def host_generate(llm: Any, prompt: Any, configured: str, **extra: Any) -> Any:
    """调用 ``llm.generate``，只传 ``task_name`` 或 ``model_name``，绝不把任务名塞进 ``model``。"""
    available = await list_host_tasks(llm)
    task_name, model_name = resolve_llm_route(configured, available)
    kwargs: dict[str, Any] = {"prompt": prompt, **extra}
    if task_name:
        kwargs["task_name"] = task_name
    if model_name:
        kwargs["model_name"] = model_name
    return await llm.generate(**kwargs)
