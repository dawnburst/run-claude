# `lmi config switch` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `lmi config switch`, which applies a partial `settings.json` fragment over `~/.claude/settings.json` and can restore the machine's pristine settings with `lmi config switch origin`.

**Architecture:** Task 1 is a pure refactor: `jsonfile.py` moves from `lmi/commands/install/` to `lmi/core/`, with its exit code parameterised, and the `~/.claude/settings.json` path moves to `lmi/core/claude.py`. Tasks 2-5 build the new `lmi/commands/config/` package leaf-first — merge, fragment, origin — and wire it together in Task 6. Task 7 documents.

**Tech Stack:** Python 3.9, standard library only. `pytest` for tests (dev extra). No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-08-09-lmi-config-switch-design.md`. Where this plan and the spec disagree, the spec wins — raise it rather than guessing.

## Global Constraints

Every task's requirements implicitly include all of these.

- **Python 3.9 floor.** No `match`. No PEP 604 unions (`str | None`) in *evaluated* annotations — use `typing.Optional`/`Dict`/`List`. Annotations are evaluated at `def` time, so this is an import-time `TypeError`.
- **`Path.write_text(..., newline=...)` requires 3.10.** Never use it.
- **Standard library only at runtime.** `lmi/` must never import `pytest`. `pyproject.toml` keeps `dependencies = []`.
- **Never `subprocess.run(..., shell=True)`.** This command runs no subprocess at all; if you find yourself adding one, stop and ask.
- **Never use `pathlib`'s `is_dir()`/`is_file()`** on a user-supplied path — they raise `ENAMETOOLONG`/`EACCES` instead of returning `False`. Use `lmi.core.fs.classify` / `fs.kind`, and turn `fs.UNKNOWN` into exit 2.
- **Never call `Path.expanduser()` unguarded** — it raises `RuntimeError` for a `~someuser` whose home cannot be resolved.
- **Commands never import each other.** `lmi/commands/config/` must not import from `lmi/commands/install/` or `lmi/commands/schedule/`. That is the entire reason Task 1 exists.
- **Exit codes:** `0` and `2` are global, from `lmi.core.errors`, and must not be redefined. This command owns `3` and `4`. There is deliberately **no** code `1` — nothing external is invoked.
- **Run `python3 -m pytest tests/ -q` after every task** and state that you did. Baseline is **274** passing.
- **No test may touch the developer's real `~/.claude`.** Use the `home` fixture, which redirects `HOME` and `USERPROFILE`.
- **Test counts in this plan are approximate.** Do not add or remove tests to hit a number. The gate is: every test in your task exists as written, the full suite is green, and no previously-passing test broke.
- **Exact strings that fail silently if wrong** — copy verbatim:
  - `ANTHROPIC_AUTH_TOKEN`
  - `settings.json.lmi-origin`
  - `config/settings_switch.json`
  - `env` values in a fragment are **JSON strings**, never numbers.

## File Structure

| File | Responsibility |
|---|---|
| `lmi/core/jsonfile.py` | **Moved** from `commands/install/`. Read / back up / atomically write one JSON document. Exit code supplied by the caller |
| `lmi/core/claude.py` | **New.** Where Claude Code's files live: `settings_path()` |
| `lmi/commands/install/jsonfile.py` | **Deleted** (moved) |
| `lmi/commands/install/settings.py` | **Modified.** `path()` delegates to `core.claude.settings_path()` |
| `lmi/commands/install/runner.py` | **Modified.** Import `jsonfile` from `core`, pass the exit code |
| `lmi/commands/config/__init__.py` | `NAME="config"`, `HELP`, `add_arguments`, `run` |
| `lmi/commands/config/args.py` | The nested subparser and `switch`'s arguments |
| `lmi/commands/config/merge.py` | The recursive merge. Pure, no I/O |
| `lmi/commands/config/fragment.py` | Finding, reading and validating the switch file |
| `lmi/commands/config/origin.py` | The snapshot: write-once, restore, remove |
| `lmi/commands/config/runner.py` | `run(args)` — the flow |
| `lmi/commands/config/exit_codes.py` | This command's codes: 3, 4 |
| `lmi/commands/__init__.py` | **Modified.** Registration, alphabetical |
| `tests/commands/config/` | One test module per source module, plus `conftest.py` |
| `tests/core/test_jsonfile.py` | **Moved** from `tests/commands/install/` |
| `examples/settings_switch.json`, `README.md`, `CLAUDE.md` | Documentation |

---

### Task 1: Promote `jsonfile.py` and the settings path to `core/`

A pure refactor. **No behaviour changes.** A green suite after this task is the proof that the move was faithful.

**Files:**
- Create: `lmi/core/jsonfile.py` (moved content)
- Create: `lmi/core/claude.py`
- Delete: `lmi/commands/install/jsonfile.py`
- Modify: `lmi/commands/install/settings.py` (`path()`)
- Modify: `lmi/commands/install/runner.py` (import + call sites)
- Move: `tests/commands/install/test_jsonfile.py` → `tests/core/test_jsonfile.py`
- Create: `tests/core/__init__.py`

**Interfaces:**
- Produces:
  - `core.jsonfile.TS_FORMAT: str`, `BACKUP_SUFFIX: str`, `timestamp() -> str`
  - `core.jsonfile.read(path, what, code) -> dict`
  - `core.jsonfile.backup(path, stamp, what, code) -> Optional[Path]`
  - `core.jsonfile.write(path, doc, what, code, mode=None) -> None`
  - `core.claude.settings_path() -> Path` — `~/.claude/settings.json`

**The one change to the module's shape:** every function gains a required `code`
parameter where it previously imported `install.exit_codes.EXIT_CONFIG_WRITE`.
`core/` cannot know a command's codes. `code` goes **after** `what` and before
any optional parameter, so `write(path, doc, what, code, mode=None)`.

- [ ] **Step 1: Move the module and rewrite its exit-code plumbing**

```bash
git mv lmi/commands/install/jsonfile.py lmi/core/jsonfile.py
git mv tests/commands/install/test_jsonfile.py tests/core/test_jsonfile.py
touch tests/core/__init__.py
```

In `lmi/core/jsonfile.py`: delete `from .exit_codes import EXIT_CONFIG_WRITE`,
change the two relative imports from `...core` to `.` (it is now *in* core), add
`code` to each public signature, and replace every `EXIT_CONFIG_WRITE` with
`code`. Replace the module docstring's first paragraph with:

```python
"""Reading, backing up and atomically writing one JSON document.

Nothing here knows what Claude Code is, which is why it lives in core/ rather
than in the command that first needed it. It was promoted out of
commands/install/ when `lmi config switch` became the second caller - the
moment CLAUDE.md section 2 names for promoting, rather than in advance.

Every function takes the exit `code` to raise with, because core/ cannot know a
command's codes and two commands must be free to disagree about them. Both
current callers pass 3.

Every write is atomic - a temp file beside the target, then os.replace, which is
atomic on POSIX and on Windows. A half-written settings.json is invalid JSON and
Claude Code cannot start without it.
"""
```

- [ ] **Step 2: Create `lmi/core/claude.py`**

```python
"""Where Claude Code keeps its files.

One definition, because two commands need it and neither should own it: if
`lmi install` and `lmi config` ever disagreed about where settings.json lives,
one of them would silently configure a file nothing reads.
"""

