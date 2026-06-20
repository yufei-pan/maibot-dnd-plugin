# maibot-dnd-plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a MaiBot first-party plugin that runs adjudicated-mechanics D&D sessions in group chat with a dedicated GM LLM, soft-turn batching, and MaiBot as an enrolled NL player.

**Architecture:** Single plugin (`maibot-dnd-plugin`) with focused modules under `dnd/`: SessionStore (filesystem), MechanicsEngine (pure Python), TurnCoordinator (inbox/debounce), GMBroker (isolated LLM beats), Broadcast (send + sync_to_maisaka_history). `plugin.py` wires SDK decorators only.

**Tech Stack:** Python ≥3.10, `maibot-plugin-sdk` (import `maibot_sdk`), `tomli`/`tomli-w`, `httpx`, `pyyaml`, stdlib `secrets` for dice. Tests via `pytest` + offline `smoke_test.py`. Reference: `maibook-plugin`, `maibot-impression-card-plugin`.

## Global Constraints

- Plugin id: `maibot-dnd-plugin`; manifest id e.g. `com.0-hz.maibot-dnd`
- User-facing text: 简体中文
- No silent fallbacks (不要兜底)
- No Host/SDK source edits for v1
- Use `@Tool`, `@Command`, `@HookHandler`; not `@Action`
- Required lifecycle: `on_load`, `on_unload`, `on_config_update`, `create_plugin`
- GM dice/stats: plugin code only, never LLM numbers
- `ctx.send.text(..., sync_to_maisaka_history=True)` for all GM/system broadcasts
- Tests: `PYTHONPATH=.:../maibot-plugin-sdk pytest -v` from plugin dir
- Line length 120 if using ruff

---

## File map (created across tasks)

| Path | Responsibility |
|---|---|
| `plugin.py` | `DndPlugin(MaiBotPlugin)`, decorators, `create_plugin()` |
| `dnd/config.py` | `DndConfig`, migration, `CURRENT_CONFIG_VERSION = "0.1.0"` |
| `dnd/paths.py` | `_safe_stream_dir`, `_safe_component`, session paths |
| `dnd/store.py` | `SessionStore` read/write session.toml, bible, yaml, jsonl |
| `dnd/mechanics/dice.py` | `roll_formula(formula: str) -> RollResult` |
| `dnd/mechanics/sheets.py` | `CharacterSheet` dataclass, validation gate B |
| `dnd/mechanics/items.py` | Item catalog + inventory ops |
| `dnd/mechanics/engine.py` | `MechanicsEngine.apply(intent: dict) -> list[MechanicsOutcome]` |
| `dnd/session/permissions.py` | `can(actor, action, session) -> bool` |
| `dnd/session/readiness.py` | `campaign_missing()`, `player_missing()` |
| `dnd/session/lifecycle.py` | create/stop/restart/start state transitions |
| `dnd/turn/inbox.py` | `InboxMessage`, tagging by active/initiative |
| `dnd/turn/coordinator.py` | debounce, proceed, processing lock |
| `dnd/gm/parser.py` | parse GM JSON block from LLM output |
| `dnd/gm/context.py` | build GM prompt messages with budget |
| `dnd/gm/broker.py` | `run_beat(...) -> BeatResult` |
| `dnd/broadcast.py` | `broadcast_gm`, `broadcast_system`, `wake_mai_turn` |
| `assets/character_card.html` | Card template |
| `assets/map.html` | Map template |
| `tests/*.py` | Unit tests |
| `tests/smoke_test.py` | Offline load + migration smoke |

---

### Task 1: Plugin scaffold + config migration

**Files:**
- Create: `maibot-dnd-plugin/_manifest.json`
- Create: `maibot-dnd-plugin/config.default.toml`
- Create: `maibot-dnd-plugin/.gitignore`
- Create: `maibot-dnd-plugin/dnd/__init__.py`
- Create: `maibot-dnd-plugin/dnd/config.py`
- Create: `maibot-dnd-plugin/plugin.py` (minimal lifecycle stub)
- Create: `maibot-dnd-plugin/tests/smoke_test.py`
- Test: `maibot-dnd-plugin/tests/smoke_test.py`

