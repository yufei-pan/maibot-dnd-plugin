"""物品目录与最小物品效果执行。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from dnd.mechanics.dice import RollRng, RollResult, roll_formula
from dnd.mechanics.sheets import CharacterSheet

DEFAULT_ITEM_CATALOG: dict[str, dict[str, Any]] = {
    "potion_of_healing": {
        "id": "potion_of_healing",
        "name": "治疗药水",
        "effects": [{"kind": "heal", "formula": "2d4+2"}],
    }
}


def _load_player_doc(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"角色卡不存在: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"角色卡格式错误（根节点必须是映射）: {path}")
    return dict(raw)


def _write_player_doc(path: Path, data: Mapping[str, Any]) -> None:
    text = yaml.dump(dict(data), allow_unicode=True, sort_keys=False, default_flow_style=False)
    path.write_text(text, encoding="utf-8")


def _inventory_list(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = doc.get("inventory", [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("角色卡 inventory 必须是数组")
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("角色卡 inventory 元素必须是对象")
        normalized.append(dict(item))
    return normalized


def _save_inventory(doc: dict[str, Any], inventory: list[dict[str, Any]]) -> None:
    doc["inventory"] = inventory


def _resolve_item_catalog_entry(item_id: str, embedded_item: Mapping[str, Any] | None) -> dict[str, Any]:
    base = DEFAULT_ITEM_CATALOG.get(item_id, {"id": item_id, "name": item_id, "effects": []})
    merged = dict(base)
    if embedded_item is not None:
        merged.update(dict(embedded_item))
    effects = merged.get("effects")
    if effects is None:
        merged["effects"] = []
        return merged
    if not isinstance(effects, list):
        raise ValueError("物品 effects 必须是数组")
    return merged


def execute_use_item(
    session_root: Path,
    intent: Mapping[str, Any],
    *,
    rng: RollRng | None = None,
) -> tuple[dict[str, Any], RollResult | None]:
    actor = str(intent.get("actor") or "").strip()
    item_id = str(intent.get("item_id") or "").strip()
    if not actor:
        raise ValueError("use_item 缺少 actor")
    if not item_id:
        raise ValueError("use_item 缺少 item_id")

    player_path = session_root / "players" / f"{actor}.yaml"
    doc = _load_player_doc(player_path)
    inventory = _inventory_list(doc)

    target_idx = -1
    entry: dict[str, Any] | None = None
    for idx, item in enumerate(inventory):
        if str(item.get("id") or "").strip() == item_id:
            target_idx = idx
            entry = item
            break
    if target_idx < 0 or entry is None:
        raise ValueError(f"角色 {actor} 不持有物品 {item_id}")

    count = entry.get("count", 1)
    if not isinstance(count, int) or count <= 0:
        raise ValueError(f"角色 {actor} 的物品 {item_id} 数量无效")

    catalog_entry = _resolve_item_catalog_entry(item_id, entry)
    effects = catalog_entry.get("effects", [])
    if not isinstance(effects, list):
        raise ValueError("物品 effects 必须是数组")

    sheet = CharacterSheet.from_yaml(yaml.dump(doc, allow_unicode=True, sort_keys=False, default_flow_style=False))
    roll: RollResult | None = None
    healed = 0
    for effect in effects:
        if not isinstance(effect, dict):
            raise ValueError("effect 必须是对象")
        kind = str(effect.get("kind") or "").strip()
        if kind == "heal":
            formula = str(effect.get("formula") or "").strip()
            if not formula:
                raise ValueError("heal effect 缺少 formula")
            roll = roll_formula(formula, rng=rng)
            healed = roll.total
            sheet.hp_current = min(sheet.hp_max, sheet.hp_current + healed)

    doc["hp_current"] = sheet.hp_current
    doc["hp_max"] = sheet.hp_max

    new_count = count - 1
    if new_count <= 0:
        inventory.pop(target_idx)
    else:
        entry["count"] = new_count
        inventory[target_idx] = entry
    _save_inventory(doc, inventory)
    _write_player_doc(player_path, doc)

    return {
        "kind": "use_item",
        "actor": actor,
        "item_id": item_id,
        "item_name": str(catalog_entry.get("name") or item_id),
        "healed": healed,
        "hp_current": sheet.hp_current,
        "hp_max": sheet.hp_max,
    }, roll


def execute_spawn_item(session_root: Path, intent: Mapping[str, Any]) -> dict[str, Any]:
    raw_item = intent.get("item")
    if not isinstance(raw_item, dict):
        raise ValueError("spawn_item 缺少 item 对象")
    item_id = str(raw_item.get("id") or "").strip()
    if not item_id:
        raise ValueError("spawn_item.item.id 不能为空")

    give_to = str(intent.get("give_to") or "").strip()
    spawned = dict(raw_item)

    if give_to:
        player_path = session_root / "players" / f"{give_to}.yaml"
        doc = _load_player_doc(player_path)
        inventory = _inventory_list(doc)
        target_idx = -1
        for idx, existing in enumerate(inventory):
            if str(existing.get("id") or "").strip() == item_id:
                target_idx = idx
                break
        if target_idx >= 0:
            current = inventory[target_idx]
            count = current.get("count", 1)
            if not isinstance(count, int) or count <= 0:
                raise ValueError(f"角色 {give_to} 物品 {item_id} 的 count 非法")
            current["count"] = count + 1
            inventory[target_idx] = current
        else:
            new_item = dict(spawned)
            new_item["count"] = 1
            inventory.append(new_item)
        _save_inventory(doc, inventory)
        _write_player_doc(player_path, doc)
        return {"kind": "spawn_item", "item_id": item_id, "item_name": str(spawned.get("name") or item_id), "give_to": give_to}

    scene_items_path = session_root / "state" / "scene-items.yaml"
    current_items: list[dict[str, Any]]
    if scene_items_path.is_file():
        loaded = yaml.safe_load(scene_items_path.read_text(encoding="utf-8"))
        if loaded is None:
            loaded = []
        if not isinstance(loaded, list):
            raise ValueError("scene-items.yaml 根节点必须是数组")
        current_items = []
        for item in loaded:
            if not isinstance(item, dict):
                raise ValueError("scene-items.yaml 元素必须是对象")
            current_items.append(dict(item))
    else:
        current_items = []
    current_items.append(spawned)
    scene_items_path.write_text(
        yaml.dump(current_items, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return {"kind": "spawn_item", "item_id": item_id, "item_name": str(spawned.get("name") or item_id), "give_to": ""}