from pathlib import Path


def settings_path():
    """~/.claude/settings.json - the user-scope settings file."""
    return Path.home() / ".claude" / "settings.json"
```

- [ ] **Step 3: Point install at the promoted code**

In `lmi/commands/install/settings.py`, replace the body of `path()`:

```python
from ...core.claude import settings_path


def path():
    """~/.claude/settings.json. Defined in core.claude - see the note there."""
    return settings_path()
```

In `lmi/commands/install/runner.py`, change the import so `jsonfile` comes from
core, and pass `EXIT_CONFIG_WRITE` at each of the five call sites:

```python
from . import claude_json, gitbash, npm, prompts, settings
from .config import build_config
from .exit_codes import EXIT_CONFIG_WRITE, EXIT_INTERNAL
from ...core import jsonfile
from ...core.errors import EXIT_OK, LmiError
```

The call sites become `jsonfile.read(settings_path, "Claude Code settings",
EXIT_CONFIG_WRITE)`, `jsonfile.backup(path, stamp, what, EXIT_CONFIG_WRITE)`,
`jsonfile.write(path, merged, "Claude Code settings", EXIT_CONFIG_WRITE, mode=mode)`,
and the two in `_write_onboarding_flag`. Search for `jsonfile.` to find them all.

- [ ] **Step 4: Update the moved tests**

In `tests/core/test_jsonfile.py`: change `from lmi.commands.install import
jsonfile` to `from lmi.core import jsonfile`, and add the `code` argument to
every call. The import of `EXIT_CONFIG_WRITE` is no longer available from
install — use the literal `3` and add a module-level note:

```python
# The exit code is the caller's to choose now that jsonfile lives in core/.
# 3 is what both real callers pass; these tests assert the code is propagated,
# not that core/ has an opinion about it.
CODE = 3
```

Every assertion on `exc.value.code == 3` stays exactly as it is — that is the
propagation check.

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m pytest tests/ -q`
Expected: **274 passed** — the same number as before. A refactor that changes
the count changed behaviour.

If anything fails, the move was not faithful. Do not adjust a test to match;
find what the move broke.

- [ ] **Step 6: Verify nothing still imports the old path**

```bash
grep -rn "install import jsonfile\|install\.jsonfile\|from \.jsonfile" lmi/ tests/
```
Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add -A lmi/ tests/
git commit -m "refactor: promote jsonfile.py and the settings path to core/

CLAUDE.md section 2 says to promote when a second command needs it, not in
advance. \`lmi config switch\` is that second command.

The exit code becomes a parameter: core/ cannot know a command's codes.
Both callers pass 3, so no behaviour changes - the suite is still 274."
```

---

### Task 2: The recursive merge

**Files:**
- Create: `lmi/commands/config/__init__.py` (stub), `lmi/commands/config/merge.py`
- Create: `tests/commands/config/__init__.py`, `tests/commands/config/test_merge.py`

**Interfaces:**
- Produces: `merge.deep_merge(base: dict, overlay: dict) -> dict` — a new dict; neither argument is mutated.

- [ ] **Step 1: Create the package stub**

`lmi/commands/config/__init__.py` — the contract lands in Task 6, and the
command must not be registered until `run` exists:

```python
"""`lmi config` - switch Claude Code between configurations.

The four-name command contract (NAME, HELP, add_arguments, run) is completed in
Task 6; this module is not registered in lmi/commands/__init__.py until run()
exists, so that test_every_command_satisfies_the_contract cannot see a
half-built command.
"""
```

Also create an empty `tests/commands/config/__init__.py`.

- [ ] **Step 2: Write the failing test**

`tests/commands/config/test_merge.py`:

```python
"""The recursive merge that makes a switch touch only what it names."""

from lmi.commands.config.merge import deep_merge


def test_an_unnamed_sibling_survives():
    base = {"env": {"A": "1", "B": "2"}, "model": "sonnet"}
    assert deep_merge(base, {"env": {"A": "9"}}) == {
        "env": {"A": "9", "B": "2"},
        "model": "sonnet",
    }


def test_siblings_survive_three_levels_down():
    base = {"a": {"b": {"c": {"keep": 1, "change": 1}}}}
    result = deep_merge(base, {"a": {"b": {"c": {"change": 2}}}})
    assert result == {"a": {"b": {"c": {"keep": 1, "change": 2}}}}


def test_a_scalar_replaces_a_scalar():
    assert deep_merge({"model": "sonnet"}, {"model": "opus"}) == {"model": "opus"}


def test_a_new_key_is_added():
    assert deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_a_list_replaces_rather_than_merging():
    """Merging lists has no single right answer - append? union? by index?

    Guessing produces a settings.json nobody wrote, so a list replaces whole.
    """
    assert deep_merge({"x": [1, 2, 3]}, {"x": [9]}) == {"x": [9]}


def test_an_object_replaces_a_scalar():
    assert deep_merge({"x": 5}, {"x": {"a": 1}}) == {"x": {"a": 1}}


def test_a_scalar_replaces_an_object():
    assert deep_merge({"x": {"a": 1}}, {"x": 5}) == {"x": 5}


def test_null_sets_and_does_not_delete():
    """MANDATORY. Silent failure: a key the user meant to blank disappears.

    `null` is a value. Treating it as a tombstone would make it impossible to
    ever set a key to null deliberately, and would quietly remove settings a
    fragment merely mentioned.
    """
    assert deep_merge({"a": 1, "b": 2}, {"a": None}) == {"a": None, "b": 2}


def test_neither_argument_is_mutated():
    """MANDATORY. Silent failure: the origin snapshot written from a mutated dict.

    runner reads settings.json once and passes it here. If deep_merge mutated
    `base`, the snapshot taken from that same object would already carry the
    switch - so `switch origin` would restore the switched state and the user's
    real settings would be gone, with nothing to show it happened.
    """
    base = {"env": {"A": "1"}}
    overlay = {"env": {"A": "9"}}
    deep_merge(base, overlay)
    assert base == {"env": {"A": "1"}}
    assert overlay == {"env": {"A": "9"}}


def test_nested_results_are_not_shared_with_the_inputs():
    base = {"env": {"A": "1"}}
    result = deep_merge(base, {"model": "opus"})
    result["env"]["A"] = "mutated"
    assert base["env"]["A"] == "1"


def test_an_empty_overlay_changes_nothing():
    assert deep_merge({"a": 1}, {}) == {"a": 1}


def test_an_empty_base_takes_the_overlay():
    assert deep_merge({}, {"a": 1}) == {"a": 1}
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python3 -m pytest tests/commands/config/test_merge.py -q`
Expected: `ModuleNotFoundError: No module named 'lmi.commands.config.merge'`.

