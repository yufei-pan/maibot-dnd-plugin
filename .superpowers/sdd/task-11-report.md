# Task 11 Report — Setup tools + bible/dictionary/rulebook

**Status:** DONE

## Summary

### Setup module (`dnd/setup.py`)

- Added `write_bible(session_root, topic, content, mode)` — maibook-style append/replace via `_atomic_write`
- Added `write_gm_prompt`, `write_character_sheet`, `dict_set`, `dict_query`, `review_ready`, `spawn_item`
- Added rulebook import pipeline:
  - `fetch_rulebook_text(url, max_bytes)` — httpx streaming fetch with size cap
  - `parse_rulebook_split(response)` — parses `===DND_RULEBOOK_JSON===` + JSON topics
  - `write_rulebook_topics` → `bible/rules/<topic>.md`
  - `import_rulebook(llm_generate, ...)` — fetch → `ctx.llm.generate` split → write rules files

### Config

- Added `session.rulebook_import_max_bytes` (default 5 MiB) for rulebook URL fetch cap

### Plugin wiring (`plugin.py`)

**Tools (creator/admin via `setup` permission):**

| Tool | Purpose |
|---|---|
| `dnd_setup_bible` | Write/append `bible/<topic>.md` |
| `dnd_setup_gm_prompt` | Write/append `gm-prompt.md` |
| `dnd_setup_character` | Write/merge `players/<id>.yaml` |
| `dnd_import_rulebook` | URL → LLM split → `bible/rules/` |
| `dnd_dict_set` | Add dictionary entry |
| `dnd_dict_query` | Query dictionary (any user with active session) |
| `dnd_review_ready` | Gate A+B readiness checklist |
| `dnd_spawn_item` | Spawn item to player or scene |

**Commands:**

| Command | Maps to |
|---|---|
| `/dnd bible [append\|replace] <topic> <content>` | `write_bible` |
| `/dnd gm-prompt [append\|replace] <content>` | `write_gm_prompt` |
| `/dnd review` | `review_ready` |
| `/dnd import-rules <url>` | `import_rulebook` |
| `/dnd dict [term]` | `dict_query` |
| `/dnd dict set <term> <explanation>` | `dict_set` |

### Tests (`tests/test_setup.py`)

- Bible replace / append / empty-content rejection
- Dictionary set + query round-trip
- Rulebook split parse + topic file write
- Missing marker error case

## Test output

```text
$ cd /mnt/klein/work/maibot-plugins/maibot-dnd-plugin && PYTHONPATH=.:../maibot-plugin-sdk pytest -v
============================== 41 passed in 0.24s ===============================
```

## Commit

`feat(dnd): add setup tools and bible commands`
