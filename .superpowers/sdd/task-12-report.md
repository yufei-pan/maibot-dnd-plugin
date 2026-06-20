# Task 12 Report — Play tools + lookup commands

**Status:** DONE

## Summary

### Play module (`dnd/play.py`)

- `query_bible(session_root, topic)` — read `bible/<topic>.md` or `bible/rules/<topic>.md`; empty topic lists available stems
- `query_log(session_root, limit=20)` — tail `journal/rolls.jsonl` with broker roll-line formatting
- `execute_roll(...)` — free formula via `roll_formula`, or skill check via `MechanicsEngine`
- `format_sheet(session_root, player_id)` — raw YAML character sheet
- `query_map(session_root, map_name)` — list/read map Markdown stub (PNG render deferred to Task 13 wiring)

### Plugin wiring (`plugin.py`)

**Shared helpers:**

- `_tool_play_session(kwargs, require_running=False)` — active session + enrollment gate
- `_dispatch_proceed(stream_id, record)` — `TurnCoordinator.request_proceed()` + flush (used by command and tool)

**Tools (enrolled):**

| Tool | Purpose |
|---|---|
| `dnd_proceed` | Manual GM beat advance |
| `dnd_query_bible` | Bible/rules retrieval |
| `dnd_query_log` | Recent roll log |
| `dnd_roll` | Formula roll or skill check |

**Commands:**

| Command | Maps to |
|---|---|
| `/dnd card` | Existing render path (`render_card` + Markdown fallback) |
| `/dnd sheet [player_id]` | `format_sheet` |
| `/dnd roll [formula]` | `execute_roll` (enrolled) |
| `/dnd log` | `query_log` (enrolled) |
| `/dnd map [name]` | `query_map` text stub |

`/dnd proceed` command refactored to share `_dispatch_proceed` with `dnd_proceed` tool.

### Tests (`tests/test_play_tools.py`)

- Formula roll offline with injected RNG
- Skill check via `MechanicsEngine` with fixed d20
- Bible topic read + list
- Roll log JSONL read

## Test output

```text
$ cd /mnt/klein/work/maibot-plugins/maibot-dnd-plugin && PYTHONPATH=.:../maibot-plugin-sdk pytest -v
============================== 63 passed in 0.23s ===============================
```

## Commit

`feat(dnd): add play tools and lookup commands`
