# Task 2 Report — SessionStore + path helpers

**Status:** DONE

**Commit:** `bb1c2adf45bb9943fc82fc9787c8703612fb00dc`

## Summary

Added filesystem session persistence layer:

- `dnd/paths.py` — `_safe_component`, `_safe_stream_dir`, `session_dir`, `_atomic_write` (patterns from maibook-plugin)
- `dnd/store.py` — `SessionRecord` dataclass, `SessionStore` with `create_session`, `load_session`, `write_text`, `append_jsonl`
- `tests/test_store.py` — layout scaffold + load round-trip test

`create_session` scaffolds `bible/`, `state/`, `journal/`, `summaries/`, `players/`, empty bible stems, `dictionary.json`, `gm-prompt.md`, `state/scene-state.md` (heading only), and `session.toml` with `status=setup`.

## Test output

```
$ cd /mnt/klein/work/maibot-plugins/maibot-dnd-plugin && PYTHONPATH=.:../maibot-plugin-sdk pytest tests/test_store.py -v
============================= test session starts ==============================
platform linux -- Python 3.13.5, pytest-8.3.5, pluggy-1.5.0 -- /usr/bin/python3
cachedir: .pytest_cache
rootdir: /mnt/klein/work/maibot-plugins/maibot-dnd-plugin
plugins: typeguard-4.4.2, anyio-4.8.0
collecting ... collected 1 item

tests/test_store.py::test_create_session_layout PASSED                   [100%]

============================== 1 passed in 0.02s ===============================
```

Exit code: 0

## Concerns

- None blocking Task 3.
