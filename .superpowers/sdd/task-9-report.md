# Task 9 Report — GM broker beat pipeline

**Status:** DONE

## Summary

### GMBroker (`dnd/gm/broker.py`)

- Added `run_beat(ctx, plugin_instance, session, inbox, config, reason="proceed") -> BeatResult`
- Beat pipeline now performs:
  1. Build messages via `build_gm_messages`
  2. `ctx.llm.generate(prompt=..., model=config.session.gm_model)`
  3. Parse with `parse_gm_response`; on parse error, retry once with repair prompt enforcing `===DND_BEAT_JSON===`
  4. Execute mechanics intents through `_execute_payload`
  5. Broadcast narration + roll summaries + feedback with `broadcast_gm`
  6. Persist `journal/beats.jsonl` + `journal/rolls.jsonl`
  7. Apply `scene_state_patch` to `state/scene-state.md`, update `session.toml` active player and `state/turn.yaml`
  8. If new active player equals plugin `._mai_person_id`, trigger `wake_mai_turn`
- Added processing result dataclasses:
  - `BeatResult`
  - `ExecutionResult`

### Mechanics items (`dnd/mechanics/items.py`)

- Added minimal item catalog:
  - `potion_of_healing` with heal effect `2d4+2`
- Added item operations:
  - `execute_use_item(session_root, intent)`:
    - Validates inventory
    - Applies heal effect to `players/<actor>.yaml`
    - Decrements/consumes item
  - `execute_spawn_item(session_root, intent)`:
    - Spawn to player inventory (`give_to`) or to `state/scene-items.yaml`
- Exported in `dnd/mechanics/__init__.py`

### TurnCoordinator flush wiring

- `dnd/turn/coordinator.py` now supports async flush callback:
  - `set_flush_callback(...)`
  - `dispatch_flush(reason, flushed)`
  - debounce auto-flush now dispatches callback
  - `requeue(messages)` restores inbox on beat failure
- `plugin.py` now wires coordinator flush to broker:
  - Added `_handle_flush(...)`
  - `/dnd proceed` and `/dnd skip` call `coordinator.dispatch_flush(...)` instead of Task 7 stub
  - On beat error: explicit error broadcast + inbox requeue + processing lock release

### Test (`tests/test_broker.py`)

- Added `test_execute_payload_skill_use_item_and_spawn`
- Uses fixed `GMBeatPayload` and runs `_execute_payload` directly (no LLM)
- Verifies:
  - skill check + heal roll entries produced
  - heal updates HP
  - spawn item goes to inventory
  - consumed healing potion is removed

## Test output

```text
$ cd /mnt/klein/work/maibot-plugins/maibot-dnd-plugin && PYTHONPATH=.:../maibot-plugin-sdk pytest -v
============================== 35 passed in 0.18s ===============================
```

## Commit

`feat(dnd): add GM beat pipeline`
