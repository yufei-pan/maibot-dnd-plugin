"""Host LLM 任务名 / 具体模型名路由。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dnd.llm_route import host_generate, resolve_llm_route

pytestmark = pytest.mark.anyio


def test_resolve_llm_route_prefers_task_names() -> None:
    assert resolve_llm_route("planner", ["utils", "planner", "replyer"]) == ("planner", None)
    assert resolve_llm_route(" utils ", ["utils"]) == ("utils", None)


def test_resolve_llm_route_uses_model_name_when_not_a_task() -> None:
    assert resolve_llm_route("step-5-preview", ["utils", "planner"]) == (None, "step-5-preview")


def test_resolve_llm_route_listing_unavailable_falls_back_to_task() -> None:
    assert resolve_llm_route("planner", None) == ("planner", None)
    assert resolve_llm_route("planner", []) == ("planner", None)
    assert resolve_llm_route("", ["planner"]) == (None, None)


async def test_host_generate_uses_task_name_not_model() -> None:
    captured: list[dict[str, object]] = []

    async def generate(**kwargs: object) -> dict[str, object]:
        captured.append(dict(kwargs))
        return {"success": True, "response": "ok"}

    async def get_available_models() -> list[str]:
        return ["utils", "planner", "replyer"]

    llm = SimpleNamespace(generate=generate, get_available_models=get_available_models)
    result = await host_generate(llm, [{"role": "user", "content": "hi"}], "planner")
    assert result["success"] is True
    assert captured[0].get("task_name") == "planner"
    assert "model" not in captured[0]
    assert "model_name" not in captured[0]


async def test_host_generate_uses_model_name_for_concrete_model() -> None:
    captured: list[dict[str, object]] = []

    async def generate(**kwargs: object) -> dict[str, object]:
        captured.append(dict(kwargs))
        return {"success": True, "response": "ok"}

    async def get_available_models() -> list[str]:
        return ["utils", "planner"]

    llm = SimpleNamespace(generate=generate, get_available_models=get_available_models)
    await host_generate(llm, "hi", "step-5-preview", temperature=0.2)
    assert captured[0].get("model_name") == "step-5-preview"
    assert captured[0].get("temperature") == 0.2
    assert "task_name" not in captured[0]
    assert "model" not in captured[0]


async def test_host_generate_listing_failure_keeps_task_name() -> None:
    captured: list[dict[str, object]] = []

    async def generate(**kwargs: object) -> dict[str, object]:
        captured.append(dict(kwargs))
        return {"success": True, "response": "ok"}

    async def get_available_models() -> list[str]:
        raise RuntimeError("listing failed")

    llm = SimpleNamespace(generate=generate, get_available_models=get_available_models)
    await host_generate(llm, "hi", "planner")
    assert captured[0].get("task_name") == "planner"
    assert "model_name" not in captured[0]