**Interfaces:**
- Produces: `CURRENT_CONFIG_VERSION`, `DndConfig`, `_normalize_dnd_config()`, `create_plugin() -> DndPlugin`

- [ ] **Step 1: Write failing smoke test**

```python
# tests/smoke_test.py
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR))
sys.path.insert(0, str(PLUGIN_DIR.parent / "maibot-plugin-sdk"))

import plugin as dnd_plugin


def test_create_plugin_and_config_version() -> None:
    inst = dnd_plugin.create_plugin()
    assert inst.plugin_id == "maibot-dnd-plugin"
    cfg = dnd_plugin.DndConfig()
    assert cfg.plugin.config_version == "0.1.0"


if __name__ == "__main__":
    test_create_plugin_and_config_version()
    print("ok")
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd maibot-dnd-plugin && PYTHONPATH=.:../maibot-plugin-sdk python tests/smoke_test.py`

- [ ] **Step 3: Add manifest, config, minimal plugin.py**

`_manifest.json` capabilities (minimum v1):
`config.get`, `llm.generate`, `send.text`, `send.image`, `render.html2png`, `maisaka.context.append`, `maisaka.proactive.trigger`, `person.get_id`

Dependencies: `tomli`, `tomli-w`, `httpx`, `pyyaml`

`plugin.py` skeleton:

```python
from maibot_sdk import MaiBotPlugin, PluginConfigBase
from dnd.config import CURRENT_CONFIG_VERSION, DndConfig, _normalize_dnd_config

class DndPlugin(MaiBotPlugin):
    plugin_id = "maibot-dnd-plugin"
    config_model = DndConfig

    async def on_load(self) -> None:
        self.ctx.logger.info("地下城插件已加载")

    async def on_unload(self) -> None:
        self.ctx.logger.info("地下城插件已卸载")

    async def on_config_update(self, scope, config_data, version) -> None:
        merged, _, notes = _normalize_dnd_config(config_data, DndConfig().model_dump(mode="python"))
        if notes:
            self.ctx.logger.info("配置迁移: %s", "; ".join(notes))

def create_plugin() -> DndPlugin:
    return DndPlugin()
```

- [ ] **Step 4: Run smoke test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(dnd): scaffold plugin with config migration"
```

---

### Task 2: SessionStore + path helpers

**Files:**
- Create: `maibot-dnd-plugin/dnd/paths.py`
- Create: `maibot-dnd-plugin/dnd/store.py`
- Create: `maibot-dnd-plugin/tests/test_store.py`

**Interfaces:**
- Produces:
  - `session_dir(data_root: Path, stream_id: str, session_id: str) -> Path`
  - `SessionStore.load_session(path) -> SessionRecord`
  - `SessionStore.write_text(path, text)`, `append_jsonl(path, obj)`
  - `SessionRecord.status: str` — `setup|ready|running|stopped`

- [ ] **Step 1: Write failing test**

```python
# tests/test_store.py
from pathlib import Path
from dnd.store import SessionStore

