"""GMBroker payload 执行测试（不依赖 LLM）。"""

from __future__ import annotations

from pathlib import Path

import yaml

from dnd.gm.broker import _execute_payload
from dnd.gm.parser import GMBeatPayload
from dnd.store import SessionStore


def _write_player(path: Path) -> None:
    payload = {
        "name": "艾莉丝",
        "abilities": {"str": 10, "dex": 14, "con": 12, "int": 10, "wis": 12, "cha": 10},
        "skills": {"stealth": 5},
        "hp_current": 4,
        "hp_max": 10,
        "inventory": [{"id": "potion_of_healing", "name": "治疗药水", "count": 1}],
    }
    path.write_text(yaml.dump(payload, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding="utf-8")


def test_execute_payload_skill_use_item_and_spawn(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    record = store.create_session(stream_id="g1", title="测试战役", creator_id="u1")
    store.add_enrolled(record.session_id, stream_id="g1", user_id="alice")
    _write_player(record.root / "players" / "alice.yaml")

    payload = GMBeatPayload(
        narration="艾莉丝在阴影中搜索，并找到一瓶药水。",
        mechanics=[
            {"kind": "skill_check", "actor": "alice", "skill": "stealth", "dc": 12},
            {"kind": "spawn_item", "item": {"id": "rusty_key", "name": "生锈的钥匙"}, "give_to": "alice"},
            {"kind": "use_item", "actor": "alice", "item_id": "potion_of_healing"},
        ],
        feedback=[],
        turn_advance={"to": "alice"},
        scene_state_patch="新增：暗门钥匙已入手。",
        honored_ids=["m1"],
    )

    result = _execute_payload(record, payload)

    assert len(result.mechanics_results) == 3
    assert len(result.roll_entries) == 2
    assert result.roll_entries[0]["kind"] == "skill_check"
    assert result.roll_entries[1]["kind"] == "use_item_heal"

    updated = yaml.safe_load((record.root / "players" / "alice.yaml").read_text(encoding="utf-8"))
    assert isinstance(updated, dict)
    assert int(updated["hp_current"]) == 10
    inventory = updated.get("inventory", [])
    assert isinstance(inventory, list)
    item_ids = {str(item.get("id") or "") for item in inventory if isinstance(item, dict)}
    assert "rusty_key" in item_ids
    assert "potion_of_healing" not in item_ids
