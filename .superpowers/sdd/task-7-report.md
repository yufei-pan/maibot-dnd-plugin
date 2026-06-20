# Task 7 Report — Broadcast layer

**Status:** DONE

## Summary

Implemented Maisaka-sync broadcast helpers in `dnd/broadcast.py`:

- `broadcast_gm(ctx, stream_id, text, cfg)` — `【地下城·GM】` prefix, `maisaka_source_kind=plugin:dnd-gm`
- `broadcast_system(ctx, stream_id, text, cfg)` — `【地下城】` prefix, `maisaka_source_kind=plugin:dnd`
- `wake_mai_turn(ctx, stream_id, text, intent, reason, metadata, cfg)` — public system broadcast + `maisaka.proactive.trigger`

Shared `_broadcast_text` uses `cfg.broadcast.sync_to_maisaka_history` on every `ctx.send.text` call. On send failure: logs warning and explicitly falls back to `ctx.maisaka.context.append` (not silent).

### Plugin wiring

- `plugin.py` `_send()` now delegates to `broadcast_system()` so all command replies get prefix + sync + fallback behavior.

### Tests

- `tests/test_broadcast.py` — mock ctx verifies `sync_to_maisaka_history=True`, prefix application, send-failure fallback, and `wake_mai_turn` proactive trigger.

## Test output

```
$ cd /mnt/klein/work/maibot-plugins/maibot-dnd-plugin && PYTHONPATH=.:../maibot-plugin-sdk pytest tests/test_broadcast.py -v
============================== 4 passed in 0.09s ===============================

$ PYTHONPATH=.:../maibot-plugin-sdk pytest tests/ -v
============================== 28 passed in 0.16s ==============================
```

## Concerns / follow-ups

- Task 9 GMBroker will call `broadcast_gm` for narration/rolls and `wake_mai_turn` when active player is bot person.
- Opening beat stub still uses system channel via `_send` → `broadcast_system`; GM narration awaits Task 9.
