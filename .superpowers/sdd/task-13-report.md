# Task 13 Report — Character card + map rendering

**Status:** DONE

## Summary

### Assets

- `assets/character_card.html` — parchment-style character card (name, HP, abilities with modifiers, skills, optional mugshot)
- `assets/map.html` — parchment-style map display (title, body text, optional legend)

### Render module (`dnd/render.py`)

| Function | Purpose |
|---|---|
| `load_template(plugin_dir, filename)` | Load HTML template from `assets/` |
| `load_character_sheet(session_root, player_id)` | Read YAML sheet + optional `mugshot` path |
| `build_card_html(template, sheet, ...)` | Render character card HTML fragment |
| `build_map_html(template, title, body, ...)` | Render map HTML fragment |
| `build_card_markdown(sheet, ...)` | Markdown fallback when PNG render fails |
| `render_card(ctx, html_fragment)` | `ctx.render.html2png` with `#card`, `device_scale_factor=1.0` |
| `render_map(ctx, html_fragment)` | `ctx.render.html2png` with `#map`, `device_scale_factor=1.0` |

Mugshot: optional `mugshot:` field in `players/<id>.yaml` (path relative to session root); embedded as data URI when file exists, otherwise first-letter placeholder.

### Plugin wiring (`plugin.py`)

- `/dnd card [player_id]` — loads target sheet (default: caller), renders PNG via Host; on failure sends Markdown fallback with notice

### Tests (`tests/test_render.py`)

- Offline HTML contains character name, HP, ability modifiers, skills
- Map HTML contains title/body/legend
- Mugshot path loading and base64 embed when file exists
- Markdown fallback contains name/HP

## Test output

```text
$ cd /mnt/klein/work/maibot-plugins/maibot-dnd-plugin && PYTHONPATH=.:../maibot-plugin-sdk pytest -v
tests/test_render.py — 6 passed
Total: 58 passed, 1 failed (pre-existing: tests/test_broker.py::test_execute_payload_skill_use_item_and_spawn)
```

## Commit

`feat(dnd): add character card and map rendering`