- [ ] **Step 4: Write `merge.py`**

```python
"""The recursive merge that makes a switch touch only what it names.

Pure and total: no I/O, no error paths, one function. That is why it is its own
module - it is the piece most worth testing exhaustively, and it is easier to
be exhaustive about something with no dependencies.
"""

import copy


def deep_merge(base, overlay):
    """`base` with `overlay` applied. A new dict; neither argument is touched.

    Two dicts merge key by key, recursing. Anything else replaces whole - a list
    replaces a list rather than being appended to or unioned, because merging
    lists has no single right answer and guessing produces settings nobody wrote.

    Returning a copy is not politeness. The runner reads settings.json once and
    uses the same object for the origin snapshot; mutating `base` here would put
    the switched state into the snapshot, so `switch origin` would restore the
    switch instead of undoing it.
    """
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 -m pytest tests/commands/config/test_merge.py -q` → PASS.
Then `python3 -m pytest tests/ -q` — 274 + 12.

- [ ] **Step 6: Commit**

```bash
git add lmi/commands/config/ tests/commands/config/
git commit -m "feat(config): the recursive merge

Objects merge key by key; everything else replaces whole. Returns a copy
because the runner reuses the base dict for the origin snapshot, and a
mutation there would make \`switch origin\` restore the switch."
```

---

### Task 3: Finding, reading and validating the fragment

**Files:**
- Create: `lmi/commands/config/exit_codes.py`, `lmi/commands/config/fragment.py`
- Create: `tests/commands/config/conftest.py`, `tests/commands/config/test_fragment.py`

**Interfaces:**
- Consumes: `lmi.core.{fs, text}`, `lmi.core.errors.{LmiError, EXIT_USAGE}`
- Produces:
  - `exit_codes.EXIT_CONFIG_WRITE = 3`, `EXIT_INTERNAL = 4`
  - `fragment.DEFAULT_NAME = "config/settings_switch.json"`
  - `fragment.load(explicit) -> Tuple[dict, Path]` — `explicit` is the `--file` value or `None`

- [ ] **Step 1: Write the shared fixture**

`tests/commands/config/conftest.py`:

```python
"""Fixtures for the `lmi config` suite."""

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway HOME, so no test can touch the developer's real ~/.claude."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    return h
```

- [ ] **Step 2: Write the failing test**

`tests/commands/config/test_fragment.py`:

```python
"""Locating and validating a settings.json fragment."""

import json

import pytest

from lmi.commands.config import fragment
from lmi.core.errors import LmiError


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    return path


def test_the_default_path_is_used_when_no_file_is_given(tmp_path, monkeypatch):
    expected = write(tmp_path / "config" / "settings_switch.json", {"model": "opus"})
    monkeypatch.chdir(tmp_path)
    doc, path = fragment.load(None)
    assert doc == {"model": "opus"}
    assert path == expected


def test_the_default_name_is_spelled_exactly():
    assert fragment.DEFAULT_NAME == "config/settings_switch.json"


def test_an_explicit_file_is_used(tmp_path, monkeypatch):
    chosen = write(tmp_path / "prod.json", {"model": "opus"})
    write(tmp_path / "config" / "settings_switch.json", {"model": "WRONG"})
    monkeypatch.chdir(tmp_path)
    doc, path = fragment.load(str(chosen))
    assert doc == {"model": "opus"}
    assert path == chosen


def test_a_missing_explicit_file_does_not_fall_back(tmp_path, monkeypatch):
    """MANDATORY. Silent failure: switching to a profile you did not name.

    A --file the user typed and that does not exist must be an error, never a
    quiet fall-through to ./config/settings_switch.json - which would apply a
    different profile while reporting success.
    """
    write(tmp_path / "config" / "settings_switch.json", {"model": "WRONG"})
    monkeypatch.chdir(tmp_path)
    with pytest.raises(LmiError) as exc:
        fragment.load(str(tmp_path / "nope.json"))
    assert exc.value.code == 2


def test_no_file_anywhere_is_a_usage_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(LmiError) as exc:
        fragment.load(None)
    assert exc.value.code == 2
    assert "settings_switch.json" in str(exc.value)


def test_a_utf8_bom_is_tolerated(tmp_path):
    path = tmp_path / "f.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'{"model": "opus"}')
    assert fragment.load(str(path))[0] == {"model": "opus"}


def test_invalid_json_names_the_file(tmp_path):
    path = tmp_path / "f.json"
    path.write_text('{"model": }', encoding="utf-8")
    with pytest.raises(LmiError) as exc:
        fragment.load(str(path))
    assert exc.value.code == 2
    assert "f.json" in str(exc.value)


@pytest.mark.parametrize("doc", [[1, 2], "text", 5])
def test_a_non_object_top_level_is_rejected(tmp_path, doc):
    path = write(tmp_path / "f.json", doc)
    with pytest.raises(LmiError) as exc:
        fragment.load(str(path))
    assert exc.value.code == 2


def test_a_non_string_env_value_is_rejected(tmp_path):
    """MANDATORY. Silent failure: the switched setting does not apply.

    Claude Code types settings.json env as string-to-string. A JSON number
    writes cleanly, parses cleanly, and the setting does nothing.
    """
    path = write(tmp_path / "f.json", {"env": {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": 32000}})
    with pytest.raises(LmiError) as exc:
        fragment.load(str(path))
    assert exc.value.code == 2
    assert "string" in str(exc.value)


def test_a_string_env_value_is_accepted(tmp_path):
    path = write(tmp_path / "f.json", {"env": {"A": "1"}})
    assert fragment.load(str(path))[0] == {"env": {"A": "1"}}


def test_a_non_object_env_is_rejected(tmp_path):
    path = write(tmp_path / "f.json", {"env": ["not", "a", "map"]})
    with pytest.raises(LmiError) as exc:
        fragment.load(str(path))
    assert exc.value.code == 2


def test_an_unknown_key_passes_through_untouched(tmp_path):
    """lmi does not model Claude Code's schema; it reports typos better."""
    exotic = {"somethingAddedIn2027": {"nested": [1, {"a": 2}]}}
    path = write(tmp_path / "f.json", exotic)
    assert fragment.load(str(path))[0] == exotic


def test_an_empty_object_is_accepted(tmp_path):
    path = write(tmp_path / "f.json", {})
    assert fragment.load(str(path))[0] == {}


def test_tilde_user_that_cannot_resolve_is_usage_not_a_traceback():
    with pytest.raises(LmiError) as exc:
        fragment.load("~nosuchuser-lmi/f.json")
    assert exc.value.code == 2
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python3 -m pytest tests/commands/config/test_fragment.py -q`
Expected: `ImportError: cannot import name 'fragment'`.

- [ ] **Step 4: Write `exit_codes.py`**

