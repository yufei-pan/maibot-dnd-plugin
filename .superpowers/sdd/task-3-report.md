# Task 3 Report — MechanicsEngine dice + skill checks

**Status:** DONE

**Commit:** `71535cd9b38e5b0196887fcaf2f24283859c79a9`

## Summary

Added pure-Python mechanics layer:

- `dnd/mechanics/dice.py` — `RollResult`, `roll_formula()` with `NdM±mod` parsing; default RNG via `secrets.randbelow`
- `dnd/mechanics/sheets.py` — minimal `CharacterSheet` dataclass (skills/abilities/HP for engine reads)
- `dnd/mechanics/engine.py` — `MechanicsEngine.execute()` for `skill_check` with advantage/disadvantage on d20 (mutually exclusive cancels to normal roll)
- `tests/test_dice.py` — deterministic tests via injected `rng`

## Test output

```
$ cd /mnt/klein/work/maibot-plugins/maibot-dnd-plugin && PYTHONPATH=.:../maibot-plugin-sdk pytest tests/test_dice.py -v
============================= test session starts ==============================
platform linux -- Python 3.13.5, pytest-8.3.5, pluggy-1.5.0 -- /usr/bin/python3
cachedir: .pytest_cache
rootdir: /mnt/klein/work/maibot-plugins/maibot-dnd-plugin
plugins: typeguard-4.4.2, anyio-4.8.0
collecting ... collected 2 items

tests/test_dice.py::test_roll_d20_plus_mod PASSED                        [ 50%]
tests/test_dice.py::test_advantage_takes_higher PASSED                   [100%]

============================== 2 passed in 0.01s ===============================
```

Exit code: 0

## Concerns

- `CharacterSheet` is minimal; Task 4 adds YAML loading and gate B validation.
- Only `skill_check` intent kind is implemented; other kinds deferred to Task 9.
