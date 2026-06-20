# Task 6 Report — TurnCoordinator + play commands

**Status:** DONE

## Context

Task 5 (permissions + lifecycle) was not yet committed when Task 6 started. Both were implemented together in one changeset to avoid conflicts with `SessionStore` and `plugin.py`.

## Summary

### Turn layer (`dnd/turn/`)

- `inbox.py` — `InboxMessage` dataclass (`player_id`, `text`, `is_active`, `initiative_distance`, `ooc`); `Inbox` with `append` / `drain` / `peek`
- `coordinator.py` — `TurnCoordinator`:
  - Debounce only after `on_active_player_message` from the active player; resets on repeat; no debounce for off-turn messages
  - `request_proceed()` / `request_skip()` / `flush(reason)` with `processing` lock
  - `complete_processing()` to release lock (beat stub in plugin until Task 9)
  - Auto-flush on debounce timeout via `asyncio` task

### Session layer (Task 5, bundled)

- `permissions.py` — `can(user_id, action, session, …)` per design matrix; `open_mode` grants lifecycle admin but still requires enrollment for `proceed`
- `lifecycle.py` — `LifecycleService` for new/list/start/stop/restart/handoff/join/leave/turn state
- `store.py` — enrolled list, turn state (`active_player`, `initiative`), `find_active_session`, `ensure_turn_state`

### Plugin commands (`plugin.py`)

**Lifecycle:** `/dnd new`, `list`, `status`, `start`, `stop`, `restart`, `handoff`

**Play:** `/dnd join`, `leave`, `proceed`, `turn`, `skip`, `ooc`

- Per-stream `TurnCoordinator` instances keyed by `stream_id`
- `/dnd start` runs readiness gates; on pass sets `running`, seeds initiative, opens coordinator
- `/dnd proceed` / `skip` flush inbox with busy guard while `processing`
- Beat pipeline stub logs and calls `complete_processing()` (GM broker deferred to Task 9)

### Tests

- `tests/test_turn.py` — plan debounce tests plus tagging, flush lock, busy proceed, timeout auto-flush
- `tests/test_permissions.py` — permission matrix (Task 5)
- `tests/conftest.py` — `anyio_backend = asyncio` (trio not installed)

## Test output

```
$ cd /mnt/klein/work/maibot-plugins/maibot-dnd-plugin && PYTHONPATH=.:../maibot-plugin-sdk pytest tests/ -v
============================== 24 passed in 0.16s ==============================
```

## Concerns / follow-ups

- Debounce auto-flush calls `flush()` internally but does not yet invoke GMBroker (Task 9); plugin only stubs beat completion on manual `proceed`/`skip`
- Message capture hooks (Task 10) will call `append` + `on_active_player_message` for enrolled player chat
- Broadcast layer (Task 7) will replace raw `ctx.send.text` in `_send` / opening beat stub