```python
"""Exit codes specific to `lmi config`.

0 and 2 are global and live in lmi.core.errors. 3 and 4 keep the meanings they
have in `lmi install`, so a script does not have to learn a per-command
vocabulary.

There is deliberately no 1. In the other commands 1 means "the external thing
we shelled out to failed"; this command invokes nothing, so a 1 here would have
no meaning to give.
"""

EXIT_CONFIG_WRITE = 3
EXIT_INTERNAL = 4
```

- [ ] **Step 5: Write `fragment.py`**

```python
"""Finding, reading and validating the settings.json fragment.

A fragment is a raw settings.json fragment - what you write is what lands.
Validation goes exactly as far as lmi can honestly judge and no further: the
file must be a JSON object, and an `env` block must map strings to strings.
Every other key passes through unexamined, because whether "mdel" is a typo for
"model" is Claude Code's schema's business and it reports that better than a
duplicated validator would. It is also what keeps this command working when
Anthropic adds a setting.
"""

import json
from pathlib import Path

from ...core import fs
from ...core.errors import EXIT_USAGE, LmiError
from ...core.text import decode_with_bom

DEFAULT_NAME = "config/settings_switch.json"
ENV_KEY = "env"

EXAMPLE = """{
  "model": "opus",
  "env": {
    "ANTHROPIC_BASE_URL": "https://gateway.example.com/"
  }
}"""


def load(explicit):
    """(the fragment, the path it came from). Raises LmiError on anything wrong."""
    path = _find(explicit)
    doc = _parse(path)
    _validate(doc, path)
    return doc, path


def _find(explicit):
    if explicit is not None:
        path = _expand(explicit)
        # An explicit --file that does not exist must NOT fall back to the
        # default. A named file that quietly resolves to a different one is how
        # a machine ends up in a configuration nobody chose.
        if _kind(path) != fs.FILE:
            raise LmiError(
                "the file given with --file does not exist: %s" % path, EXIT_USAGE
            )
        return path

    default = Path.cwd() / DEFAULT_NAME
    if _kind(default) == fs.FILE:
        return default
    raise LmiError(
        "no switch file found. Looked for:\n"
        "      %s\n"
        "    Create one, or pass --file PATH. A minimal fragment:\n\n%s"
        % (default, "\n".join("      " + l for l in EXAMPLE.splitlines())),
        EXIT_USAGE,
    )


def _expand(raw):
    """Path(raw).expanduser().absolute(), without the one way it explodes.

    expanduser() raises RuntimeError for a "~someuser" whose home it cannot look
    up, and unguarded that reaches the CLI as a traceback.
    """
    try:
        return Path(raw).expanduser().absolute()
    except RuntimeError as exc:
        raise LmiError(
            "the switch file path cannot be expanded: %s (%s)" % (raw, exc),
            EXIT_USAGE,
        )


def _kind(path):
    """fs.classify, but an unanswerable path is a usage error.

    Path.is_file() raises ENAMETOOLONG rather than returning False.
    """
    kind, reason = fs.classify(path)
    if kind == fs.UNKNOWN:
        raise LmiError(
            "the switch file path cannot be used: %s (%s)" % (path, reason),
            EXIT_USAGE,
        )
    return kind


def _parse(path):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LmiError(
            "the switch file cannot be read: %s (%s)" % (path, exc), EXIT_USAGE
        )
    # Through the BOM decoder: Notepad and PowerShell's Set-Content both write a
    # UTF-8 BOM, and json.loads rejects one with a bare "Expecting value".
    try:
        text = decode_with_bom(raw)
    except UnicodeDecodeError as exc:
        raise LmiError(
            "the switch file is not UTF-8: %s (%s)" % (path, exc), EXIT_USAGE
        )
    try:
        return json.loads(text)
    except ValueError as exc:
        raise LmiError(
            "the switch file is not valid JSON: %s (%s)" % (path, exc), EXIT_USAGE
        )


def _validate(doc, path):
    if not isinstance(doc, dict):
        raise LmiError(
            "the switch file must contain a JSON object: %s" % path, EXIT_USAGE
        )
    env = doc.get(ENV_KEY)
    if env is None:
        return
    if not isinstance(env, dict):
        raise LmiError('"env" must be a JSON object: %s' % path, EXIT_USAGE)
    for key, value in env.items():
        if not isinstance(value, str):
            raise LmiError(
                '"env.%s" must be a string, not %s: %s\n'
                "    Claude Code types settings.json env as string-to-string; a "
                "number is silently ignored."
                % (key, type(value).__name__, path),
                EXIT_USAGE,
            )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/commands/config/ -q` → PASS.
Then `python3 -m pytest tests/ -q`.

- [ ] **Step 7: Commit**

```bash
git add lmi/commands/config/ tests/commands/config/
git commit -m "feat(config): find, read and validate a settings fragment

--file at a nonexistent path is exit 2 and never falls back to the default.
env values must be strings: Claude Code types that map string-to-string and
silently ignores a number."
```

---

### Task 4: The origin snapshot

**Files:**
- Create: `lmi/commands/config/origin.py`
- Create: `tests/commands/config/test_origin.py`

**Interfaces:**
- Consumes: `core.claude.settings_path`, `core.fs`, `core.jsonfile`, `exit_codes.EXIT_CONFIG_WRITE`
- Produces:
  - `origin.SUFFIX = ".lmi-origin"`
  - `origin.path() -> Path` — `~/.claude/settings.json.lmi-origin`
  - `origin.exists() -> bool`
  - `origin.capture(settings, code) -> bool` — writes the snapshot **only if absent**; True if it wrote one
  - `origin.restore(code) -> Path` — copies back over settings.json and removes the snapshot; raises if absent

- [ ] **Step 1: Write the failing test**

`tests/commands/config/test_origin.py`:

