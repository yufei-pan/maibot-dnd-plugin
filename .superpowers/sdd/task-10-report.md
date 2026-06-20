# Task 10 Report — HookHandlers player capture + Mai injection

**Status:** DONE

## Summary

### Hooks helper (`dnd/hooks.py`)

- Added reusable helper functions for Task 10 hook/event flow:
  - `is_running(status)`
  - `resolve_stream_id(kwargs)`
  - `resolve_user_id(kwargs)`
  - `extract_plain_text(message, kwargs)`
  - `load_scene_brief(session_root)`
  - `load_character_name(session_root, player_id)`
  - `build_player_briefing(character_name, scene_brief)`
- Helpers are designed to be testable offline without Host runtime.

### Plugin wiring (`plugin.py`)

- Added `@HookHandler("maisaka.replyer.after_response")`:
  - When session is `running` and bot person is enrolled, appends reply text to `TurnCoordinator` inbox.
  - Calls active-player debounce logic only when bot is current active player.
- Added `@HookHandler("maisaka.replyer.before_model_request")`:
  - When session is `running` and bot is enrolled, injects one `user` message briefing after the last `system` message.
  - Briefing includes bot character name (`players/<person_id>.yaml`) and scene brief (`state/scene-state.md`).
- Added `@EventHandler(... EventType.ON_MESSAGE)`:
  - Captures inbound messages from enrolled human players while session is `running`.
  - Appends text to inbox and triggers active-player debounce when applicable.
  - Ignores `/dnd ...` commands and bot-self messages.

### Tests

- Added `tests/test_hooks.py` for offline helper coverage:
  - running-state判定
  - stream/user 解析
  - plain text 提取
  - scene brief 读取与标题剥离
  - character name 读取
  - briefing 文案生成

### README

- Added `README.md` stub and a manual Hook test checklist section for Host-side verification.