def test_create_session_layout(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    rec = store.create_session(stream_id="g1", title="Test Campaign", creator_id="u1")
    assert rec.status == "setup"
    assert (rec.root / "bible" / "world.md").exists()
    assert (rec.root / "session.toml").exists()
    loaded = store.load_session(rec.session_id, stream_id="g1")
    assert loaded.creator_id == "u1"
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd maibot-dnd-plugin && PYTHONPATH=.:../maibot-plugin-sdk pytest tests/test_store.py -v`

- [ ] **Step 3: Implement paths.py + store.py**

Copy `_safe_stream_dir` / `_atomic_write` patterns from `maibook-plugin/plugin.py`. On create, scaffold empty bible files and `state/scene-state.md` with heading only.

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

---

### Task 3: MechanicsEngine — dice + skill checks

**Files:**
- Create: `maibot-dnd-plugin/dnd/mechanics/dice.py`
- Create: `maibot-dnd-plugin/dnd/mechanics/engine.py`
- Create: `maibot-dnd-plugin/tests/test_dice.py`

**Interfaces:**
- Produces:
  - `RollResult(dice: list[int], modifier: int, total: int, formula: str)`
  - `roll_formula(formula: str, rng=None) -> RollResult`
  - `MechanicsEngine.execute(intent: dict, sheets: dict[str, CharacterSheet]) -> MechanicsOutcome`

- [ ] **Step 1: Write failing dice tests**

```python
import re
from dnd.mechanics.dice import roll_formula

def test_roll_d20_plus_mod() -> None:
    r = roll_formula("1d20+5", rng=lambda n, m: 12)  # inject fixed die
    assert r.total == 17
    assert r.formula == "1d20+5"

def test_advantage_takes_higher() -> None:
    from dnd.mechanics.engine import MechanicsEngine
    from dnd.mechanics.sheets import CharacterSheet

    sheet = CharacterSheet(name="A", abilities={"wis": 14}, skills={"perception": 5}, hp_current=10, hp_max=10)
    engine = MechanicsEngine()
    outcome = engine.execute(
        {"kind": "skill_check", "actor": "a1", "skill": "perception", "dc": 13, "advantage": True},
        {"a1": sheet},
        rng=lambda n, m: 10,
    )
    assert outcome.success is True
    assert outcome.roll.total >= 15
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement dice parser**

Support `NdM`, optional `+/-` modifier, advantage/disadvantage on d20 checks. Use `secrets.randbelow` by default.

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

---

### Task 4: Character sheets + readiness gates

**Files:**
- Create: `maibot-dnd-plugin/dnd/mechanics/sheets.py`
- Create: `maibot-dnd-plugin/dnd/session/readiness.py`
- Create: `maibot-dnd-plugin/tests/test_readiness.py`

**Interfaces:**
- Produces:
  - `CharacterSheet.from_yaml(text) -> CharacterSheet`
  - `character_sheet_missing(sheet: CharacterSheet | None, ability_keys: list[str]) -> list[str]`
  - `campaign_readiness(session_root: Path) -> list[str]`
  - `session_readiness(session_root, enrolled_ids, ability_keys) -> list[str]`

- [ ] **Step 1: Write failing readiness tests**

```python
from pathlib import Path
from dnd.session.readiness import campaign_readiness, character_sheet_missing
from dnd.mechanics.sheets import CharacterSheet

def test_character_gate_b() -> None:
    ok = CharacterSheet(name="Li", abilities={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
                        skills={"athletics": 2}, hp_current=8, hp_max=8)
    assert character_sheet_missing(ok, ["str","dex","con","int","wis","cha"]) == []

    bad = CharacterSheet(name="Li", abilities={"str": 10}, skills={}, hp_current=0, hp_max=0)
    assert "HP" in " ".join(character_sheet_missing(bad, ["str","dex","con","int","wis","cha"]))

def test_campaign_gate_a(tmp_path: Path) -> None:
    (tmp_path / "bible").mkdir()
    (tmp_path / "bible" / "world.md").write_text("sky islands", encoding="utf-8")
    missing = campaign_readiness(tmp_path)
    assert any("plot-outline" in m for m in missing)
```

- [ ] **Step 2–4: Implement + pass**

Required bible stems: `world`, `plot-outline`, `characters`; plus non-empty `gm-prompt.md`.

- [ ] **Step 5: Commit**

---

### Task 5: Permissions + session lifecycle commands

**Files:**
- Create: `maibot-dnd-plugin/dnd/session/permissions.py`
- Create: `maibot-dnd-plugin/dnd/session/lifecycle.py`
- Modify: `maibot-dnd-plugin/plugin.py` — add lifecycle `@Command`s
- Create: `maibot-dnd-plugin/tests/test_permissions.py`

**Interfaces:**
- Produces:
  - `can(user_id, action: str, session, config, enrolled: set[str]) -> bool`
  - `LifecycleService.new/start/stop/restart/handoff(...)`

Commands to wire in this task:
`/dnd new`, `list`, `status`, `start`, `stop`, `restart`, `handoff`

- [ ] **Step 1: Permission unit tests**

```python
from dnd.session.permissions import can

def test_only_creator_restarts_stopped() -> None:
    session = {"status": "stopped", "creator_id": "c1"}
    assert can("c1", "restart", session, admin_ids=[], open_mode=False, enrolled=set()) is True
    assert can("p1", "restart", session, admin_ids=[], open_mode=False, enrolled={"p1"}) is False

def test_enrolled_can_stop_running() -> None:
    session = {"status": "running", "creator_id": "c1"}
    assert can("p1", "stop", session, admin_ids=[], open_mode=False, enrolled={"p1"}) is True
```

- [ ] **Step 2–4: Implement lifecycle + commands**

`/dnd start` calls `session_readiness`; on fail return checklist; on pass set `running` and call opening beat stub (Task 7).

- [ ] **Step 5: Commit**

---

### Task 6: TurnCoordinator — inbox, debounce, proceed

**Files:**
- Create: `maibot-dnd-plugin/dnd/turn/inbox.py`
- Create: `maibot-dnd-plugin/dnd/turn/coordinator.py`
- Modify: `maibot-dnd-plugin/plugin.py` — `/dnd join`, `leave`, `proceed`, `turn`, `skip`, `ooc`
- Create: `maibot-dnd-plugin/tests/test_turn.py`

**Interfaces:**
- Produces:
  - `Inbox.append(msg: InboxMessage) -> None`
  - `TurnCoordinator.on_active_player_message(player_id) -> None` — starts/resets debounce
  - `TurnCoordinator.flush(reason: str) -> list[InboxMessage]` — clears inbox, sets processing lock
  - `TurnCoordinator.processing: bool`

- [ ] **Step 1: Debounce tests**

```python
import asyncio
from dnd.turn.coordinator import TurnCoordinator

async def test_no_debounce_until_active_speaks() -> None:
    tc = TurnCoordinator(debounce_seconds=0.05)
    tc.set_active("alice")
    tc.append({"player_id": "bob", "text": "wait"})
    assert tc.debounce_scheduled is False
    tc.on_active_player_message("alice")
    assert tc.debounce_scheduled is True

async def test_active_resets_debounce() -> None:
    tc = TurnCoordinator(debounce_seconds=0.05)
    tc.set_active("alice")
    tc.on_active_player_message("alice")
    first = tc.debounce_generation
    tc.on_active_player_message("alice")
    assert tc.debounce_generation == first + 1
```

- [ ] **Step 2–4: Implement coordinator with asyncio debounce task**

Any enrolled player may call `request_proceed()`.

- [ ] **Step 5: Commit**

---

### Task 7: Broadcast layer

**Files:**
- Create: `maibot-dnd-plugin/dnd/broadcast.py`
- Modify: `maibot-dnd-plugin/plugin.py` — inject Broadcast helper using `self.ctx`

**Interfaces:**
- Produces:
  - `async def broadcast_gm(ctx, stream_id, text, config) -> None`
  - `async def broadcast_system(ctx, stream_id, text, config) -> None`
  - `async def wake_mai_turn(ctx, stream_id, text, intent: str) -> None`

Implementation:

```python
async def broadcast_gm(ctx, stream_id, text, cfg):
    full = f"{cfg.broadcast.system_prefix_gm}{text}"
    ok = await ctx.send.text(
        full, stream_id,
        sync_to_maisaka_history=cfg.broadcast.sync_to_maisaka_history,
        maisaka_source_kind="plugin:dnd-gm",
    )
    if not ok:
        ctx.logger.warning("send 失败，fallback context.append")
        await ctx.maisaka.context.append(stream_id=stream_id, segments=[{"type": "text", "content": full}], source_kind="plugin:dnd-gm")
```

- [ ] **Step 1: Manual/mock test in smoke_test** — mock ctx verifying kwargs include `sync_to_maisaka_history=True`

- [ ] **Step 2: Commit**

---

### Task 8: GM parser + context builder

**Files:**
- Create: `maibot-dnd-plugin/dnd/gm/parser.py`
- Create: `maibot-dnd-plugin/dnd/gm/context.py`
- Create: `maibot-dnd-plugin/tests/test_gm_parser.py`

**Interfaces:**
- Produces:
  - `parse_gm_response(text: str) -> GMBeatPayload`
  - `GMBeatPayload(narration, mechanics, feedback, turn_advance, scene_state_patch, honored_ids)`
  - `build_gm_messages(session, inbox, config) -> list[dict]`

Use delimiter `===DND_BEAT_JSON===` (like maibook `===NEED_INFO===`).

- [ ] **Step 1: Parser test with sample LLM output**

```python
from dnd.gm.parser import parse_gm_response

SAMPLE = '''一些叙述文字
===DND_BEAT_JSON===
{"narration":"艾莉丝躲进阴影","mechanics":[{"kind":"skill_check","actor":"a1","skill":"stealth","dc":12}],"feedback":[],"honored":["m1"],"turn_advance":{"to":"a1"}}
'''

def test_parse_gm_block() -> None:
    p = parse_gm_response(SAMPLE)
    assert "艾莉丝" in p.narration
    assert p.mechanics[0]["kind"] == "skill_check"
```

- [ ] **Step 2–4: Implement parser + context builder with char budget clipping**

- [ ] **Step 5: Commit**

---

### Task 9: GMBroker beat pipeline

**Files:**
- Create: `maibot-dnd-plugin/dnd/gm/broker.py`
- Create: `maibot-dnd-plugin/dnd/mechanics/items.py` (minimal heal + spawn)
- Modify: `maibot-dnd-plugin/dnd/turn/coordinator.py` — call broker on flush
- Modify: `maibot-dnd-plugin/plugin.py`

**Interfaces:**
- Produces:
  - `async def run_beat(ctx, session, inbox, config) -> BeatResult`
  - Applies mechanics, writes `journal/beats.jsonl`, updates `turn.yaml`, broadcasts

Beat pipeline steps (spec § GM beat flow):
1. Build messages
2. `ctx.llm.generate` with `config.session.gm_model`
3. Parse; on fail retry once with repair prompt
4. Execute mechanics; log rolls to `journal/rolls.jsonl`
5. `broadcast_gm` narration + roll summaries + feedback
6. Persist scene patch; advance turn; if new active is bot person → `wake_mai_turn`

- [ ] **Step 1: Unit test mechanics execution path without LLM**

Mock `GMBroker._execute_payload` with fixed `GMBeatPayload`.

- [ ] **Step 2–4: Implement broker**

- [ ] **Step 5: Commit**

---

### Task 10: HookHandlers — player capture + MaiBot injection

**Files:**
- Modify: `maibot-dnd-plugin/plugin.py`
- Create: `maibot-dnd-plugin/dnd/hooks.py`

**Interfaces:**
- Consumes: `TurnCoordinator`, session running check, enrolled set
- Produces:
  - `@EventHandler` or message hook for inbound enrolled player text → inbox
  - `@HookHandler("maisaka.replyer.after_response")` → if bot response and enrolled, inbox append + `on_active_player_message(bot_person_id)`
  - `@HookHandler("maisaka.replyer.before_model_request")` → inject player briefing when session running + enrolled

Reference: `MaiBot-plastic-memory-plugin/plugin.py` hook patterns.

- [ ] **Step 1: Document manual test checklist in README** (hook behavior requires Host)

- [ ] **Step 2: Implement hooks.py + wire decorators**

- [ ] **Step 3: Commit**

---

### Task 11: Setup tools + bible/dictionary/rulebook

**Files:**
- Modify: `maibot-dnd-plugin/plugin.py`
- Create: `maibot-dnd-plugin/dnd/setup.py`

Tools:
`dnd_setup_bible`, `dnd_setup_gm_prompt`, `dnd_setup_character`, `dnd_import_rulebook`, `dnd_dict_set`, `dnd_dict_query`, `dnd_review_ready`, `dnd_spawn_item`

Commands:
`/dnd bible`, `gm-prompt`, `review`, `import-rules`, `dict`, `dict set`

Rulebook import: httpx fetch (max size from config) → `ctx.llm.generate` split prompt → write `bible/rules/<topic>.md`.

- [ ] **Step 1: Unit test `_write_bible` append/replace** (copy maibook `_write_bible` shape)

- [ ] **Step 2–4: Implement setup.py**

- [ ] **Step 5: Commit**

---

### Task 12: Play tools + lookup commands

**Files:**
- Modify: `maibot-dnd-plugin/plugin.py`

Tools: `dnd_proceed`, `dnd_query_bible`, `dnd_query_log`, `dnd_roll`

Commands: `/dnd card`, `sheet`, `roll`, `log`, `map`

- [ ] **Step 1: Wire tools to existing services**

- [ ] **Step 2: Commit**

---

### Task 13: Character card + map rendering

**Files:**
- Create: `maibot-dnd-plugin/assets/character_card.html`
- Create: `maibot-dnd-plugin/assets/map.html`
- Create: `maibot-dnd-plugin/dnd/render.py`

Follow `maibot-impression-card-plugin` html2png pattern (`device_scale_factor=1.0` like maibook).

- [ ] **Step 1: Render sheet fields to HTML offline test** (no Host: test HTML string contains name/HP)

- [ ] **Step 2: `/dnd card` sends image or markdown fallback on render failure**

- [ ] **Step 3: Commit**

---

### Task 14: README + smoke test completion + manual E2E checklist

**Files:**
- Create: `maibot-dnd-plugin/README.md`
- Modify: `maibot-dnd-plugin/tests/smoke_test.py`

README sections: install (symlink), config, commands table, testing, manual E2E steps.

Manual E2E:
1. `ln -s ../../maibot-dnd-plugin MaiBot/plugins/maibot-dnd-plugin`
2. `/dnd new 测试战役`
3. Fill bible via commands; `/dnd join`; complete sheets
4. `/dnd review` → `/dnd start`
5. Active player speaks → `/dnd proceed` → GM system message appears
6. Verify MaiBot sees GM text in context (sync_to_maisaka_history)

- [ ] **Step 1: Expand smoke_test for config migration + parser + readiness**

- [ ] **Step 2: Write README**

- [ ] **Step 3: Run full pytest + smoke**

Run: `cd maibot-dnd-plugin && PYTHONPATH=.:../maibot-plugin-sdk pytest -v && python tests/smoke_test.py`

- [ ] **Step 4: Commit**

---

## Spec coverage checklist

| Spec section | Task |
|---|---|
| Session engine architecture | 1–2, 9 |
| Adjudicated mechanics | 3–4, 9 |
| Soft turns + inbox | 6, 9 |
| Proceed authority | 6, 12 |
| MaiBot NL + replyer capture | 10 |
| GM system + sync | 7, 9 |
| Session admin C+D | 5 |
| Review gates A+B | 4, 5, 11 |
| Bible/dictionary/rulebook | 11 |
| Context/scene-state/summaries | 8, 9 (scene patch); summaries: basic stub in 9, full scene close in 12+ |
| Maps | 13 |
| Error handling | 8 (parse retry), 9 (abort beat), 7 (sync fallback) |
| Config | 1 |

**Deferred to post-v1 (document in README):** episode summaries automation, combat strict mode, `/dnd scene close` LLM summary generation.

---

## Suggested implementation order

```
Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14
```

Tasks 1–6 deliver a stoppable session with permissions and turns but stub GM. Task 9 completes the play loop. Tasks 10–14 complete MaiBot integration and polish.