```python
"""The pristine snapshot: written once, restored once, then gone."""

import json
import os
import stat

import pytest

from lmi.commands.config import origin
from lmi.core.errors import LmiError
from tests.conftest import skip_as_root

CODE = 3


def settings(home):
    return home / ".claude" / "settings.json"


def put(path, doc, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    if mode is not None:
        os.chmod(str(path), mode)
    return path


def test_the_suffix_is_spelled_exactly():
    assert origin.SUFFIX == ".lmi-origin"


def test_path_sits_beside_settings_json(home):
    assert origin.path().name == "settings.json.lmi-origin"
    assert origin.path().parent == settings(home).parent


def test_capture_writes_when_absent(home):
    assert origin.capture({"model": "sonnet"}, CODE) is True
    assert json.loads(origin.path().read_text(encoding="utf-8")) == {"model": "sonnet"}


def test_capture_is_write_once(home):
    """MANDATORY. Silent failure: `origin` stops meaning your real settings.

    The snapshot must be written only if it does not already exist. Written
    unconditionally, `origin` silently becomes "undo one step" while still being
    spelled origin, and the pristine settings are unrecoverable after the second
    switch. Nothing observable distinguishes the two: the file is present either
    way, and a single switch behaves identically.
    """
    origin.capture({"generation": 0}, CODE)
    assert origin.capture({"generation": 1}, CODE) is False
    assert origin.capture({"generation": 2}, CODE) is False
    assert json.loads(origin.path().read_text(encoding="utf-8")) == {"generation": 0}


def test_exists_reflects_the_file(home):
    assert origin.exists() is False
    origin.capture({"a": 1}, CODE)
    assert origin.exists() is True


def test_restore_puts_it_back_and_removes_the_snapshot(home):
    put(settings(home), {"model": "sonnet"})
    origin.capture({"model": "sonnet"}, CODE)
    put(settings(home), {"model": "opus"})

    origin.restore(CODE)
    assert json.loads(settings(home).read_text(encoding="utf-8")) == {"model": "sonnet"}
    assert origin.exists() is False


def test_restore_without_a_snapshot_is_usage(home):
    with pytest.raises(LmiError) as exc:
        origin.restore(CODE)
    assert exc.value.code == 2
    assert "nothing to restore" in str(exc.value)


def test_restore_twice_is_usage_the_second_time(home):
    put(settings(home), {"a": 1})
    origin.capture({"a": 1}, CODE)
    origin.restore(CODE)
    with pytest.raises(LmiError) as exc:
        origin.restore(CODE)
    assert exc.value.code == 2


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_the_snapshot_is_0600(home):
    """It can hold ANTHROPIC_AUTH_TOKEN, and ~/.claude/ is 0755."""
    origin.capture({"env": {"ANTHROPIC_AUTH_TOKEN": "sk-x"}}, CODE)
    assert stat.S_IMODE(os.stat(str(origin.path())).st_mode) == 0o600


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_a_restored_settings_file_is_0600(home):
    put(settings(home), {"env": {"ANTHROPIC_AUTH_TOKEN": "sk-x"}}, mode=0o600)
    origin.capture({"env": {"ANTHROPIC_AUTH_TOKEN": "sk-x"}}, CODE)
    put(settings(home), {"model": "opus"}, mode=0o644)
    origin.restore(CODE)
    assert stat.S_IMODE(os.stat(str(settings(home))).st_mode) == 0o600
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/commands/config/test_origin.py -q`
Expected: `ImportError: cannot import name 'origin'`.

- [ ] **Step 3: Write `origin.py`**

```python
"""The pristine snapshot of settings.json, and putting it back.

`switch origin` means "the settings this machine had before the first switch",
not "undo the last switch". That distinction lives entirely in capture(): the
snapshot is written ONLY if it does not already exist.

Get that backwards and the command still works, in the sense that nothing
errors. `origin` silently becomes undo-one-step while still being spelled
origin, and the user's real settings are unrecoverable after the second switch -
with the file present either way and a single switch behaving identically, so
nothing afterwards shows which of the two you built.
"""

import os

from ...core import fs, jsonfile
from ...core.claude import settings_path
from ...core.errors import EXIT_USAGE, LmiError

SUFFIX = ".lmi-origin"

NOTHING_TO_RESTORE = (
    "there is nothing to restore: no switch has been made on this machine,\n"
    "    so lmi has no record of what settings.json looked like before one.\n"
    "    `lmi config switch --file <fragment>` takes that snapshot the first\n"
    "    time it runs."
)


def path():
    """~/.claude/settings.json.lmi-origin - beside the file it protects."""
    settings = settings_path()
    return settings.with_name(settings.name + SUFFIX)


def exists():
    return fs.kind(path()) == fs.FILE


def capture(settings, code):
    """Snapshot `settings` if no snapshot exists. True if one was written.

    The `if not exists()` is the whole mechanism - see the module docstring.
    Do not "simplify" it into an unconditional write.

    0600 because settings.json can carry ANTHROPIC_AUTH_TOKEN and ~/.claude/ is
    0755, so a snapshot at the umask default would publish it to every user on
    the box.
    """
    if exists():
        return False
    jsonfile.write(path(), settings, "origin snapshot", code, mode=0o600)
    return True


def restore(code):
    """Put the snapshot back over settings.json and remove it. Returns its path.

    Removed afterwards so the next switch establishes a fresh pristine point,
    and so a second `origin` says there is nothing left rather than silently
    repeating itself.
    """
    if not exists():
        raise LmiError(NOTHING_TO_RESTORE, EXIT_USAGE)

    snapshot = path()
    target = settings_path()
    doc = jsonfile.read(snapshot, "origin snapshot", code)
    # The snapshot is 0600, and the file it restores must not be looser.
    jsonfile.write(target, doc, "Claude Code settings", code, mode=0o600)
    try:
        os.unlink(str(snapshot))
    except OSError as exc:
        raise LmiError(
            "settings.json was restored but the snapshot could not be removed: "
            "%s (%s)\n"
            "    Delete it by hand, or the next switch will not take a fresh one."
            % (snapshot, exc),
            code,
        )
    return target
```

`fs` is imported for `exists()` and `jsonfile` for the read and write — that is
the whole import list. **`exit_codes` is deliberately not imported here.** Every
function in this module takes `code` from its caller, the same contract
`core/jsonfile.py` uses, and raising with a module-level constant in one branch
while honouring the parameter everywhere else is the kind of inconsistency that
makes a later reader distrust both.

There is no `shutil` either: the restore goes through `jsonfile.write` rather
than `shutil.copy2`, so it is atomic and the mode is forced rather than
inherited.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/commands/config/test_origin.py -q` → PASS.
Then `python3 -m pytest tests/ -q`.

- [ ] **Step 5: Commit**

```bash
git add lmi/commands/config/origin.py tests/commands/config/test_origin.py
git commit -m "feat(config): the write-once origin snapshot

capture() writes only if no snapshot exists. Unconditional, \`origin\`
silently becomes undo-one-step while still being spelled origin, and the
pristine settings are gone after the second switch."
```

---

### Task 5: Arguments and the nested subparser

**Files:**
- Create: `lmi/commands/config/args.py`
- Create: `tests/commands/config/test_args.py`

**Interfaces:**
- Produces: `args.add_arguments(parser) -> None`, `args.NAME = "config"`, `args.HELP`

`lmi/cli.py` gives each command one subparser and calls `command.add_arguments`
on it. A second level is built *inside* that call, so `cli.py` learns nothing.

- [ ] **Step 1: Write the failing test**

`tests/commands/config/test_args.py`:

