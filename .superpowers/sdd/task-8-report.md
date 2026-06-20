# Task 8 Report — GM parser + context builder

**Status:** DONE

## Summary

### GM parser (`dnd/gm/parser.py`)

- `DND_BEAT_JSON_MARKER = "===DND_BEAT_JSON==="`
- `GMBeatPayload` frozen dataclass: `narration`, `mechanics`, `feedback`, `turn_advance`, `scene_state_patch`, `honored_ids`
- `parse_gm_response(text)` — splits on delimiter, parses JSON, maps `honored` → `honored_ids`; merges optional preamble into `narration`; raises `ValueError` on missing marker or invalid JSON (no silent fallbacks)

### GM context builder (`dnd/gm/context.py`)

- `build_gm_messages(session, inbox, config) -> list[dict[str, str]]` — returns `[system, user]` messages for `ctx.llm.generate`
- Context sections in spec priority order (high → low):
  1. GM system prompt (base rules + `gm-prompt.md`)
  2. `state/scene-state.md`
  3. Player snapshots + turn summary (`active_player`, initiative)
  4. Bible excerpts (`world.md`, `plot-outline.md`)
  5. Dictionary hits from `bible/dictionary.json` matched against inbox text
  6. Recent beats from `journal/beats.jsonl` (limit from `config.session.recent_beats_limit`)
  7. Pending inbox with turn tags (`is_active`, `initiative_distance`, `ooc`)
- Char budget: `max(2000, gm_context_char_budget)` minus user prompt overhead; clips lowest-priority sections first, then truncates highest-priority block with `……（略）` suffix

### Package (`dnd/gm/__init__.py`)

Exports parser and context public API.

### Tests (`tests/test_gm_parser.py`)

- Plan sample parse test (`test_parse_gm_block`)
- Parse error cases (missing marker, invalid JSON)
- Context assembly includes core sections
- Clipping drops inbox before higher-priority bible/scene content at tight budget
- Dictionary term matching from inbox text

## Test output

```
$ cd /mnt/klein/work/maibot-plugins/maibot-dnd-plugin && PYTHONPATH=.:../maibot-plugin-sdk pytest tests/test_gm_parser.py -v
============================== 6 passed in 0.07s ===============================
```

## Commit

`feat(dnd): add GM response parser and context builder`

## Follow-ups (Task 9)

- `dnd/gm/broker.py` will call `build_gm_messages` + `parse_gm_response` in the beat pipeline
- Parse retry with repair prompt on failure
- Mechanics execution + journal persistence wired from `GMBeatPayload`
