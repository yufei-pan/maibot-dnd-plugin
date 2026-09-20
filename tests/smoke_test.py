"""离线冒烟测试：不依赖 MaiBot Host，验证插件可导入与核心纯逻辑。

运行方式（在仓库根目录）：
    PYTHONPATH=.:../maibot-plugin-sdk python tests/smoke_test.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR))
sys.path.insert(0, str(PLUGIN_DIR.parent / "maibot-plugin-sdk"))

import plugin as dnd_plugin  # noqa: E402
from dnd.config import CURRENT_CONFIG_VERSION, DndConfig, _normalize_dnd_config  # noqa: E402
from dnd.gm.parser import DND_BEAT_JSON_MARKER, parse_gm_response  # noqa: E402
from dnd.llm_route import resolve_llm_route  # noqa: E402
from dnd.mechanics.sheets import CharacterSheet  # noqa: E402
from dnd.session.readiness import campaign_readiness, session_readiness  # noqa: E402

_ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"]

GM_PARSER_SAMPLE = f"""一些叙述文字
{DND_BEAT_JSON_MARKER}
{{"narration":"艾莉丝躲进阴影","mechanics":[{{"kind":"skill_check","actor":"a1","skill":"stealth","dc":12}}],"feedback":[],"honored":["m1"],"turn_advance":{{"to":"a1"}}}}
"""


def test_create_plugin_and_config_version() -> None:
    inst = dnd_plugin.create_plugin()
    assert inst.plugin_id == "maibot-dnd-plugin"
    cfg = DndConfig()
    assert cfg.plugin.config_version == CURRENT_CONFIG_VERSION


def test_resolve_llm_route() -> None:
    assert resolve_llm_route("planner", ["utils", "planner", "replyer"]) == ("planner", None)
    assert resolve_llm_route("step-5-preview", ["utils", "planner"]) == (None, "step-5-preview")
    assert resolve_llm_route("planner", None) == ("planner", None)


def test_normalize_config_empty() -> None:
    defaults = DndConfig().model_dump(mode="python")
    merged, changed, notes = _normalize_dnd_config({}, defaults)
    assert changed is True
    assert merged["plugin"]["config_version"] == CURRENT_CONFIG_VERSION
    assert any("空配置" in note for note in notes)


def test_normalize_config_version_migration() -> None:
    defaults = DndConfig().model_dump(mode="python")
    raw = {
        "plugin": {"config_version": "0.0.1"},
        "session": {"debounce_seconds": 30},
    }
    merged, changed, notes = _normalize_dnd_config(raw, defaults)
    assert changed is True
    assert merged["plugin"]["config_version"] == CURRENT_CONFIG_VERSION
    assert merged["session"]["debounce_seconds"] == 30


def test_normalize_config_merge_current() -> None:
    defaults = DndConfig().model_dump(mode="python")
    raw = {
        "plugin": {"config_version": CURRENT_CONFIG_VERSION},
        "broadcast": {"system_prefix": "【测试】"},
    }
    merged, changed, notes = _normalize_dnd_config(raw, defaults)
    assert merged["broadcast"]["system_prefix"] == "【测试】"
    assert notes == []


def test_parse_gm_response_sample() -> None:
    payload = parse_gm_response(GM_PARSER_SAMPLE)
    assert "艾莉丝" in payload.narration
    assert payload.mechanics[0]["kind"] == "skill_check"
    assert payload.honored_ids == ["m1"]
    assert payload.turn_advance == {"to": "a1"}


def test_readiness_gates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # Gate A：战役圣经缺 plot-outline
        (root / "bible").mkdir()
        (root / "bible" / "world.md").write_text("浮空群岛", encoding="utf-8")
        gate_a = campaign_readiness(root)
        assert any("plot-outline" in item for item in gate_a)

        # Gate A + B：补全圣经与 GM 提示，但玩家角色卡不完整
        for stem in ("world", "plot-outline", "characters"):
            (root / "bible" / f"{stem}.md").write_text(f"{stem} 内容", encoding="utf-8")
        (root / "gm-prompt.md").write_text("悬疑氛围", encoding="utf-8")
        (root / "players").mkdir()

        good = CharacterSheet(
            name="Alice",
            abilities=dict.fromkeys(_ABILITY_KEYS, 10),
            skills={"stealth": 3},
            hp_current=8,
            hp_max=8,
        )
        (root / "players" / "p1.yaml").write_text(good.to_yaml(), encoding="utf-8")
        (root / "players" / "p2.yaml").write_text("name: Bob\n", encoding="utf-8")

        missing = session_readiness(root, ["p1", "p2", "p3"], _ABILITY_KEYS)
        assert not any("bible/" in item for item in missing)
        assert any("p2" in item for item in missing)
        assert any("p3" in item for item in missing)


def _run_all() -> None:
    test_create_plugin_and_config_version()
    test_resolve_llm_route()
    test_normalize_config_empty()
    test_normalize_config_version_migration()
    test_normalize_config_merge_current()
    test_parse_gm_response_sample()
    test_readiness_gates()


if __name__ == "__main__":
    _run_all()
    print("ok")