```python
"""The nested subparser - `lmi config switch [origin] [--file PATH]`."""

import argparse

import pytest

from lmi.commands.config import args as config_args


def parser():
    p = argparse.ArgumentParser(prog="lmi config")
    config_args.add_arguments(p)
    return p


def test_switch_with_no_arguments_parses():
    ns = parser().parse_args(["switch"])
    assert ns.target is None
    assert ns.file is None


def test_origin_is_accepted_as_the_target():
    assert parser().parse_args(["switch", "origin"]).target == "origin"


def test_a_path_is_rejected_as_the_target():
    """MANDATORY. Silent failure: a filename read as the restore keyword.

    Paths only ever arrive behind --file. If the positional accepted arbitrary
    text, `lmi config switch prod.json` would look reasonable and would have to
    guess whether the word is a keyword or a file - the ambiguity the --file
    flag exists to remove.
    """
    with pytest.raises(SystemExit):
        parser().parse_args(["switch", "prod.json"])


def test_file_takes_a_path():
    assert parser().parse_args(["switch", "--file", "p.json"]).file == "p.json"


def test_f_is_the_short_form():
    assert parser().parse_args(["switch", "-f", "p.json"]).file == "p.json"


def test_origin_and_file_can_be_given_together_and_parse():
    """Parsing accepts it; the runner decides what it means (origin wins)."""
    ns = parser().parse_args(["switch", "origin", "--file", "p.json"])
    assert ns.target == "origin" and ns.file == "p.json"


def test_an_unknown_verb_is_rejected():
    with pytest.raises(SystemExit):
        parser().parse_args(["nosuchverb"])


def test_no_verb_leaves_the_marker_unset():
    """`lmi config` alone must be a usage error, which runner turns into exit 2."""
    assert getattr(parser().parse_args([]), "_config_run", None) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/commands/config/test_args.py -q`
Expected: `ImportError: cannot import name 'args'`.

- [ ] **Step 3: Write `args.py`**

```python
"""The `lmi config` argument surface.

cli.py hands each command one subparser and calls add_arguments on it. The
second level is built here, inside that call, so cli.py keeps its single
subparser level and learns nothing about this command - the architecture rule
in CLAUDE.md section 2.

`origin` is a bare positional with choices=["origin"]; a path only ever arrives
behind --file. That is what removes the collision between the keyword and a file
of the same name: the two never occupy the same argument, so no precedence rule
is needed.
"""

NAME = "config"
HELP = "Switch Claude Code between configurations"

SWITCH_HELP = "apply a settings.json fragment, or restore the pristine settings"


def add_arguments(parser):
    sub = parser.add_subparsers(dest="config_command", metavar="<subcommand>")
    switch = sub.add_parser("switch", help=SWITCH_HELP, description=SWITCH_HELP)
    switch.add_argument(
        "target", nargs="?", choices=["origin"], metavar="[origin]",
        help="restore the settings.json this machine had before the first switch",
    )
    switch.add_argument(
        "-f", "--file", dest="file", metavar="PATH",
        help="the settings.json fragment to apply. Default: config/settings_switch.json",
    )
    switch.set_defaults(_config_run="switch")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/commands/config/test_args.py -q` → PASS.
Then `python3 -m pytest tests/ -q`.

- [ ] **Step 5: Commit**

```bash
git add lmi/commands/config/args.py tests/commands/config/test_args.py
git commit -m "feat(config): the nested subparser

The second level is built inside add_arguments, so cli.py keeps one
subparser level. \`origin\` is a bare positional with choices; paths only
arrive behind --file, so keyword and filename never collide."
```

---

### Task 6: The flow, and registration

**Files:**
- Create: `lmi/commands/config/runner.py`
- Modify: `lmi/commands/config/__init__.py` (replace the Task 2 stub)
- Modify: `lmi/commands/__init__.py`
- Modify: `tests/test_cli.py` — `test_the_registry_lists_every_command_in_help_order`
- Create: `tests/commands/config/test_runner.py`

**Interfaces:**
- Consumes: everything from Tasks 1-5
- Produces: `runner.run(args) -> int`; the package exports `NAME`, `HELP`, `add_arguments`, `run`

- [ ] **Step 1: Write the failing test**

`tests/commands/config/test_runner.py`:

```python
"""End to end: fragment in, settings.json out, snapshot in between."""

import json
import os
import stat

import pytest

from lmi.commands.config import origin, runner
from lmi.core.errors import LmiError
from tests.conftest import skip_as_root


class Args:
    def __init__(self, target=None, file=None, config_command="switch"):
        self.target = target
        self.file = file
        self.config_command = config_command
        self._config_run = "switch" if config_command == "switch" else None


def settings(home):
    return home / ".claude" / "settings.json"


def put(path, doc, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    if mode is not None:
        os.chmod(str(path), mode)
    return path


def frag(tmp_path, doc, name="f.json"):
    path = tmp_path / name
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    return path


def read(home):
    return json.loads(settings(home).read_text(encoding="utf-8"))


def test_a_switch_changes_only_what_it_names(home, tmp_path):
    put(settings(home), {"model": "sonnet", "theme": "dark",
                         "env": {"A": "1", "B": "2"}})
    f = frag(tmp_path, {"model": "opus", "env": {"A": "9"}})

    assert runner.run(Args(file=str(f))) == 0
    assert read(home) == {
        "model": "opus", "theme": "dark", "env": {"A": "9", "B": "2"},
    }


def test_the_first_switch_captures_the_snapshot(home, tmp_path):
    put(settings(home), {"model": "sonnet"})
    runner.run(Args(file=str(frag(tmp_path, {"model": "opus"}))))
    assert json.loads(origin.path().read_text(encoding="utf-8")) == {"model": "sonnet"}


def test_three_switches_leave_the_snapshot_pristine(home, tmp_path):
    """MANDATORY. Silent failure: `origin` restores a switched state.

    The snapshot must still hold the settings from before the FIRST switch. If
    capture() ever writes unconditionally, this is the only thing that notices -
    every individual switch still works, and the file exists either way.
    """
    put(settings(home), {"generation": "pristine"})
    for n in range(3):
        runner.run(Args(file=str(frag(tmp_path, {"generation": str(n)}, "g%d.json" % n))))
    assert json.loads(origin.path().read_text(encoding="utf-8")) == {
        "generation": "pristine"
    }


def test_origin_restores_the_pristine_settings(home, tmp_path):
    put(settings(home), {"model": "sonnet", "keep": True})
    runner.run(Args(file=str(frag(tmp_path, {"model": "opus"}))))
    runner.run(Args(file=str(frag(tmp_path, {"model": "haiku"}, "b.json"))))

    assert runner.run(Args(target="origin")) == 0
    assert read(home) == {"model": "sonnet", "keep": True}
    assert origin.exists() is False


def test_origin_wins_when_a_file_is_also_given(home, tmp_path):
    put(settings(home), {"model": "sonnet"})
    runner.run(Args(file=str(frag(tmp_path, {"model": "opus"}))))
    f = frag(tmp_path, {"model": "NEVER"}, "never.json")

    assert runner.run(Args(target="origin", file=str(f))) == 0
    assert read(home) == {"model": "sonnet"}


def test_origin_before_any_switch_is_usage(home):
    with pytest.raises(LmiError) as exc:
        runner.run(Args(target="origin"))
    assert exc.value.code == 2


def test_a_missing_settings_file_is_created(home, tmp_path):
    assert runner.run(Args(file=str(frag(tmp_path, {"model": "opus"})))) == 0
    assert read(home) == {"model": "opus"}


def test_an_invalid_fragment_writes_nothing(home, tmp_path):
    """MANDATORY. Silent failure: a half-applied switch.

    Everything is read and validated before anything is written, so a bad
    fragment must leave settings.json untouched AND take no snapshot - a
    snapshot taken here would freeze the wrong state as 'pristine'.
    """
    put(settings(home), {"model": "sonnet"})
    before = settings(home).read_bytes()
    bad = tmp_path / "bad.json"
    bad.write_text('{"model": }', encoding="utf-8")

    with pytest.raises(LmiError) as exc:
        runner.run(Args(file=str(bad)))
    assert exc.value.code == 2
    assert settings(home).read_bytes() == before
    assert origin.exists() is False


def test_an_unparseable_settings_file_is_refused(home, tmp_path):
    settings(home).parent.mkdir(parents=True, exist_ok=True)
    settings(home).write_text('{"model": }', encoding="utf-8")
    before = settings(home).read_bytes()

    with pytest.raises(LmiError) as exc:
        runner.run(Args(file=str(frag(tmp_path, {"model": "opus"}))))
    assert exc.value.code == 3
    assert settings(home).read_bytes() == before


def test_no_subcommand_is_a_usage_error(home):
    with pytest.raises(LmiError) as exc:
        runner.run(Args(config_command=None))
    assert exc.value.code == 2


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_a_token_in_the_result_forces_0600(home, tmp_path):
    put(settings(home), {"model": "sonnet"}, mode=0o644)
    f = frag(tmp_path, {"env": {"ANTHROPIC_AUTH_TOKEN": "sk-x"}})
    runner.run(Args(file=str(f)))
    assert stat.S_IMODE(os.stat(str(settings(home))).st_mode) == 0o600


def test_the_run_reports_what_changed(home, tmp_path, capsys):
    put(settings(home), {"model": "sonnet"})
    runner.run(Args(file=str(frag(tmp_path, {"model": "opus"}))))
    out = capsys.readouterr().out
    assert "model" in out
    assert str(settings(home)) in out
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/commands/config/test_runner.py -q`
Expected: `ImportError: cannot import name 'runner'`.

- [ ] **Step 3: Write `runner.py`**

```python
"""The `lmi config switch` flow.

Order matters: everything is read and validated before anything is written, so
a malformed fragment leaves the machine exactly as it was. The snapshot is taken
before the merge is written, so a failure part-way still leaves a recoverable
state - and it is taken only after the fragment has been accepted, or a bad
fragment would freeze the wrong moment as 'pristine'.
"""

from . import fragment, origin
from .exit_codes import EXIT_CONFIG_WRITE, EXIT_INTERNAL
from .merge import deep_merge
from ...core import jsonfile
from ...core.claude import settings_path
from ...core.errors import EXIT_OK, EXIT_USAGE, LmiError

TOKEN_KEY = "ANTHROPIC_AUTH_TOKEN"

NO_SUBCOMMAND = (
    "lmi config needs a subcommand.\n"
    "    lmi config switch                  apply config/settings_switch.json\n"
    "    lmi config switch --file PATH      apply that fragment\n"
    "    lmi config switch origin           restore the pristine settings.json"
)


def run(args):
    try:
        return _run(args)
    except LmiError:
        # Already carries its exit code and a message cli.main will print.
        raise
    except Exception as exc:                    # noqa: BLE001 - deliberate
        raise LmiError(
            "unexpected failure in lmi config: %s: %s" % (type(exc).__name__, exc),
            EXIT_INTERNAL,
        )


def _run(args):
    if getattr(args, "_config_run", None) is None:
        raise LmiError(NO_SUBCOMMAND, EXIT_USAGE)

    # origin wins over --file: it is the more destructive of the two and the
    # user named it explicitly, so silently applying a fragment instead would
    # be the worse surprise.
    if getattr(args, "target", None) == "origin":
        return _restore()
    return _switch(getattr(args, "file", None))


def _switch(explicit):
    doc, source = fragment.load(explicit)
    say("Fragment: %s" % source)

    target = settings_path()
    current = jsonfile.read(target, "Claude Code settings", EXIT_CONFIG_WRITE)

    if origin.capture(current, EXIT_CONFIG_WRITE):
        say("Saved your current settings as the restore point: %s" % origin.path())

    merged = deep_merge(current, doc)
    jsonfile.write(
        target, merged, "Claude Code settings", EXIT_CONFIG_WRITE,
        mode=_mode_for(merged),
    )

    say("Wrote %s" % target)
    for key in sorted(doc):
        say("  %s" % key)
    say("Restore with: lmi config switch origin")
    return EXIT_OK


def _restore():
    target = origin.restore(EXIT_CONFIG_WRITE)
    say("Restored %s to the settings from before the first switch." % target)
    say("The restore point is used up; the next switch will take a new one.")
    return EXIT_OK


def _mode_for(doc):
    """0600 when the document holds a credential, else leave the mode alone.

    On Windows os.chmod only toggles the read-only bit and grants no protection;
    lmi does not claim otherwise there.
    """
    env = doc.get("env")
    if isinstance(env, dict) and env.get(TOKEN_KEY):
        return 0o600
    return None


def say(message=""):
    """Console output. This command writes no log file."""
    print(message)
```

- [ ] **Step 4: Replace the package `__init__.py`**

```python
from .args import HELP, NAME, add_arguments  # noqa: F401
from .runner import run  # noqa: F401
```

- [ ] **Step 5: Register the command**

`lmi/commands/__init__.py` — replace the import and the list:

```python
from . import config, install, schedule

COMMANDS = [config, install, schedule]
```

- [ ] **Step 6: Update the registration tripwire**

In `tests/test_cli.py`, replace `test_the_registry_lists_every_command_in_help_order`
entirely — **including its docstring**, which currently explains a lifecycle
rationale that this change supersedes and would otherwise contradict the list
directly beneath it:

```python
def test_the_registry_lists_every_command_in_help_order():
    """The intended tripwire: adding a command must update this list.

    Registry order is --help order, and it is alphabetical. An earlier spec
    ordered by lifecycle - install, then schedule - but that is already
    arguable at three commands (you configure after installing, and also
    between scheduled runs) and becomes a debate at four. Alphabetical has no
    opinion to disagree with.
    """
    from lmi.commands import COMMANDS
    assert [c.NAME for c in COMMANDS] == ["config", "install", "schedule"]
```

- [ ] **Step 7: Run the whole suite, then check the wiring by hand**

Run: `python3 -m pytest tests/ -q` → all pass.

```bash
python3 -m lmi --help                       # config, install, schedule
python3 -m lmi config --help                # shows `switch`
python3 -m lmi config switch --help         # shows [origin] and --file
python3 -m lmi config ; echo "expect 2, got $?"
python3 -m lmi config switch nonsense ; echo "expect 2, got $?"
```

Report the actual output of each.

- [ ] **Step 8: Commit**

```bash
git add lmi/commands/ tests/
git commit -m "feat(config): the switch flow, and registration

Everything is read and validated before anything is written, so a bad
fragment leaves the machine untouched and takes no snapshot - a snapshot
there would freeze the wrong moment as pristine.

Registry order becomes alphabetical; the tripwire test's docstring is
rewritten to match, or it would contradict the list beneath it."
```

---

### Task 7: Documentation

**Files:**
- Create: `examples/settings_switch.json`
- Modify: `README.md`, `CLAUDE.md`
- Modify: `tests/test_docs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_docs.py`:

```python
def test_the_example_switch_fragment_is_accepted(tmp_path):
    """It is copied and edited, so a rejected shape is a broken starting point."""
    from lmi.commands.config import fragment
    src = REPO / "examples" / "settings_switch.json"
    staged = tmp_path / "f.json"
    staged.write_bytes(src.read_bytes())
    doc, _ = fragment.load(str(staged))
    assert doc


def test_the_readme_documents_config_switch():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for needle in ("lmi config switch", "settings.json.lmi-origin",
                   "config/settings_switch.json"):
        assert needle in readme, "README.md must document %s" % needle


def test_claude_md_records_the_write_once_snapshot():
    """MANDATORY. The rule is one line of code and invisible when inverted.

    If CLAUDE.md does not carry it, the next person to touch origin.capture has
    nothing telling them why the `if not exists()` is there.
    """
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert "lmi-origin" in text
    start = text.index("lmi-origin")
    window = text[max(0, start - 800):start + 800]
    assert "once" in window or "only if" in window
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_docs.py -q` → FAIL, `examples/settings_switch.json` missing.

- [ ] **Step 3: Write `examples/settings_switch.json`**

```json
{
  "model": "opus",
  "env": {
    "ANTHROPIC_BASE_URL": "https://gateway.example.com/",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "32000"
  }
}
```

- [ ] **Step 4: Add the README section**

Append an `## lmi config switch` section after the `lmi install claude` material.
It must contain, at minimum:

- the three invocations, and that `--file` (`-f`) is the only way to name a path;
- that the fragment is a raw `settings.json` fragment, not an lmi config file,
  and that `registry` is **not** a settings key — it belongs to `lmi install`;
- the merge rule, with the `{"env": {"A": "9"}}` over `{"env": {"A": "1", "B": "2"}}`
  worked example, and that lists replace whole and `null` sets rather than deletes;
- that `env` values must be strings;
- what `origin` restores — the state before the **first** switch, not the last —
  that it is used up when restored, and that intermediate states are *not*
  recoverable because the fragment that produced them reproduces them;
- where the snapshot lives (`~/.claude/settings.json.lmi-origin`, mode 0600);
- the exit codes: 0 · 2 usage (no fragment, bad fragment, non-string `env`
  value, `origin` with nothing to restore) · 3 a settings file could not be read
  or written · 4 a bug in lmi;
- the real-run check no test can perform: switch a fragment that changes
  `model`, run `claude`, confirm the model changed, then `switch origin` and
  confirm it changed back.

- [ ] **Step 5: Update `CLAUDE.md`**

Three edits:

1. **Section 2, architecture map** — add the new package and the two promoted
   modules:

```
lmi/commands/config/        `lmi config switch`, as a self-contained package
  args.py                   the nested subparser
  fragment.py               finding, reading and validating the switch file
  merge.py                  the recursive merge
  origin.py                 the write-once snapshot
  runner.py                 the flow
  exit_codes.py             this command's codes (3, 4)
lmi/core/
  jsonfile.py               read / back up / atomically write a JSON document
  claude.py                 where Claude Code keeps its files
```

Note in the same section that `jsonfile.py` moved out of `commands/install/`
when `config` became its second caller, and that this is the promotion rule in
action rather than an exception to it.

2. **Section 3** — append a new numbered item, continuing from the last:

```
22. **The origin snapshot is written only if it does not already exist.**
    `config/origin.capture` takes it on the first switch and never again, so
    `switch origin` means the settings the machine had before *any* switch.
    **Silent:** written unconditionally it becomes undo-one-step while still
    being spelled origin - every single switch still behaves identically, the
    file is present either way, and the user's real settings are unrecoverable
    after the second switch with nothing to show it.
```

3. **Section 5, fixtures table** — add the `home` fixture from
   `tests/commands/config/conftest.py`.

- [ ] **Step 6: Run the whole suite**

Run: `python3 -m pytest tests/ -q` → all pass.

- [ ] **Step 7: Commit**

```bash
git add examples/ README.md CLAUDE.md tests/test_docs.py
git commit -m "docs(config): README section, example fragment, CLAUDE.md guard

Records the write-once snapshot rule in section 3: it is one line of code,
it is invisible when inverted, and nothing else would tell the next reader
why the \`if not exists()\` is there."
```

---

## Self-Review

**Spec coverage** — every section maps to a task:

| Spec | Task |
|---|---|
| §1 non-goals (no npm switching, no `status`, no removal, no env var, no stack) | Enforced by omission; `null`-sets pinned in T2, no-env-var in T3 |
| §2 command surface, `origin` positional vs `--file` | T5 |
| §3 fragment shape, discovery, validation | T3 |
| §4 merge semantics | T2 |
| §5 write-once snapshot, restore, exit 2 when absent | T4, plus the three-switch test in T6 |
| §6 promotion of `jsonfile.py` and `settings_path()` | T1 |
| §7 package structure, registration alphabetical | T5, T6 |
| §8 flow order (validate → snapshot → merge → write) | T6 |
| §9 exit codes, no code 1 | T3 (`exit_codes.py`), asserted throughout |
| §10 testing, incl. the MANDATORY items | T2, T3, T4, T6 |
| §11 documentation | T7 |

**MANDATORY tests, eight in total:** `null` sets rather than deletes (T2); neither
merge argument is mutated (T2); `--file` does not fall through (T3); non-string
`env` value rejected (T3); `capture` is write-once (T4); three switches leave the
snapshot pristine (T6); an invalid fragment writes nothing and takes no snapshot
(T6); a path is rejected as the positional (T5). Plus the `CLAUDE.md` guard in T7.

**Placeholder scan:** clean. Task 7 Step 4 is a content checklist rather than
literal prose, deliberately — the README's voice should be matched by whoever
writes it, and `tests/test_docs.py` mechanically enforces the parts that matter.

**Type consistency:** `jsonfile.{read,backup,write}` take `(path, …, what, code)`
throughout, with `mode` last and optional. `origin.{capture,restore}` take `code`.
`fragment.load(explicit) -> (dict, Path)` matches its use in `runner._switch`.
`deep_merge(base, overlay)` matches. `args` sets `_config_run`, which
`runner._run` reads by that exact name, and `test_args` asserts it.

**Two fixes applied during review rather than left as notes:** `origin.py` no
longer imports an unused `shutil`, and the mode assertion in T4 lost a redundant
`.__str__()`. Both were transcription traps that would have cost an implementer
a review round.
