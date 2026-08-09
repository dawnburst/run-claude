# `lmi upgrade` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `lmi upgrade`, a command that installs a newer `lmi` from the site's internal Python package index over the installation it is currently running from, having asked first, and refuses to report success unless the installed command answers with the new version.

**Architecture:** A new self-contained command package `lmi/commands/upgrade/`, registered by one line in `lmi/commands/__init__.py`. `cli.py` is not touched. Two pieces of `lmi install` are promoted into `core/` first, because `upgrade` is the second command to need them: config-file discovery and the interactive-prompt guard. Then the leaf modules (`config`, `installation`, `pip`, `verify`, `prompts`) are built and tested one at a time, and `runner.py` orchestrates them last.

**Tech Stack:** Python 3.9, standard library only. `pytest` for tests (dev extra). No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-08-09-lmi-upgrade-design.md`. Where this plan and the spec disagree, the spec wins — raise it rather than guessing.

## Global Constraints

Every task's requirements implicitly include all of these.

- **Python 3.9 floor.** No `match`. No PEP 604 unions (`str | None`) in *evaluated* annotations — use `typing.Optional`/`Dict`/`List`. Function annotations are evaluated at `def` time, so this is an import-time `TypeError`, not a runtime one.
- **`Path.write_text(..., newline=...)` requires 3.10.** Always use `open(path, "w", encoding="utf-8", newline="\n")`.
- **Standard library only at runtime.** `lmi/` must never import `pytest`. `pyproject.toml` keeps `dependencies = []`; `tests/test_packaging.py` enforces it, and `--no-deps` below depends on it staying true.
- **Never `subprocess.run(..., shell=True)`.** An index URL from a config file must never reach a shell. Always a list argv, always `check=False` (the default).
- **Never use `pathlib`'s `is_dir()`/`is_file()`** on a user-supplied path. They raise `ENAMETOOLONG`, `EACCES` and more instead of returning `False`. Use `lmi.core.fs.classify` / `fs.kind`, and turn `fs.UNKNOWN` into exit 2.
- **Never call `Path.expanduser()` unguarded.** It raises `RuntimeError` for a `~someuser` whose home cannot be resolved.
- **Commands never import each other.** `lmi/commands/upgrade/` must not import from `lmi/commands/install/` or `lmi/commands/schedule/`. Anything both need goes through `lmi/core/`.
- **Exit codes:** `0` and `2` are global, from `lmi.core.errors`, and must not be redefined. This command owns `1`, `3`, `4`.
- **Never read `lmi.__version__` to decide whether an upgrade worked.** It is the version this process imported *before* pip ran. The only honest answer comes from running the installed console script in a subprocess.
- **Run `python3 -m pytest tests/ -q` after every task** and state in your report that you did, with the actual count. **Baseline is 274 passing.**
- **No test may reach a real `pip`, a real package index, a real `claude` or a real `npm`.** Fixtures replace the interpreter or `PATH` entirely (never prepend), and `HOME` is redirected to `tmp_path`.
- **Exact strings that fail silently if wrong** — copy verbatim, never retype:
  - `--index-url` (never `--extra-index-url`: it must *replace* the default index, not add to it)
  - `--no-deps`
  - `--cert` (pip's CA option; npm's is `cafile`, they are not the same flag)
  - `direct_url.json`, and the key path `dir_info.editable`
  - `pipx_metadata.json`

## File Structure

| File | Responsibility |
|---|---|
| `lmi/core/config.py` | **New.** Where the config file is, how it is decoded and parsed, and the two refusals that must never become fall-throughs |
| `lmi/core/prompts.py` | **New.** The three question types and the guard that turns a missing terminal into exit 2 rather than a hang |
| `lmi/commands/install/config.py` | **Modify.** Keeps the `claude` section's meaning; delegates discovery to `core/config.py` |
| `lmi/commands/install/prompts.py` | **Modify.** Shrinks to this command's `NO_TERMINAL` text plus three one-line delegations |
| `lmi/commands/upgrade/__init__.py` | **New.** The four-name command contract |
| `lmi/commands/upgrade/exit_codes.py` | **New.** This command's codes: 1, 3, 4 |
| `lmi/commands/upgrade/config.py` | **New.** `--version`, `--config`, the `lmi` config section, the frozen `Config` |
| `lmi/commands/upgrade/installation.py` | **New.** Which installation this process runs from, and what to refuse |
| `lmi/commands/upgrade/pip.py` | **New.** The version probe and the one pip install command |
| `lmi/commands/upgrade/verify.py` | **New.** Running the installed console script and checking what it reports |
| `lmi/commands/upgrade/prompts.py` | **New.** This command's one question and its `NO_TERMINAL` text |
| `lmi/commands/upgrade/runner.py` | **New.** `run(args)` — the flow and the reporting |
| `lmi/commands/__init__.py` | **Modify.** One import, one list entry |
| `tests/test_core_config.py`, `tests/test_core_prompts.py` | **New.** What the promotion added: the parameterised purpose, section name and no-terminal text |
| `tests/commands/upgrade/` | **New.** `conftest.py` plus one test module per source module |
| `examples/lmi.json`, `config/lmi.json`, `tests/test_docs.py` | **Modify.** The `lmi` config section |
| `README.md`, `CLAUDE.md` | **Modify.** Documentation |

**Two deliberate deviations from the spec, both to reduce churn in shipped code:**

1. The spec (§6) says `install/prompts.py` moves to `core/`. This plan keeps `install/prompts.py` as a four-line delegating wrapper instead of deleting it, because `tests/commands/install/test_runner.py`'s `answers` fixture patches `prompts.confirm` / `prompts.secret` / `prompts.text` and is the seam the whole install flow is driven through. The guard still exists exactly once, in `core/prompts.py`, which is what §6 is actually asking for.
2. The spec (§6) says the discovery tests move. They do not need to: every test in `tests/commands/install/test_config.py` drives discovery through `config.build_config`, so they keep passing across the move unchanged — which makes them the proof that the promotion changed no behaviour. New tests for the *new* parameterisation go in `tests/test_core_config.py`.

---

### Task 1: Promote config-file discovery into `lmi/core/config.py`

**Files:**
- Create: `lmi/core/config.py`
- Modify: `lmi/commands/install/config.py`
- Create: `tests/test_core_config.py`

**Interfaces:**
- Consumes: `lmi.core.errors.{LmiError, EXIT_USAGE}`, `lmi.core.fs.{classify, FILE, UNKNOWN}`, `lmi.core.text.decode_with_bom`
- Produces, all used by Task 3:
  - `core.config.CONFIG_ENV_VAR`, `CWD_CONFIG_NAME`, `CWD_CONFIG_DIR`, `CWD_CONFIG`, `HOME_CONFIG`, `HELP` — strings
  - `core.config.add_argument(parser) -> None` — adds `--config PATH`
  - `core.config.find(explicit, purpose, example) -> Path`
  - `core.config.load(path) -> dict`
  - `core.config.section(doc, name, path, example) -> dict`
  - `core.config.expand(raw) -> Path`
  - `core.config.kind(path) -> str`

- [ ] **Step 1: Write the failing test for the two new parameters**

Create `tests/test_core_config.py`:

```python
"""What the promotion out of lmi/commands/install/ added.

Behaviour that existed before the move is pinned by
tests/commands/install/test_config.py, which drives all of it through
install's build_config and must keep passing unchanged. What is new here is
that the purpose sentence, the section name and the example are the caller's,
so two commands can share one file without either one's error message
mentioning the other.
"""

import json

import pytest

from lmi.core import config
from lmi.core.errors import LmiError

EXAMPLE = '{\n  "widget": {\n    "size": 3\n  }\n}'


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    return path


def test_the_purpose_sentence_is_the_callers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.delenv(config.CONFIG_ENV_VAR, raising=False)

    with pytest.raises(LmiError) as exc:
        config.find(None, "`lmi widget` needs one to know the size.", EXAMPLE)
    assert exc.value.code == 2
    assert "`lmi widget` needs one to know the size." in str(exc.value)
    assert "lmi install" not in str(exc.value)
    assert "widget" in str(exc.value)          # the example is printed too


def test_a_missing_section_names_the_section_asked_for(tmp_path):
    path = write(tmp_path / "lmi.json", {"claude": {}})
    with pytest.raises(LmiError) as exc:
        config.section(config.load(path), "lmi", path, EXAMPLE)
    assert exc.value.code == 2
    assert '"lmi" section' in str(exc.value)


def test_a_section_that_is_not_an_object_names_it_too(tmp_path):
    path = write(tmp_path / "lmi.json", {"lmi": "nope"})
    with pytest.raises(LmiError) as exc:
        config.section(config.load(path), "lmi", path, EXAMPLE)
    assert exc.value.code == 2
    assert '"lmi" section must be a JSON object' in str(exc.value)


def test_a_present_section_is_returned(tmp_path):
    path = write(tmp_path / "lmi.json", {"lmi": {"index": "https://x/"}})
    got = config.section(config.load(path), "lmi", path, EXAMPLE)
    assert got == {"index": "https://x/"}


def test_two_sections_live_in_one_file(tmp_path):
    """The whole point of the promotion: one file, two commands."""
    path = write(tmp_path / "lmi.json",
                 {"lmi": {"index": "https://i/"}, "claude": {"registry": "https://r/"}})
    doc = config.load(path)
    assert config.section(doc, "lmi", path, EXAMPLE)["index"] == "https://i/"
    assert config.section(doc, "claude", path, EXAMPLE)["registry"] == "https://r/"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_core_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lmi.core.config'`

- [ ] **Step 3: Create `lmi/core/config.py`**

This is a move, not a rewrite. Every message string below is copied verbatim from `lmi/commands/install/config.py` so the existing install tests keep passing; the only edits are the three `%s` slots for the purpose, the section name and the example.

```python
"""Finding, reading and parsing an lmi config file.

Promoted out of lmi/commands/install/config.py when `lmi upgrade` became the
second command to need it - which is the condition CLAUDE.md section 2 names
for moving something into core/: "then, not in advance".

What lives here has no command flavour: where the file is, how it is decoded,
how it is parsed, and the two refusals that must never quietly become
fall-throughs - an explicit --config that does not exist, and a file left at
the pre-move ./lmi.json. What a section *means* stays with the command that
owns it.
"""

import json
import os
from pathlib import Path

from . import fs
from .errors import EXIT_USAGE, LmiError
from .text import decode_with_bom

CONFIG_ENV_VAR = "LMI_CONFIG"
CWD_CONFIG_NAME = "lmi.json"
# The working-directory default lives in ./config/, not loose in the directory
# itself, so a checkout has one obvious place for it. Kept as two names because
# find() has to look for the pre-move path as well - see _refuse_legacy.
CWD_CONFIG_DIR = "config"
CWD_CONFIG = "%s/%s" % (CWD_CONFIG_DIR, CWD_CONFIG_NAME)
HOME_CONFIG = "~/.lmi/config.json"

HELP = "config file. Default: $%s, ./%s, %s" % (CONFIG_ENV_VAR, CWD_CONFIG,
                                                HOME_CONFIG)


def add_argument(parser):
    """The --config flag. One definition, so two commands cannot describe the
    same search order differently."""
    parser.add_argument("--config", dest="config", metavar="PATH", help=HELP)


# --- discovery ------------------------------------------------------------

def find(explicit, purpose, example):
    """The config file to read.

    `purpose` is one sentence saying what the calling command needs it for, and
    `example` a minimal file to paste; both appear only when nothing is found,
    where they are all the operator has to go on.
    """
    if explicit is not None:
        path = expand(explicit)
        # An explicit --config that does not exist must NOT fall through to the
        # next candidate. A named file that quietly resolves to a different one
        # is how a machine gets provisioned against the wrong registry.
        if kind(path) != fs.FILE:
            raise LmiError(
                "the config file given with --config does not exist: %s" % path,
                EXIT_USAGE,
            )
        return path

    candidates = []
    from_env = os.environ.get(CONFIG_ENV_VAR)
    if from_env:
        candidates.append(expand(from_env))
    in_cwd = Path.cwd() / CWD_CONFIG_DIR / CWD_CONFIG_NAME
    candidates.append(in_cwd)
    candidates.append(expand(HOME_CONFIG))

    for candidate in candidates:
        if kind(candidate) == fs.FILE:
            return candidate
        # Checked at the point in the order the old path used to occupy, so an
        # explicit --config or $LMI_CONFIG still wins and never sees this.
        if candidate == in_cwd:
            _refuse_legacy(Path.cwd() / CWD_CONFIG_NAME, in_cwd)
    raise LmiError(_nothing_found(candidates, purpose, example), EXIT_USAGE)


def _refuse_legacy(legacy, expected):
    """The working-directory default moved into ./config/. Say so; do not skip.

    Passing over a file at the old path is not harmless. The next candidate is
    ~/.lmi/config.json - a different registry, quite possibly a different site -
    and installing from it while an lmi.json sits in plain view in the working
    directory is exactly the wrong-registry provisioning that the --config rule
    above exists to prevent, reached from the other direction. It is also the
    silent kind: the run reports success and the machine is provisioned against
    the wrong source.
    """
    if kind(legacy) != fs.FILE:
        return
    raise LmiError(
        "the working-directory config file has moved into %s/, so %s is no "
        "longer read.\n"
        "    Move it:\n\n"
        "        mkdir -p %s && mv %s %s\n\n"
        "    or keep it where it is by naming it: --config %s"
        % (CWD_CONFIG_DIR, legacy, expected.parent, legacy, expected, legacy),
        EXIT_USAGE,
    )


def _nothing_found(candidates, purpose, example):
    return (
        "no config file found. %s\n"
        "    Looked in, in order:\n%s\n"
        "    Create one, or pass --config PATH. A minimal file:\n\n%s"
        % (purpose,
           "\n".join("      " + str(c) for c in candidates),
           "\n".join("      " + line for line in example.splitlines()))
    )


def expand(raw):
    """Path(raw).expanduser().absolute(), without the one way it explodes.

    expanduser() raises RuntimeError for a "~someuser" whose home it cannot look
    up - a typo in --config "~claude/lmi.json" is enough - and unguarded that
    reaches the CLI as a traceback and exit 1.
    """
    try:
        return Path(raw).expanduser().absolute()
    except RuntimeError as exc:
        raise LmiError(
            "the config file path cannot be expanded: %s (%s)" % (raw, exc),
            EXIT_USAGE,
        )


def kind(path):
    """fs.classify, but an unanswerable path is a usage error.

    Path.is_file() raises ENAMETOOLONG rather than returning False, so an
    over-long --config used to crash with a traceback and exit 1.
    """
    verdict, reason = fs.classify(path)
    if verdict == fs.UNKNOWN:
        raise LmiError(
            "the config file path cannot be used: %s (%s)" % (path, reason),
            EXIT_USAGE,
        )
    return verdict


# --- reading and parsing --------------------------------------------------

def load(path):
    """The whole document, as a dict-or-whatever-it-is. No section knowledge."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LmiError(
            "the config file cannot be read: %s (%s)" % (path, exc), EXIT_USAGE
        )
    # Through the BOM decoder because Notepad and PowerShell's Set-Content both
    # write a UTF-8 BOM, and json.loads rejects one with a bare "Expecting value".
    try:
        text = decode_with_bom(raw)
    except UnicodeDecodeError as exc:
        raise LmiError(
            "the config file is not UTF-8: %s (%s)" % (path, exc), EXIT_USAGE
        )
    try:
        return json.loads(text)
    except ValueError as exc:
        raise LmiError(
            "the config file is not valid JSON: %s (%s)" % (path, exc), EXIT_USAGE
        )


def section(doc, name, path, example):
    """One named top-level object out of a loaded document."""
    if not isinstance(doc, dict):
        raise LmiError(
            "the config file must contain a JSON object: %s" % path, EXIT_USAGE
        )
    found = doc.get(name)
    if found is None:
        raise LmiError(
            'the config file has no "%s" section: %s\n'
            "    Expected:\n\n%s"
            % (name, path,
               "\n".join("      " + l for l in example.splitlines())),
            EXIT_USAGE,
        )
    if not isinstance(found, dict):
        raise LmiError(
            'the "%s" section must be a JSON object: %s' % (name, path),
            EXIT_USAGE,
        )
    return found
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `python3 -m pytest tests/test_core_config.py -q`
Expected: PASS, 5 tests.

- [ ] **Step 5: Rewrite `lmi/commands/install/config.py` to delegate**

Delete from it: `CONFIG_ENV_VAR`/`CWD_*`/`HOME_CONFIG` as literals, `_find`, `_refuse_legacy`, `_nothing_found`, `_expand`, `_kind`, `_load`, `_section`, and the now-unused `json`, `os`, `fs`, `decode_with_bom` imports.

Keep everything else exactly as it is. Replace the top of the module with:

```python
"""Arguments, config-file discovery and validation for `lmi install`.

Validation lives with the command, not in cli.py, so cli.py stays pure
parse-and-dispatch as commands accumulate. Where the file *is* lives in
lmi/core/config.py, because `lmi upgrade` reads the same file - see
CLAUDE.md section 2 on promoting into core/.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from ...core import config as core_config
from ...core import fs
from ...core.errors import EXIT_USAGE, LmiError

# What this command installs. Deliberately not a config key: a command whose
# target is configurable is a different command.
PACKAGE = "@anthropic-ai/claude-code"

SECTION = "claude"
PURPOSE = "`lmi install` needs one to know which registry to install from."

# Re-exported so this module stays the one place install's own tests and
# tests/test_docs.py have to know about.
CONFIG_ENV_VAR = core_config.CONFIG_ENV_VAR
CWD_CONFIG_NAME = core_config.CWD_CONFIG_NAME
CWD_CONFIG_DIR = core_config.CWD_CONFIG_DIR
CWD_CONFIG = core_config.CWD_CONFIG
HOME_CONFIG = core_config.HOME_CONFIG
```

Then `DEFAULT_ENV` and `EXAMPLE` stay verbatim, and these three change:

```python
def add_arguments(parser):
    parser.add_argument(
        "target", choices=["claude"], metavar="TARGET",
        help="what to install. Only 'claude' is supported",
    )
    core_config.add_argument(parser)


def build_config(args):
    """Find, read and validate the config file. Never returns a partial Config."""
    path = core_config.find(getattr(args, "config", None), PURPOSE, EXAMPLE)
    section = core_config.section(core_config.load(path), SECTION, path, EXAMPLE)
    return Config(
        registry=_registry(section, path),
        cafile=_cafile(section, path),
        marketplaces=_object(section, "marketplaces", path),
        env=_env(section, path),
        source=path,
    )
```

and inside `_cafile`, the two former local helpers become the core ones:

```python
    resolved = core_config.expand(value)
    # Checked here rather than at npm time: `npm config set cafile /typo`
    # succeeds, and the mistake surfaces much later as an unrelated TLS error.
    if core_config.kind(resolved) != fs.FILE:
```

`Config`, `_registry`, `_object` and `_env` are unchanged.

- [ ] **Step 6: Run the whole suite — the install tests are the proof**

Run: `python3 -m pytest tests/ -q`
Expected: PASS, 274 + the 5 new ones = **279**. Every test in `tests/commands/install/test_config.py` and `tests/test_docs.py` must pass **unmodified**. If any of them needed editing, the move changed behaviour — revert and find out which message drifted.

- [ ] **Step 7: Commit**

```bash
git add lmi/core/config.py lmi/commands/install/config.py tests/test_core_config.py
git commit -m "refactor(core): promote config-file discovery out of lmi install

lmi upgrade reads the same file, which is the condition CLAUDE.md section 2
names for moving something into core/. The purpose sentence, the section name
and the pasteable example become the caller's, so neither command's error
message mentions the other. install's own config tests are unchanged and are
what proves no message drifted."
```

---

### Task 2: Promote the prompt guard into `lmi/core/prompts.py`

**Files:**
- Create: `lmi/core/prompts.py`
- Modify: `lmi/commands/install/prompts.py`
- Modify: `tests/commands/install/test_prompts.py` (one line — see Step 5)
- Create: `tests/test_core_prompts.py`

**Interfaces:**
- Consumes: `lmi.core.errors.{LmiError, EXIT_USAGE}`
- Produces, used by Task 7:
  - `core.prompts.NO_TERMINAL: str` — the generic message
  - `core.prompts.CANCELLED: str`
  - `core.prompts.confirm(question, default=False, no_terminal=NO_TERMINAL) -> bool`
  - `core.prompts.text(question, default=None, no_terminal=NO_TERMINAL) -> str`
  - `core.prompts.secret(question, no_terminal=NO_TERMINAL) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_core_prompts.py`:

```python
"""The shared prompt guard.

The behaviour of each question type is pinned by
tests/commands/install/test_prompts.py and must keep passing through the
delegating wrapper. What is new here is that the no-terminal message is the
caller's, so `lmi upgrade` does not tell the user about an auth token it never
asks for.
"""

import builtins

import pytest

from lmi.core import prompts
from lmi.core.errors import LmiError

MINE = "lmi widget is interactive and needs a terminal."


def eof(prompt=""):
    raise EOFError


def test_the_no_terminal_message_is_the_callers(monkeypatch):
    monkeypatch.setattr(builtins, "input", eof)
    with pytest.raises(LmiError) as exc:
        prompts.confirm("q?", no_terminal=MINE)
    assert exc.value.code == 2
    assert str(exc.value) == MINE


def test_secret_carries_the_callers_message_too(monkeypatch):
    monkeypatch.setattr(prompts.getpass, "getpass", eof)
    with pytest.raises(LmiError) as exc:
        prompts.secret("Token", no_terminal=MINE)
    assert str(exc.value) == MINE


def test_the_default_message_still_says_terminal(monkeypatch):
    """A caller that passes nothing must still fail fast, not hang."""
    monkeypatch.setattr(builtins, "input", eof)
    with pytest.raises(LmiError) as exc:
        prompts.confirm("q?")
    assert exc.value.code == 2
    assert "terminal" in str(exc.value)


def test_ctrl_c_is_cancelled_whatever_the_caller_said(monkeypatch):
    def interrupt(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr(builtins, "input", interrupt)
    with pytest.raises(LmiError) as exc:
        prompts.confirm("q?", no_terminal=MINE)
    assert exc.value.code == 2
    assert str(exc.value) == prompts.CANCELLED
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_core_prompts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lmi.core.prompts'`

- [ ] **Step 3: Create `lmi/core/prompts.py`**

The bodies are copied verbatim from `lmi/commands/install/prompts.py`; the only edit is the `no_terminal` parameter threaded through to `_ask`.

```python
"""Asking a question at a terminal, and the guard against hanging without one.

One module, so the guard exists exactly once. A command that is interactive by
design cannot be driven from a script - that is a decision, not a bug. What it
must never do is *hang*: with no terminal, input() and getpass() raise EOFError,
and an unguarded call would block a provisioning run forever with nothing to
answer it. That is the difference between "not scriptable" and "wedged", and
only the second is a bug.

The no-terminal message is the caller's, because it should say which questions
that particular command asks. Note that these commands are the reason invariant
3 in CLAUDE.md names `lmi schedule` rather than lmi as a whole.
"""

import getpass

from .errors import EXIT_USAGE, LmiError

NO_TERMINAL = (
    "this command is interactive and needs a terminal.\n"
    "    Run it directly in a terminal, not from a script, a pipe or a build step."
)

CANCELLED = "cancelled - nothing was changed."


def confirm(question, default=False, no_terminal=NO_TERMINAL):
    """A yes/no question. Anything but y/yes is no."""
    hint = " [Y/n]: " if default else " [y/N]: "
    answer = _ask(input, question + hint, no_terminal).strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def text(question, default=None, no_terminal=NO_TERMINAL):
    """A free-text answer. Blank takes `default`, or "" when there is none."""
    hint = " [%s]: " % default if default else ": "
    answer = _ask(input, question + hint, no_terminal).strip()
    return answer or (default or "")


def secret(question, no_terminal=NO_TERMINAL):
    """A secret answer, never echoed.

    getpass, not input: an echoed token lands in the terminal scrollback and in
    any recording of the session.
    """
    return _ask(getpass.getpass, question + ": ", no_terminal).strip()


def _ask(reader, prompt, no_terminal):
    try:
        return reader(prompt)
    except EOFError:
        raise LmiError(no_terminal, EXIT_USAGE)
    except KeyboardInterrupt:
        # Every prompt is asked before anything is modified, so Ctrl-C here is
        # genuinely a no-op - say so rather than printing a traceback.
        raise LmiError(CANCELLED, EXIT_USAGE)
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `python3 -m pytest tests/test_core_prompts.py -q`
Expected: PASS, 4 tests.

- [ ] **Step 5: Shrink `lmi/commands/install/prompts.py` to a wrapper**

Replace the whole file with:

```python
"""Every question `lmi install` asks.

The mechanics and the no-terminal guard live in lmi/core/prompts.py, because
`lmi upgrade` needs the same guard and duplicating a guard is how one copy of
it comes to be missing. What stays here is this command's own NO_TERMINAL text
- which names the questions this command actually asks - and the three entry
points that tests/commands/install/test_runner.py patches to drive the flow.
"""

import getpass  # noqa: F401 - kept so `prompts.getpass` still resolves

from ...core import prompts as _prompts
from ...core.prompts import CANCELLED  # noqa: F401

NO_TERMINAL = (
    "lmi install is interactive and needs a terminal.\n"
    "    It asks before repairing an existing install, for the Claude Code auth\n"
    "    token, and for the Git Bash path when it cannot find one.\n"
    "    Run it directly in a terminal, not from a script, a pipe or a build step."
)


def confirm(question, default=False):
    return _prompts.confirm(question, default, NO_TERMINAL)


def text(question, default=None):
    return _prompts.text(question, default, NO_TERMINAL)


def secret(question):
    return _prompts.secret(question, NO_TERMINAL)
```

Then change exactly one line in `tests/commands/install/test_prompts.py`. In `test_eof_from_getpass_is_also_a_usage_error`:

```python
    monkeypatch.setattr(prompts.getpass, "getpass", eof)
```

becomes

```python
    # The module object is shared, so patching it here is what core.prompts
    # sees. Named through core.prompts now that the call lives there.
    monkeypatch.setattr(core_prompts.getpass, "getpass", eof)
```

with `from lmi.core import prompts as core_prompts` added to that module's imports. **No other test in that file changes.** The `import getpass` retained in the wrapper is not what makes this work — the `getpass` module object is a singleton — but it keeps `prompts.getpass` a valid attribute for anyone who reaches for it.

- [ ] **Step 6: Run the whole suite**

Run: `python3 -m pytest tests/ -q`
Expected: PASS, 279 + the 4 new ones = **283**. `tests/commands/install/test_prompts.py` and `test_runner.py` must both be green; they are the proof the wrapper preserved behaviour.

- [ ] **Step 7: Commit**

```bash
git add lmi/core/prompts.py lmi/commands/install/prompts.py \
        tests/test_core_prompts.py tests/commands/install/test_prompts.py
git commit -m "refactor(core): promote the prompt guard out of lmi install

lmi upgrade asks a question too, and a guard that exists twice is a guard that
goes missing once. install/prompts.py stays as this command's NO_TERMINAL text
plus three delegations, which keeps the seam test_runner.py drives the flow
through."
```

---

### Task 3: The `upgrade` package, its config section, and registration

**Files:**
- Create: `lmi/commands/upgrade/__init__.py`
- Create: `lmi/commands/upgrade/exit_codes.py`
- Create: `lmi/commands/upgrade/config.py`
- Create: `lmi/commands/upgrade/runner.py` (a stub, replaced in Task 7)
- Modify: `lmi/commands/__init__.py`
- Modify: `examples/lmi.json`, `config/lmi.json`, `tests/test_docs.py`
- Create: `tests/commands/upgrade/__init__.py`
- Create: `tests/commands/upgrade/test_config.py`

**Interfaces:**
- Consumes: `core.config.{find, load, section, expand, kind, add_argument}` (Task 1), `core.errors`, `core.fs`
- Produces:
  - `upgrade.exit_codes.EXIT_PIP_FAILED = 1`, `EXIT_VERIFY_FAILED = 3`, `EXIT_INTERNAL = 4`
  - `upgrade.config.PACKAGE = "lmi"`, `SECTION = "lmi"`, `PURPOSE: str`, `EXAMPLE: str`
  - `upgrade.config.add_arguments(parser) -> None`
  - `upgrade.config.Config` — frozen dataclass, fields `index: str`, `cafile: Optional[Path]`, `source: Path`
  - `upgrade.config.build_config(args) -> Config`
  - `upgrade.NAME = "upgrade"`, `upgrade.HELP`, `upgrade.add_arguments`, `upgrade.run`

- [ ] **Step 1: Write the failing test**

Create `tests/commands/upgrade/__init__.py` (empty) and `tests/commands/upgrade/test_config.py`:

```python
"""The `lmi` section of the config file, and this command's arguments."""

import argparse
import json

import pytest

from lmi.commands.upgrade import config
from lmi.core.errors import LmiError

MINIMAL = {"lmi": {"index": "https://artifactory.example.com/api/pypi/x/simple/"}}


class Args:
    def __init__(self, config=None, version=None):
        self.config = config
        self.version = version


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    return path


def test_the_index_is_read(tmp_path):
    path = write(tmp_path / "lmi.json", MINIMAL)
    cfg = config.build_config(Args(config=str(path)))
    assert cfg.index == "https://artifactory.example.com/api/pypi/x/simple/"
    assert cfg.cafile is None
    assert cfg.source == path


@pytest.mark.parametrize("value", [None, "", "   ", 3, [], {}])
def test_a_missing_or_empty_index_is_a_usage_error(tmp_path, value):
    doc = {"lmi": {} if value is None else {"index": value}}
    path = write(tmp_path / "lmi.json", doc)
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert "index" in str(exc.value)


def test_a_file_with_only_a_claude_section_names_the_lmi_one(tmp_path):
    """The two commands share a file; the error must not be about the other."""
    path = write(tmp_path / "lmi.json", {"claude": {"registry": "https://r/"}})
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert '"lmi" section' in str(exc.value)


def test_cafile_must_exist(tmp_path):
    path = write(tmp_path / "lmi.json",
                 {"lmi": {"index": "https://i/", "cafile": str(tmp_path / "no.pem")}})
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert "cafile" in str(exc.value)


def test_cafile_that_exists_is_resolved(tmp_path):
    pem = tmp_path / "ca.pem"
    pem.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    path = write(tmp_path / "lmi.json",
                 {"lmi": {"index": "https://i/", "cafile": str(pem)}})
    assert config.build_config(Args(config=str(path))).cafile == pem


def test_missing_explicit_config_does_not_fall_through(tmp_path):
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(tmp_path / "nope.json")))
    assert exc.value.code == 2
    assert "does not exist" in str(exc.value)


def test_the_purpose_sentence_is_this_commands(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    with pytest.raises(LmiError) as exc:
        config.build_config(Args())
    assert "lmi upgrade" in str(exc.value)
    assert "registry" not in str(exc.value)


def test_the_arguments_parse(tmp_path):
    parser = argparse.ArgumentParser()
    config.add_arguments(parser)
    args = parser.parse_args(["--version", "0.2.0", "--config", "x.json"])
    assert args.version == "0.2.0"
    assert args.config == "x.json"
    assert parser.parse_args([]).version is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/commands/upgrade/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lmi.commands.upgrade'`

- [ ] **Step 3: Create the package**

`lmi/commands/upgrade/exit_codes.py`:

```python
"""Exit codes specific to `lmi upgrade`.

0 and 2 are global and live in lmi.core.errors. Everything else is this
command's own.

4 deliberately keeps the meaning it has in `lmi schedule` and `lmi install`:
a provisioning script should not have to learn a per-command definition of "a
bug in lmi".

3 is separate from 1 on purpose. By the time verification runs, pip has already
succeeded and the machine has changed, so reporting "the upgrade failed" would
be the wrong sentence - what happened is that it changed and cannot be
confirmed.

An installation shape that cannot be upgraded is NOT here: it is the global 2,
matching `lmi install` reporting a missing npm the same way. An environmental
precondition the user can fix is a usage error.
"""

EXIT_PIP_FAILED = 1
EXIT_VERIFY_FAILED = 3
EXIT_INTERNAL = 4
```

`lmi/commands/upgrade/config.py`:

```python
"""Arguments and the `lmi` config section for `lmi upgrade`.

Where the config file is, and how it is decoded and parsed, is
lmi/core/config.py's job. What the "lmi" section means is this module's.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ...core import config as core_config
from ...core import fs
from ...core.errors import EXIT_USAGE, LmiError

# What this command upgrades. Deliberately not a config key: a command whose
# target is configurable is a different command.
PACKAGE = "lmi"

SECTION = "lmi"
PURPOSE = "`lmi upgrade` needs one to know which package index to install from."

# Printed when no config file is found, so it is what a first-time operator
# pastes - with the command having just failed and nothing else on screen to
# copy from. Every key this command supports appears here. examples/lmi.json is
# the same section with real-looking URLs, and tests/test_docs.py pins the two
# key sets equal so they cannot drift apart.
EXAMPLE = """{
  "lmi": {
    "index": "https://artifactory.example.com/api/pypi/pypi-virtual/simple/",
    "cafile": "/etc/ssl/certs/corp-ca.pem"
  }
}"""


def add_arguments(parser):
    parser.add_argument(
        "--version", dest="version", metavar="VERSION",
        help="the version to install, e.g. 0.2.0. Default: the newest the "
             "index offers. Use it to go back to a known-good version",
    )
    core_config.add_argument(parser)


@dataclass(frozen=True)
class Config:
    index: str
    cafile: Optional[Path]
    source: Path


def build_config(args):
    """Find, read and validate the config file. Never returns a partial Config."""
    path = core_config.find(getattr(args, "config", None), PURPOSE, EXAMPLE)
    section = core_config.section(core_config.load(path), SECTION, path, EXAMPLE)
    return Config(
        index=_index(section, path),
        cafile=_cafile(section, path),
        source=path,
    )


def _index(section, path):
    value = section.get("index")
    if not isinstance(value, str) or not value.strip():
        raise LmiError(
            '"lmi.index" must be a non-empty string - the Python package index '
            "URL to install from: %s" % path,
            EXIT_USAGE,
        )
    return value.strip()


def _cafile(section, path):
    value = section.get("cafile")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LmiError('"lmi.cafile" must be a string: %s' % path, EXIT_USAGE)
    resolved = core_config.expand(value)
    # Checked here rather than at pip time: a wrong --cert surfaces much later
    # as an unrelated TLS error, on the far side of a question the user has
    # already answered yes to.
    if core_config.kind(resolved) != fs.FILE:
        raise LmiError(
            '"lmi.cafile" does not exist: %s (from %s)' % (resolved, path),
            EXIT_USAGE,
        )
    return resolved
```

`lmi/commands/upgrade/runner.py` — a stub for now, so the command is importable. Task 7 replaces it:

```python
"""The `lmi upgrade` flow. Filled in by Task 7."""

from ...core.errors import EXIT_OK


def run(args):
    raise NotImplementedError
```

`lmi/commands/upgrade/__init__.py`:

```python
"""`lmi upgrade` - install a newer lmi over this one.

The four-name command contract: NAME and HELP here, add_arguments from
config.py (validation lives with the command, not in cli.py) and run from
runner.py.
"""

from .config import add_arguments  # noqa: F401
from .runner import run  # noqa: F401

NAME = "upgrade"
HELP = "Upgrade lmi itself from the configured package index"
```

- [ ] **Step 4: Register the command**

`lmi/commands/__init__.py` — one import, one list entry:

```python
from . import install, schedule, upgrade

COMMANDS = [install, schedule, upgrade]
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `python3 -m pytest tests/commands/upgrade/test_config.py tests/test_cli.py -q`
Expected: PASS. The `test_cli.py` run confirms the registry addition did not break `--help` or dispatch.

- [ ] **Step 6: Add the `lmi` section to the shipped config files**

`examples/lmi.json` becomes the union of both commands' sections:

```json
{
  "lmi": {
    "index": "https://artifactory.example.com/api/pypi/pypi-virtual/simple/",
    "cafile": "/etc/ssl/certs/corp-ca.pem"
  },
  "claude": {
    "registry": "https://artifactory.example.com/api/npm/npm-virtual/",
    "cafile": "/etc/ssl/certs/corp-ca.pem",
    "marketplaces": {
      "corp-tools": {
        "source": {
          "source": "git",
          "url": "https://git.example.com/claude/marketplace.git"
        }
      }
    },
    "env": {
      "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000",
      "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "204800",
      "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"
    }
  }
}
```

`config/lmi.json` — the repo's own working config — gains a matching section pointing at public PyPI, since that is what this checkout's `claude.registry` already does:

```json
{
  "lmi": {
    "index": "https://pypi.org/simple/"
  },
  "claude": {
    "registry": "https://registry.npmjs.org/",
    "env": {
      "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000",
      "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "204800",
      "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"
    }
  }
}
```

- [ ] **Step 7: Teach `tests/test_docs.py` about the second section**

Add `from lmi.commands.upgrade import config as upgrade_config` to its imports, and add these two tests. Change `test_the_example_documents_every_supported_key` and `test_the_printed_example_matches_the_shipped_one` **not at all** — they already read only `doc["claude"]`, which is the point of pinning per section.

```python
def test_the_example_documents_every_upgrade_key():
    doc = json.loads((REPO / "examples" / "lmi.json").read_text(encoding="utf-8"))
    assert set(doc["lmi"]) == {"index", "cafile"}


def test_the_printed_upgrade_example_matches_the_shipped_one():
    """upgrade's EXAMPLE is pasted by an operator whose command just failed.

    Pinned against its own section rather than the whole document, so the two
    commands can each document their own keys without either one having to know
    about the other.
    """
    printed = json.loads(upgrade_config.EXAMPLE)
    shipped = json.loads((REPO / "examples" / "lmi.json").read_text(
        encoding="utf-8"))
    assert set(printed["lmi"]) == set(shipped["lmi"])
```

And add a test that the shipped example still validates, mirroring the existing claude one:

```python
def test_the_example_config_is_accepted_by_the_upgrade_validator(tmp_path):
    example = REPO / "examples" / "lmi.json"
    doc = json.loads(example.read_text(encoding="utf-8"))
    pem = tmp_path / "ca.pem"
    pem.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    doc["lmi"]["cafile"] = str(pem)
    staged = tmp_path / "lmi.json"
    with open(str(staged), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)

    cfg = upgrade_config.build_config(Args(str(staged)))
    assert cfg.index
    assert cfg.cafile == pem
```

Note `test_docs.Args` already takes `(config, target="claude")`; `upgrade.build_config` reads only `.config` and `.version`, so give the class a `version = None` class attribute:

```python
class Args:
    version = None

    def __init__(self, config, target="claude"):
        self.config = config
        self.target = target
```

- [ ] **Step 8: Run the whole suite**

Run: `python3 -m pytest tests/ -q`
Expected: PASS. The total is the previous one plus the tests this task added — note that `test_a_missing_or_empty_index_is_a_usage_error` is parametrised six ways, so `test_config.py` contributes 13, not 8. **Report the number you actually saw** rather than the one this plan predicts; from here on the arithmetic matters less than the fact that nothing went red.

- [ ] **Step 9: Commit**

```bash
git add lmi/commands/upgrade lmi/commands/__init__.py examples/lmi.json \
        config/lmi.json tests/commands/upgrade tests/test_docs.py
git commit -m "feat(upgrade): the command package, its config section, registration

One import and one list entry in commands/__init__.py; cli.py is untouched.
The 'lmi' section names the internal Python index and an optional CA file, and
examples/lmi.json becomes the union of both commands' sections with each one
pinned against its own."
```

---

### Task 4: Which installation is this? (`installation.py`)

**Files:**
- Create: `lmi/commands/upgrade/installation.py`
- Create: `tests/commands/upgrade/test_installation.py`

**Interfaces:**
- Consumes: `lmi.core.errors.{LmiError, EXIT_USAGE}`
- Produces, used by Tasks 5, 6 and 7:
  - `installation.VENV = "venv"`, `installation.USER_SITE = "user site"`
  - `installation.Installation` — frozen dataclass with fields `kind: str`, `pip_prefix: List[str]`, `user_flag: bool`, `script: Path`, `where: Path`
  - `installation.detect() -> Installation` — raises `LmiError(…, EXIT_USAGE)` for anything it will not upgrade

**The testability rule for this module:** every fact it needs comes from its own one-line helper (`_package_dir`, `_prefix`, `_base_prefix`, `_executable`, `_scripts_dir`, `_user_scripts_dir`, `_user_site_dir`, `_editable`, `_has_pip`, `_base_python`, `_on_windows`). Tests replace the *fact*, never `sys.prefix` itself. This is the same reason `schedule/paths.py` has `_on_windows` rather than reading `os.name` at the point of use, and the fixture table in `CLAUDE.md` §5 says so explicitly.

- [ ] **Step 1: Write the failing tests, two of them MANDATORY**

Create `tests/commands/upgrade/test_installation.py`:

```python
"""Which installation `lmi upgrade` is running from, and what it refuses.

A wrong answer here is silent in this project's sense: pip reports success, the
command still runs, and it is either the old code or a second copy that nothing
on PATH reaches.
"""

import os
from pathlib import Path

import pytest

from lmi.commands.upgrade import installation
from lmi.core.errors import LmiError


@pytest.fixture
def venv(tmp_path, monkeypatch):
    """A convincing virtual environment with lmi installed into it."""
    prefix = tmp_path / "venv"
    scripts = prefix / ("Scripts" if os.name == "nt" else "bin")
    site_packages = prefix / "site-packages"
    (site_packages / "lmi").mkdir(parents=True)
    scripts.mkdir(parents=True)
    (scripts / ("lmi.exe" if os.name == "nt" else "lmi")).write_text("x")

    monkeypatch.setattr(installation, "_editable", lambda: False)
    monkeypatch.setattr(installation, "_prefix", lambda: prefix)
    monkeypatch.setattr(installation, "_base_prefix", lambda: tmp_path / "usr")
    monkeypatch.setattr(installation, "_package_dir", lambda: site_packages / "lmi")
    monkeypatch.setattr(installation, "_executable", lambda: scripts / "python")
    monkeypatch.setattr(installation, "_scripts_dir", lambda: scripts)
    monkeypatch.setattr(installation, "_user_site_dir", lambda: tmp_path / "usersite")
    monkeypatch.setattr(installation, "_has_pip", lambda python: True)
    return prefix


def test_a_venv_install_is_upgraded_with_its_own_python(venv):
    inst = installation.detect()
    assert inst.kind == installation.VENV
    assert inst.user_flag is False
    assert inst.pip_prefix[1:] == ["-m", "pip"]
    assert Path(inst.pip_prefix[0]).name.startswith("python")
    assert inst.script.name.startswith("lmi")
    assert inst.where == venv


def test_a_venv_without_pip_borrows_the_base_python(venv, monkeypatch, tmp_path):
    """Debian and Ubuntu force `venv --without-pip`; install-linux.sh has the
    same fallback and this must not be the one place that forgets it."""
    monkeypatch.setattr(installation, "_has_pip", lambda python: False)
    monkeypatch.setattr(installation, "_base_python", lambda: tmp_path / "usr" / "bin" / "python3")

    inst = installation.detect()
    assert inst.pip_prefix[1:3] == ["-m", "pip"]
    assert inst.pip_prefix[3] == "--python"
    assert inst.pip_prefix[4].endswith("python")


def test_no_pip_anywhere_is_a_usage_error_naming_the_package(venv, monkeypatch):
    monkeypatch.setattr(installation, "_has_pip", lambda python: False)
    monkeypatch.setattr(installation, "_base_python", lambda: None)
    with pytest.raises(LmiError) as exc:
        installation.detect()
    assert exc.value.code == 2
    assert "python3-venv" in str(exc.value)


def test_an_editable_checkout_is_refused(venv, monkeypatch):
    """MANDATORY. Silent: a released wheel installed over a developer's working
    tree looks exactly like a successful upgrade, and their uncommitted work is
    gone. Checked before the venv rule because a dev checkout is usually inside
    one, so the venv rule would otherwise claim it."""
    monkeypatch.setattr(installation, "_editable", lambda: True)
    with pytest.raises(LmiError) as exc:
        installation.detect()
    assert exc.value.code == 2
    assert "editable" in str(exc.value)
    assert "pip install -e" in str(exc.value)


def test_a_pipx_installation_is_refused(venv, monkeypatch, tmp_path):
    """MANDATORY. Silent: pipx's metadata goes on describing a version that is
    no longer installed, and `pipx list` reports the old one forever."""
    (tmp_path / "venv" / "pipx_metadata.json").write_text("{}")
    with pytest.raises(LmiError) as exc:
        installation.detect()
    assert exc.value.code == 2
    assert "pipx upgrade lmi" in str(exc.value)


def test_a_user_site_install_gets_the_user_flag(tmp_path, monkeypatch):
    usersite = tmp_path / "usersite"
    (usersite / "lmi").mkdir(parents=True)
    scripts = tmp_path / "userscripts"
    scripts.mkdir()

    monkeypatch.setattr(installation, "_editable", lambda: False)
    monkeypatch.setattr(installation, "_prefix", lambda: tmp_path / "usr")
    monkeypatch.setattr(installation, "_base_prefix", lambda: tmp_path / "usr")
    monkeypatch.setattr(installation, "_package_dir", lambda: usersite / "lmi")
    monkeypatch.setattr(installation, "_executable", lambda: tmp_path / "usr" / "python")
    monkeypatch.setattr(installation, "_user_site_dir", lambda: usersite)
    monkeypatch.setattr(installation, "_user_scripts_dir", lambda: scripts)

    inst = installation.detect()
    assert inst.kind == installation.USER_SITE
    assert inst.user_flag is True
    assert inst.script.parent == scripts


def test_a_system_install_is_refused(tmp_path, monkeypatch):
    """Neither a venv nor user site: a system site-packages, a checkout on
    PYTHONPATH, something unpacked by hand. Guessing --user here writes a
    second copy that the PATH entry never reaches, and reports success."""
    monkeypatch.setattr(installation, "_editable", lambda: False)
    monkeypatch.setattr(installation, "_prefix", lambda: tmp_path / "usr")
    monkeypatch.setattr(installation, "_base_prefix", lambda: tmp_path / "usr")
    monkeypatch.setattr(installation, "_package_dir", lambda: tmp_path / "src" / "lmi")
    monkeypatch.setattr(installation, "_executable", lambda: tmp_path / "usr" / "python")
    monkeypatch.setattr(installation, "_user_site_dir", lambda: tmp_path / "usersite")

    with pytest.raises(LmiError) as exc:
        installation.detect()
    assert exc.value.code == 2
    assert str(tmp_path / "src" / "lmi") in str(exc.value)


def test_a_venv_whose_lmi_is_somewhere_else_is_refused(venv, monkeypatch, tmp_path):
    """Inside a venv, but lmi is being imported from a checkout on PYTHONPATH.
    Upgrading the venv would leave the checkout still shadowing it."""
    monkeypatch.setattr(installation, "_package_dir", lambda: tmp_path / "src" / "lmi")
    with pytest.raises(LmiError) as exc:
        installation.detect()
    assert exc.value.code == 2
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/commands/upgrade/test_installation.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lmi.commands.upgrade.installation'`

- [ ] **Step 3: Write `lmi/commands/upgrade/installation.py`**

```python
"""Which lmi installation is this process running from?

Answered before anything else happens and before the user is asked anything,
because a wrong answer is silent: pip reports success, the command still runs,
and it is either the old code or a second copy that nothing on PATH reaches.

Every fact this module needs comes from its own one-line helper, so a test can
replace the fact rather than sys itself - the same reason schedule/paths.py has
_on_windows instead of reading os.name where it is used.

The order of the checks in detect() is load-bearing. An editable checkout is
almost always *also* inside a virtual environment, so the venv rule would claim
it if it went first.
"""

import json
import os
import shutil
import site
import subprocess
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import List

from ...core.errors import EXIT_USAGE, LmiError

VENV = "venv"
USER_SITE = "user site"

EDITABLE = (
    "this lmi is an editable install (pip install -e) from %s.\n"
    "    `lmi upgrade` will not install a released wheel over a working tree:\n"
    "    it would look exactly like a successful upgrade and replace whatever\n"
    "    is uncommitted there.\n"
    "    Use git in that checkout, or install a wheel somewhere else."
)

PIPX = (
    "this lmi was installed by pipx (%s).\n"
    "    Upgrading it from underneath pipx leaves pipx's own record describing\n"
    "    a version that is no longer installed. Use pipx instead:\n\n"
    "        pipx upgrade lmi\n"
)

UNSUPPORTED = (
    "lmi is installed somewhere `lmi upgrade` does not know how to replace:\n"
    "      package:     %s\n"
    "      interpreter: %s\n"
    "    It upgrades the two installations the install scripts produce - a\n"
    "    virtual environment of its own, and a `pip install --user` - and\n"
    "    refuses anything else rather than guessing, because a wrong guess\n"
    "    installs a second copy that nothing on PATH ever reaches.\n"
    "    Re-install with scripts/install-linux.sh, install-macos.sh or\n"
    "    install-windows.cmd, or upgrade with pip yourself."
)

NO_PIP = (
    "the virtual environment at %s has no pip, and no python3 outside it could\n"
    "    be found to lend one.\n"
    "    On Debian and Ubuntu this is one missing package:\n\n"
    "        sudo apt install python3-venv\n"
)


@dataclass(frozen=True)
class Installation:
    kind: str
    pip_prefix: List[str]   # argv up to but not including "install"
    user_flag: bool         # whether pip needs --user
    script: Path            # the installed `lmi` command, for verification
    where: Path             # what to name in messages


def detect():
    """The installation to upgrade, or a usage error saying why not."""
    if _editable():
        raise LmiError(EDITABLE % _package_dir(), EXIT_USAGE)

    marker = _prefix() / "pipx_metadata.json"
    if marker.exists():
        raise LmiError(PIPX % _prefix(), EXIT_USAGE)

    package = _package_dir()
    if _prefix() != _base_prefix() and _within(package, _prefix()):
        return _venv_installation()
    if _within(package, _user_site_dir()):
        return _user_installation()
    raise LmiError(UNSUPPORTED % (package, _executable()), EXIT_USAGE)


def _venv_installation():
    python = _executable()
    script = _scripts_dir() / _script_name()
    if _has_pip(python):
        prefix = [str(python), "-m", "pip"]
    else:
        # Debian and Ubuntu ship venv's bootstrap separately, so a venv created
        # with --without-pip has none of its own. A pip outside it can still
        # populate it: --python must come before the subcommand and needs pip
        # 22.3 or newer. install-linux.sh does exactly this.
        base = _base_python()
        if base is None:
            raise LmiError(NO_PIP % _prefix(), EXIT_USAGE)
        prefix = [str(base), "-m", "pip", "--python", str(python)]
    return Installation(VENV, prefix, False, script, _prefix())


def _user_installation():
    return Installation(
        USER_SITE,
        [str(_executable()), "-m", "pip"],
        True,
        _user_scripts_dir() / _script_name(),
        _user_site_dir(),
    )


# --- the facts, each replaceable by a test --------------------------------

def _package_dir():
    """Where the lmi package being run was imported from."""
    import lmi
    return Path(lmi.__file__).resolve().parent


def _prefix():
    return Path(sys.prefix)


def _base_prefix():
    return Path(getattr(sys, "base_prefix", sys.prefix))


def _executable():
    return Path(sys.executable)


def _scripts_dir():
    """This environment's console-script directory - bin/ or Scripts\\."""
    return Path(sysconfig.get_path("scripts"))


def _user_scripts_dir():
    r"""The --user console-script directory.

    From sysconfig, deliberately not %APPDATA%\Python\PythonXX\Scripts: the
    answer differs between installs, and a Microsoft Store Python inserts a
    version level. install-windows.ps1 asks the same question the same way.
    """
    if hasattr(sysconfig, "get_preferred_scheme"):
        scheme = sysconfig.get_preferred_scheme("user")
    else:
        scheme = "nt_user" if _on_windows() else "posix_user"
    return Path(sysconfig.get_path("scripts", scheme))


def _user_site_dir():
    return Path(site.getusersitepackages())


def _script_name():
    return "lmi.exe" if _on_windows() else "lmi"


def _on_windows():
    """os.name == "nt", in a form a test can override.

    Monkeypatching os.name itself is not an option: pathlib chooses its
    concrete class from it at instantiation, so setting it to "nt" on Linux
    makes every Path() raise NotImplementedError - including pytest's own.
    """
    return os.name == "nt"


def _editable():
    """Does this lmi's install record say it is editable?

    direct_url.json with dir_info.editable is what pip writes for
    `pip install -e`. Any failure to read it means "not editable" - a source
    tree with no install record at all lands in UNSUPPORTED below, which says
    more.
    """
    try:
        from importlib import metadata
        raw = metadata.distribution("lmi").read_text("direct_url.json")
    except Exception:                       # noqa: BLE001 - any failure is "no"
        return False
    if not raw:
        return False
    try:
        doc = json.loads(raw)
    except ValueError:
        return False
    info = doc.get("dir_info")
    return bool(isinstance(info, dict) and info.get("editable"))


def _has_pip(python):
    try:
        done = subprocess.run(
            [str(python), "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return done.returncode == 0


def _base_python():
    """A python outside this venv, to lend it a pip. None if there is none."""
    candidate = getattr(sys, "_base_executable", None)
    if candidate and Path(candidate) != _executable():
        return Path(candidate)
    found = shutil.which("python3") or shutil.which("python")
    return Path(found) if found else None


def _within(child, parent):
    """Is `child` inside `parent`? Never raises for an odd path."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/commands/upgrade/test_installation.py -q`
Expected: PASS, 8 tests.

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m pytest tests/ -q`
Expected: PASS, the previous total plus the 8 new ones. Report the actual number.

- [ ] **Step 6: Commit**

```bash
git add lmi/commands/upgrade/installation.py \
        tests/commands/upgrade/test_installation.py
git commit -m "feat(upgrade): detect the installation, and refuse the ones we cannot

An editable checkout and a pipx install are refused before pip is ever
invoked - both MANDATORY tests, both silent failures if guessed at. A venv
without pip borrows a base python the way install-linux.sh does. Anything that
is neither a venv nor a --user install is refused rather than guessed."
```

---

### Task 5: The pip module and the `fake_pip` fixture

**Files:**
- Create: `tests/commands/upgrade/conftest.py`
- Create: `lmi/commands/upgrade/pip.py`
- Create: `tests/commands/upgrade/test_pip.py`

**Interfaces:**
- Consumes: `upgrade.config.{PACKAGE, Config}`, `upgrade.exit_codes.EXIT_PIP_FAILED`, `upgrade.installation.Installation`
- Produces, used by Task 7:
  - `pip.latest(inst, cfg) -> Optional[str]`
  - `pip.install(inst, cfg, version, say) -> None` — `version` is `Optional[str]`; `None` means `--upgrade lmi`. Raises `LmiError(…, EXIT_PIP_FAILED)`.

- [ ] **Step 1: Write the fixture**

Create `tests/commands/upgrade/conftest.py`:

```python
"""Fixtures for the `lmi upgrade` suite.

pip is never found on PATH - it is always `<interpreter> -m pip` - so the seam
is the interpreter. `fake_pip` gives you one that records argv and answers
`index versions`, and an Installation pointing at it. Nothing here may reach a
real pip or a real index: a real one would install a real package over the
developer's own lmi.
"""

import os
import stat
import sys

import pytest

from lmi.commands.upgrade import installation

FAKE_PIP = """\
#!{python}
import os, sys

n_file = os.environ["FAKE_PIP_COUNT"]
n = 0
if os.path.exists(n_file):
    n = int(open(n_file).read() or 0)
n += 1
open(n_file, "w").write(str(n))

with open(os.path.join(os.environ["FAKE_PIP_DIR"], "argv-%d.txt" % n), "w") as fh:
    fh.write("\\n".join(sys.argv[1:]))

if "index" in sys.argv and "versions" in sys.argv:
    latest = os.environ.get("FAKE_PIP_LATEST")
    if not latest:
        # The shape of a pip too old for the subcommand, which must degrade
        # the question rather than fail the command.
        sys.stderr.write("ERROR: unknown command \\"index\\"\\n")
        sys.exit(2)
    sys.stdout.write("lmi (%s)\\n" % latest)
    sys.stdout.write("Available versions: %s\\n" % latest)
    sys.exit(0)

print("fake pip call %d: %s" % (n, " ".join(sys.argv[1:])))
sys.exit(int(os.environ.get("FAKE_PIP_RC", "0")))
"""

FAKE_SCRIPT = """\
#!{python}
import os, sys
rc = int(os.environ.get("FAKE_SCRIPT_RC", "0"))
if rc:
    sys.stderr.write("boom\\n")
    sys.exit(rc)
sys.stdout.write("lmi %s\\n" % os.environ.get("FAKE_SCRIPT_VERSION", "0.1.0"))
"""


def _executable(path, body):
    path.write_text(body.format(python=sys.executable), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


class Pip:
    def __init__(self, exe, recdir, count_file, script):
        self.exe = exe
        self.dir = recdir
        self.count_file = count_file
        self.script = script

    def calls(self):
        """Every invocation's argv, in order."""
        return [
            (self.dir / ("argv-%d.txt" % i)).read_text(
                encoding="utf-8").splitlines()
            for i in range(1, self.count() + 1)
        ]

    def count(self):
        return int(self.count_file.read_text() or 0)

    def installation(self, kind=installation.VENV, user_flag=False):
        return installation.Installation(
            kind=kind,
            pip_prefix=[str(self.exe), "-m", "pip"],
            user_flag=user_flag,
            script=self.script,
            where=self.exe.parent,
        )


@pytest.fixture
def fake_pip(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = _executable(bindir / "python", FAKE_PIP)
    script = _executable(bindir / "lmi", FAKE_SCRIPT)

    recdir = tmp_path / "piprec"
    recdir.mkdir()
    count_file = tmp_path / "pipcount.txt"
    count_file.write_text("0")

    monkeypatch.setenv("FAKE_PIP_DIR", str(recdir))
    monkeypatch.setenv("FAKE_PIP_COUNT", str(count_file))
    return Pip(exe, recdir, count_file, script)
```

**Windows note:** these two fakes are invoked by absolute path, not through `PATH`, and Windows has no `#!` mechanism — so on Windows they would need the `.py` + `.cmd` pairing that `fake_npm` uses. The suite's Windows story is already partial (`CLAUDE.md` §5), and this fixture is POSIX-shaped like the others. Do not spend time on a Windows variant; the shipped code is what matters there, and §11 of the spec puts the real Windows question on the README list.

- [ ] **Step 2: Write the failing tests**

Create `tests/commands/upgrade/test_pip.py`:

```python
"""Building and running the one pip command, and the version probe."""

import os
from pathlib import Path

import pytest

from lmi.commands.upgrade import config, pip
from lmi.core.errors import LmiError

INDEX = "https://artifactory.example.com/api/pypi/pypi-virtual/simple/"


def cfg(cafile=None):
    return config.Config(index=INDEX, cafile=cafile, source=Path("lmi.json"))


def said(lines):
    return lambda message="": lines.append(message)


def test_install_pins_the_version_and_names_the_index(fake_pip):
    lines = []
    pip.install(fake_pip.installation(), cfg(), "0.2.0", said(lines))

    argv = fake_pip.calls()[0]
    assert argv[:3] == ["-m", "pip", "install"]
    assert "--index-url" in argv
    assert argv[argv.index("--index-url") + 1] == INDEX
    assert "--extra-index-url" not in argv
    assert "--no-deps" in argv
    assert argv[-1] == "lmi==0.2.0"
    assert "--user" not in argv


def test_no_version_becomes_upgrade_lmi(fake_pip):
    pip.install(fake_pip.installation(), cfg(), None, said([]))
    argv = fake_pip.calls()[0]
    assert argv[-2:] == ["--upgrade", "lmi"]


def test_a_cafile_becomes_cert_not_cafile(fake_pip, tmp_path):
    """pip's option is --cert. npm's is cafile; they are not the same flag."""
    pem = tmp_path / "ca.pem"
    pem.write_bytes(b"x")
    pip.install(fake_pip.installation(), cfg(cafile=pem), "0.2.0", said([]))
    argv = fake_pip.calls()[0]
    assert argv[argv.index("--cert") + 1] == str(pem)
    assert "cafile" not in argv


def test_the_user_flag_appears_only_for_a_user_site_install(fake_pip):
    pip.install(fake_pip.installation(user_flag=True), cfg(), "0.2.0", said([]))
    assert "--user" in fake_pip.calls()[0]


def test_a_failing_pip_is_exit_1_and_names_the_index(fake_pip, monkeypatch):
    monkeypatch.setenv("FAKE_PIP_RC", "1")
    with pytest.raises(LmiError) as exc:
        pip.install(fake_pip.installation(), cfg(), "0.2.0", said([]))
    assert exc.value.code == 1
    assert "index" in str(exc.value)


@pytest.mark.skipif(os.name != "nt", reason="the clause is Windows-only")
def test_the_windows_failure_names_the_running_exe(fake_pip, monkeypatch):
    monkeypatch.setenv("FAKE_PIP_RC", "1")
    with pytest.raises(LmiError) as exc:
        pip.install(fake_pip.installation(), cfg(), "0.2.0", said([]))
    assert "lmi.exe" in str(exc.value)


def test_the_probe_reads_the_newest_version(fake_pip, monkeypatch):
    monkeypatch.setenv("FAKE_PIP_LATEST", "0.9.0")
    assert pip.latest(fake_pip.installation(), cfg()) == "0.9.0"
    argv = fake_pip.calls()[0]
    assert argv[:4] == ["-m", "pip", "index", "versions"]
    assert argv[4] == "lmi"
    assert argv[argv.index("--index-url") + 1] == INDEX


def test_a_probe_that_fails_is_none_not_an_error(fake_pip, monkeypatch):
    """An older pip has no `index` subcommand. That must degrade the question,
    never fail the command - a diagnostic may not block the thing it
    diagnoses."""
    monkeypatch.delenv("FAKE_PIP_LATEST", raising=False)
    assert pip.latest(fake_pip.installation(), cfg()) is None


def test_a_probe_that_cannot_even_run_is_none(fake_pip, tmp_path):
    gone = fake_pip.installation()
    broken = type(gone)(gone.kind, [str(tmp_path / "nope")] + gone.pip_prefix[1:],
                        gone.user_flag, gone.script, gone.where)
    assert pip.latest(broken, cfg()) is None
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python3 -m pytest tests/commands/upgrade/test_pip.py -q`
Expected: FAIL — `ImportError: cannot import name 'pip'`

- [ ] **Step 4: Write `lmi/commands/upgrade/pip.py`**

```python
"""The one pip command, and the read-only probe that precedes it.

Every invocation is a list argv through subprocess.run, with the shell never
invoked: the index URL comes from a config file and must never reach a shell.
The install's output is inherited rather than captured, so pip's own progress
and errors reach the user as they happen, and check=False so a non-zero exit
returns instead of raising.

Note this module is named `pip` and lives inside a package, so `import pip`
elsewhere still finds the real one; nothing here imports pip as a library.
"""

import os
import re
import subprocess

from .config import PACKAGE
from .exit_codes import EXIT_PIP_FAILED
from ...core.errors import LmiError

# `pip index versions lmi` answers with "lmi (0.9.0)" on the first line and
# "Available versions: ..." on the second. Anchored per line, and any failure
# to match is None rather than an error - see latest().
LATEST_RE = re.compile(r"^\s*%s\s*\((.+?)\)\s*$" % re.escape(PACKAGE), re.MULTILINE)

# Two hypotheses, not one, and pip's own output is inherited so it appears
# immediately above this. The Windows clause is printed on every Windows
# failure without inspecting pip's text: pattern-matching an error message to
# decide whether to offer help is a guess that goes stale with the next pip
# release, and an extra clause on a platform where it is plausible costs
# nothing.
INSTALL_FAILED = (
    "pip install %s failed (exit %d).\n"
    "    pip's own output above says which of these it was:\n"
    "      - the index, if pip reported a network error or a 404. Check the\n"
    '        "index" value in the config file, and that it really carries lmi -\n'
    "        lmi does not populate it.\n"
)

WINDOWS_CLAUSE = (
    "      - the lmi.exe being replaced is the one running this command. If pip\n"
    "        reported a permission or access error, run this from a shell where\n"
    "        no lmi is live:\n\n"
    "          python -m pip install --user --upgrade --index-url %s lmi\n"
)


def _index_argv(cfg):
    argv = ["--index-url", cfg.index]
    if cfg.cafile:
        # pip's option is --cert. npm's is cafile; they are not interchangeable.
        argv += ["--cert", str(cfg.cafile)]
    return argv


def latest(inst, cfg):
    """The newest version the index offers, or None if it cannot say.

    Best-effort by design. `pip index` is an experimental subcommand that an
    older pip does not have at all, and its output could change. Every failure
    is None, which degrades the question the user is asked - it must never
    degrade the command, because a diagnostic that blocks the thing it
    diagnoses is worse than no diagnostic.
    """
    argv = inst.pip_prefix + ["index", "versions", PACKAGE] + _index_argv(cfg)
    try:
        done = subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL)
    except OSError:
        return None
    if done.returncode != 0:
        return None
    match = LATEST_RE.search(done.stdout.decode("utf-8", "replace"))
    return match.group(1).strip() if match else None


def install(inst, cfg, version, say):
    """Install `version`, or the newest when it is None."""
    argv = inst.pip_prefix + ["install"]
    if inst.user_flag:
        argv.append("--user")
    argv += _index_argv(cfg)
    # --no-deps: lmi declares no dependencies and tests/test_packaging.py fails
    # if that stops being true, so this changes nothing about a correct install
    # - and it means a wrong or tampered package on the index cannot pull
    # anything else onto the machine.
    argv.append("--no-deps")
    if version is None:
        argv += ["--upgrade", PACKAGE]
    else:
        argv.append("%s==%s" % (PACKAGE, version))

    say("  $ " + " ".join(argv))
    code = subprocess.run(argv).returncode
    if code != 0:
        what = PACKAGE if version is None else "%s==%s" % (PACKAGE, version)
        message = INSTALL_FAILED % (what, code)
        if os.name == "nt":
            message += WINDOWS_CLAUSE % cfg.index
        raise LmiError(message, EXIT_PIP_FAILED)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/commands/upgrade/test_pip.py -q`
Expected: PASS, 9 tests (one skipped off Windows).

- [ ] **Step 6: Run the whole suite**

Run: `python3 -m pytest tests/ -q`
Expected: PASS, the previous total plus 8 passed and 1 skipped — the skip is the Windows-only clause test, and it is expected on Linux and macOS. Report the actual numbers.

- [ ] **Step 7: Commit**

```bash
git add lmi/commands/upgrade/pip.py tests/commands/upgrade/conftest.py \
        tests/commands/upgrade/test_pip.py
git commit -m "feat(upgrade): the pip invocation and the best-effort version probe

--index-url replaces the default index rather than extending it, so an
air-gapped machine cannot silently resolve lmi from public PyPI; --no-deps
holds because test_packaging.py keeps dependencies empty. The probe's every
failure is None: a diagnostic must not block the thing it diagnoses."
```

---

### Task 6: Verification (`verify.py`)

**Files:**
- Create: `lmi/commands/upgrade/verify.py`
- Create: `tests/commands/upgrade/test_verify.py`

**Interfaces:**
- Consumes: `upgrade.exit_codes.EXIT_VERIFY_FAILED`
- Produces, used by Task 7:
  - `verify.confirm(script, expected) -> str` — the installed version; `expected` may be `None`, meaning "check only that it runs". Raises `LmiError(…, EXIT_VERIFY_FAILED)`.

- [ ] **Step 1: Write the failing tests, one MANDATORY**

Create `tests/commands/upgrade/test_verify.py`:

```python
"""Confirming an upgrade by running the installed command."""

import pytest

from lmi.commands.upgrade import verify
from lmi.core.errors import LmiError


def test_the_installed_version_is_returned(fake_pip, monkeypatch):
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.2.0")
    assert verify.confirm(fake_pip.script, "0.2.0") == "0.2.0"


def test_an_old_version_after_a_successful_pip_is_exit_3(fake_pip, monkeypatch):
    """MANDATORY. This is the stale-wheel failure reached through a new door.

    pip exits 0, the command runs, and the code is the old code. Anything that
    reported success here - reading lmi.__version__ out of this process, for
    instance, which is the version imported BEFORE pip ran - would announce an
    upgrade that did not happen and leave nothing on screen to suggest
    otherwise.
    """
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.1.0")
    with pytest.raises(LmiError) as exc:
        verify.confirm(fake_pip.script, "0.2.0")
    assert exc.value.code == 3
    assert "0.2.0" in str(exc.value)
    assert "0.1.0" in str(exc.value)


def test_no_expectation_still_requires_it_to_run(fake_pip, monkeypatch):
    """When the probe could not say what to expect, verification is weaker -
    it still catches a broken install, just not a stale one."""
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.7.0")
    assert verify.confirm(fake_pip.script, None) == "0.7.0"


def test_a_command_that_fails_to_run_is_exit_3(fake_pip, monkeypatch):
    monkeypatch.setenv("FAKE_SCRIPT_RC", "9")
    with pytest.raises(LmiError) as exc:
        verify.confirm(fake_pip.script, None)
    assert exc.value.code == 3
    assert str(fake_pip.script) in str(exc.value)


def test_a_missing_command_is_exit_3(tmp_path):
    with pytest.raises(LmiError) as exc:
        verify.confirm(tmp_path / "nothing-here", None)
    assert exc.value.code == 3


def test_unreadable_output_is_exit_3(fake_pip, monkeypatch, tmp_path):
    odd = tmp_path / "odd"
    odd.write_text("#!%s\nprint('something else')\n" % __import__("sys").executable)
    odd.chmod(0o755)
    with pytest.raises(LmiError) as exc:
        verify.confirm(odd, None)
    assert exc.value.code == 3
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/commands/upgrade/test_verify.py -q`
Expected: FAIL — `ImportError: cannot import name 'verify'`

- [ ] **Step 3: Write `lmi/commands/upgrade/verify.py`**

```python
"""Confirming the upgrade by running the command that was just installed.

Never lmi.__version__. This process imported that BEFORE pip ran, so it reports
the old version no matter what is now on disk - a command that read its own
in-memory version and announced an upgrade would be the stale-wheel bug
rebuilt deliberately: success reported, old code installed, nothing on screen
to suggest otherwise. The only honest answer is a fresh process.
"""

import re
import subprocess

from .exit_codes import EXIT_VERIFY_FAILED
from ...core.errors import LmiError

# What `lmi --version` prints: argparse's version action, "lmi " + __version__.
VERSION_RE = re.compile(r"^lmi\s+(\S+)\s*$")

DID_NOT_RUN = (
    "pip reported success, but the installed command did not run:\n"
    "      %s\n"
    "      %s\n"
    "    The machine has already changed. Re-run the install script for this\n"
    "    platform to put a known-good lmi back."
)

UNREADABLE = (
    "pip reported success, but the installed command did not report a version:\n"
    "      %s\n"
    "      said: %s\n"
    "    The machine has already changed."
)

WRONG_VERSION = (
    "pip reported success, but the installed command is still the old one.\n"
    "      expected: %s\n"
    "      got:      %s\n"
    "      command:  %s\n"
    "    Something else on this machine is providing lmi, or pip installed\n"
    "    somewhere this command does not reach. Do not trust a later\n"
    "    `lmi --version` from this shell either - run it in a new one."
)


def confirm(script, expected):
    """The version `script --version` reports, checked against `expected`.

    `expected` may be None, which happens only when the index could not be
    asked what the newest version is. Verification is then weaker - it still
    catches an install that does not run, just not one that is stale.
    """
    try:
        done = subprocess.run([str(script), "--version"],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT)
    except OSError as exc:
        raise LmiError(DID_NOT_RUN % (script, exc), EXIT_VERIFY_FAILED)

    text = done.stdout.decode("utf-8", "replace").strip()
    if done.returncode != 0:
        raise LmiError(DID_NOT_RUN % (script, text or "exit %d" % done.returncode),
                       EXIT_VERIFY_FAILED)

    lines = text.splitlines()
    match = VERSION_RE.match(lines[0]) if lines else None
    if match is None:
        raise LmiError(UNREADABLE % (script, text or "nothing"),
                       EXIT_VERIFY_FAILED)

    got = match.group(1)
    if expected is not None and got != expected:
        raise LmiError(WRONG_VERSION % (expected, got, script),
                       EXIT_VERIFY_FAILED)
    return got
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/commands/upgrade/test_verify.py -q`
Expected: PASS, 6 tests.

- [ ] **Step 5: Prove the MANDATORY test bites**

Temporarily change `confirm` to `return expected or got` after the subprocess call — the shape a lazy implementation takes.

Run: `python3 -m pytest tests/commands/upgrade/test_verify.py -q`
Expected: `test_an_old_version_after_a_successful_pip_is_exit_3` FAILS.

**Report the actual output of both directions** — red with the shortcut in place, green with it removed — rather than asserting that it would. Then restore the real implementation.

- [ ] **Step 6: Run the whole suite and commit**

Run: `python3 -m pytest tests/ -q`
Expected: PASS, the previous total plus the 6 new ones, still 1 skipped.

```bash
git add lmi/commands/upgrade/verify.py tests/commands/upgrade/test_verify.py
git commit -m "feat(upgrade): confirm the upgrade by running the installed command

Never lmi.__version__ - this process imported that before pip ran. The
MANDATORY test is pip exiting 0 while the installed command still reports the
old version: exit 3, and success not reported. That is the stale-wheel failure
reached through a new door."
```

---

### Task 7: The question, the flow, and `runner.py`

**Files:**
- Create: `lmi/commands/upgrade/prompts.py`
- Modify: `lmi/commands/upgrade/runner.py` (replacing the Task 3 stub)
- Create: `tests/commands/upgrade/test_runner.py`

**Interfaces:**
- Consumes: everything above, plus `lmi.__version__`, `core.prompts`, `core.errors.EXIT_OK`
- Produces: `runner.run(args) -> int`

- [ ] **Step 1: Write the failing tests, one MANDATORY**

Create `tests/commands/upgrade/test_runner.py`:

```python
"""The `lmi upgrade` flow.

Every test drives the real runner with a fake pip and a fake installed
command. The `answers` fixture is a scripted queue behind prompts.confirm, so
no test reaches a real stdin.
"""

import json

import pytest

import lmi
from lmi.commands.upgrade import installation, prompts, runner
from lmi.core.errors import LmiError


class Args:
    def __init__(self, config=None, version=None):
        self.config = config
        self.version = version


@pytest.fixture
def answers(monkeypatch):
    """A scripted queue of yes/no answers behind prompts.confirm."""
    queue = []

    def confirm(question, default=False):
        assert queue, "the runner asked more questions than the test scripted"
        return queue.pop(0)

    monkeypatch.setattr(prompts, "confirm", confirm)
    return queue


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "lmi.json"
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"lmi": {"index": "https://i/simple/"}}, fh)
    return path


@pytest.fixture
def wired(fake_pip, monkeypatch, config_file):
    """The runner, with detection and the running version under our control."""
    monkeypatch.setattr(installation, "detect", fake_pip.installation)
    monkeypatch.setattr(runner, "RUNNING", "0.1.0")
    return fake_pip


def test_a_newer_version_is_installed_and_confirmed(wired, answers, monkeypatch,
                                                    config_file, capsys):
    monkeypatch.setenv("FAKE_PIP_LATEST", "0.2.0")
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.2.0")
    answers.append(True)

    assert runner.run(Args(config=str(config_file))) == 0
    installs = [c for c in wired.calls() if "install" in c]
    assert len(installs) == 1
    assert installs[0][-1] == "lmi==0.2.0"
    assert "0.2.0" in capsys.readouterr().out


def test_answering_no_runs_no_pip_and_changes_nothing(wired, answers, monkeypatch,
                                                      config_file, capsys):
    """MANDATORY. The same guarantee as CLAUDE.md section 3 item 16: a user who
    answers the question rather than erring leaves the machine as they found
    it, and the command exits 0 because they answered."""
    monkeypatch.setenv("FAKE_PIP_LATEST", "0.2.0")
    answers.append(False)

    assert runner.run(Args(config=str(config_file))) == 0
    assert [c for c in wired.calls() if "install" in c] == []
    assert "Nothing was changed." in capsys.readouterr().out


def test_already_at_the_newest_makes_no_pip_install(wired, answers, monkeypatch,
                                                    config_file, capsys):
    monkeypatch.setenv("FAKE_PIP_LATEST", "0.1.0")

    assert runner.run(Args(config=str(config_file))) == 0
    assert [c for c in wired.calls() if "install" in c] == []
    assert "already" in capsys.readouterr().out.lower()


def test_an_explicit_version_equal_to_the_running_one_asks_the_index_nothing(
        wired, answers, config_file):
    assert runner.run(Args(config=str(config_file), version="0.1.0")) == 0
    assert wired.count() == 0


def test_an_explicit_version_is_pinned(wired, answers, monkeypatch, config_file):
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.0.9")
    answers.append(True)

    assert runner.run(Args(config=str(config_file), version="0.0.9")) == 0
    installs = [c for c in wired.calls() if "install" in c]
    assert installs[0][-1] == "lmi==0.0.9"
    assert not [c for c in wired.calls() if "index" in c]  # no probe needed


def test_a_probe_that_cannot_answer_still_upgrades(wired, answers, monkeypatch,
                                                   config_file, capsys):
    monkeypatch.delenv("FAKE_PIP_LATEST", raising=False)
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.5.0")
    answers.append(True)

    assert runner.run(Args(config=str(config_file))) == 0
    installs = [c for c in wired.calls() if "install" in c]
    assert installs[0][-2:] == ["--upgrade", "lmi"]
    assert "0.5.0" in capsys.readouterr().out


def test_a_stale_result_is_exit_3(wired, answers, monkeypatch, config_file):
    monkeypatch.setenv("FAKE_PIP_LATEST", "0.2.0")
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.1.0")   # pip lied
    answers.append(True)

    with pytest.raises(LmiError) as exc:
        runner.run(Args(config=str(config_file)))
    assert exc.value.code == 3


def test_a_failing_pip_is_exit_1(wired, answers, monkeypatch, config_file):
    monkeypatch.setenv("FAKE_PIP_LATEST", "0.2.0")
    monkeypatch.setenv("FAKE_PIP_RC", "1")
    answers.append(True)

    with pytest.raises(LmiError) as exc:
        runner.run(Args(config=str(config_file)))
    assert exc.value.code == 1


def test_a_refused_installation_never_reaches_pip(fake_pip, monkeypatch,
                                                  config_file):
    def refuse():
        raise LmiError("nope", 2)

    monkeypatch.setattr(installation, "detect", refuse)
    with pytest.raises(LmiError) as exc:
        runner.run(Args(config=str(config_file)))
    assert exc.value.code == 2
    assert fake_pip.count() == 0


def test_an_unexpected_exception_is_exit_4(wired, answers, monkeypatch,
                                           config_file):
    def boom():
        raise ZeroDivisionError("x")

    monkeypatch.setattr(installation, "detect", boom)
    with pytest.raises(LmiError) as exc:
        runner.run(Args(config=str(config_file)))
    assert exc.value.code == 4
    assert "ZeroDivisionError" in str(exc.value)


def test_the_running_version_is_read_from_the_package():
    """RUNNING is lmi.__version__ at import, which is the FROM side of the
    upgrade and the one thing this process can honestly report."""
    assert runner.RUNNING == lmi.__version__
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/commands/upgrade/test_runner.py -q`
Expected: FAIL — `ImportError: cannot import name 'prompts'`

- [ ] **Step 3: Write `lmi/commands/upgrade/prompts.py`**

```python
"""The one question `lmi upgrade` asks.

The mechanics and the no-terminal guard are lmi/core/prompts.py's. What is
here is this command's own NO_TERMINAL text - which must describe the question
this command asks and no other - and the single entry point that
tests/commands/upgrade/test_runner.py patches to drive the flow.
"""

from ...core import prompts as _prompts

NO_TERMINAL = (
    "lmi upgrade is interactive and needs a terminal.\n"
    "    It asks before replacing the installed lmi, because that replaces the\n"
    "    command you are running.\n"
    "    Run it directly in a terminal, not from a script, a pipe or a build step."
)


def confirm(question, default=False):
    return _prompts.confirm(question, default, NO_TERMINAL)
```

- [ ] **Step 4: Write `lmi/commands/upgrade/runner.py`**

```python
"""The `lmi upgrade` flow.

Order matters. Every question is asked BEFORE anything is modified: a user who
abandons the command at the prompt, or answers no, leaves the machine exactly
as they found it.

One rule about this module in particular. Every import here is module-level,
and after pip.install returns, nothing may import anything or touch the lmi
package: modules already imported stay in memory, but a module imported AFTER
pip would come from the new version, mixed with old ones already loaded. The
only things that may run after that line are a subprocess (verify.confirm),
stdlib calls whose modules were imported long before pip ran, and printing.
_warn_if_shadowed is that stdlib-only exception: shutil.which and Path.resolve
touch no lmi code, and both were imported at the top of this module, long
before pip ran. Do not add a lazy import, and do not move work below that
line.
"""

import shutil
from pathlib import Path

from . import installation, pip, prompts, verify
from .config import build_config
from .exit_codes import EXIT_INTERNAL
from ... import __version__
from ...core.errors import EXIT_OK, LmiError

# The version this process is running, read at import - the FROM side of the
# upgrade, and the one version this process can honestly report. It is NEVER
# the answer to "did the upgrade work": see verify.py.
RUNNING = __version__

SHADOWED = (
    "[WARN] the lmi that runs in this shell is not the one just upgraded:\n"
    "         on PATH:  %s\n"
    "         upgraded: %s\n"
    "       Remove the first, or reorder PATH, or the upgrade is invisible."
)


def run(args):
    try:
        return _run(args)
    except LmiError:
        # A usage, pip or verification error, already carrying its exit code
        # and a message cli.main will print. Not ours to reinterpret.
        raise
    except Exception as exc:                    # noqa: BLE001 - deliberate
        raise LmiError(
            "unexpected failure in lmi upgrade: %s: %s"
            % (type(exc).__name__, exc),
            EXIT_INTERNAL,
        )


def _run(args):
    cfg = build_config(args)
    say("Config:  %s" % cfg.source)

    inst = installation.detect()
    say("Running: lmi %s, installed in %s (%s)" % (RUNNING, inst.where, inst.kind))
    say("Index:   %s" % cfg.index)

    target = _target(args, inst, cfg)
    if target is _NOTHING_TO_DO:
        return EXIT_OK

    # --- ask everything, change nothing ---------------------------------
    if not prompts.confirm(_question(target), default=False):
        say("Nothing was changed.")
        return EXIT_OK

    # --- from here the machine changes ----------------------------------
    pip.install(inst, cfg, target, say)
    got = verify.confirm(inst.script, target)

    say("")
    say("Upgraded lmi %s -> %s" % (RUNNING, got))
    say("  %s" % inst.script)
    _warn_if_shadowed(inst.script)
    return EXIT_OK


# A sentinel rather than None, because None is a real target: "whatever the
# index says is newest".
_NOTHING_TO_DO = object()


def _target(args, inst, cfg):
    """The version to install, None for "the newest", or _NOTHING_TO_DO."""
    wanted = getattr(args, "version", None)
    if wanted is not None:
        if wanted == RUNNING:
            say("Already at %s - nothing to do." % wanted)
            return _NOTHING_TO_DO
        return wanted

    newest = pip.latest(inst, cfg)
    if newest is None:
        # Best-effort, and its failure degrades the question rather than the
        # command: pip will resolve the newest itself.
        say("The index could not say which version is newest; pip will choose.")
        return None
    if newest == RUNNING:
        say("Already at %s, which is the newest on the index." % newest)
        return _NOTHING_TO_DO
    return newest


def _question(target):
    if target is None:
        return ("Replace lmi %s with the newest version on the index?"
                % RUNNING)
    return "Replace lmi %s with %s?" % (RUNNING, target)


def _warn_if_shadowed(script):
    found = shutil.which("lmi")
    if not found:
        return
    try:
        same = Path(found).resolve() == Path(script).resolve()
    except OSError:
        same = False
    if not same:
        say(SHADOWED % (found, script))


def say(message=""):
    """Console output.

    Deliberately not core.log.Logger: this command writes no log file, and a
    Logger needs a path. `print` is the whole requirement - the same choice
    lmi install made, for the same reason.
    """
    print(message)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/commands/upgrade/test_runner.py -q`
Expected: PASS, 11 tests.

- [ ] **Step 6: Prove the MANDATORY test bites**

Temporarily move the `prompts.confirm` check below `pip.install`.

Run: `python3 -m pytest tests/commands/upgrade/test_runner.py -q`
Expected: `test_answering_no_runs_no_pip_and_changes_nothing` FAILS.

**Report the actual output of both directions.** Then restore.

- [ ] **Step 7: Check the command end to end by hand**

Run: `python3 -m lmi upgrade --help`
Expected: the help text shows `--version VERSION` and `--config PATH`, and `python3 -m lmi --help` lists `upgrade` alongside `install` and `schedule`.

Run: `python3 -m lmi upgrade --config /does/not/exist.json`
Expected: `[ERROR] the config file given with --config does not exist: …`, exit 2. Confirm with `echo $?`.

- [ ] **Step 8: Run the whole suite and commit**

Run: `python3 -m pytest tests/ -q`
Expected: PASS, the previous total plus the 11 new ones, still 1 skipped. **This is the number to carry into Task 8 and into `CLAUDE.md` §4 rule 1** — record it.

```bash
git add lmi/commands/upgrade/prompts.py lmi/commands/upgrade/runner.py \
        tests/commands/upgrade/test_runner.py
git commit -m "feat(upgrade): the flow - ask, install, confirm

Every question is asked before anything changes, and answering no runs no pip
at all. After pip runs, this process's own files have been replaced, so every
import is module-level and nothing below that line does more than run one
subprocess and print."
```

---

### Task 8: Documentation

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: everything. Produces: nothing executable.

- [ ] **Step 1: Add the `lmi upgrade` section to `README.md`**

Place it after the `lmi install claude` section and before `## Project layout`. It must cover, in the README's existing voice:

- What it does: installs a newer `lmi` from the index named in the config file, over the installation it is running from. Why it exists: the install scripts need a clone, and the guides say the clone is disposable.
- The `lmi` config section, in the same table style the `claude` section uses:

  | Key | Required | Meaning |
  |---|---|---|
  | `index` | **yes** | The Python package index to install from — pip's `--index-url`. Replaces the default index rather than adding to it, so an air-gapped machine cannot silently resolve `lmi` from public PyPI. |
  | `cafile` | no | A CA certificate file — pip's `--cert`. Checked for existence when the config is read, not when pip runs. |

- What it asks, and that there is no `--yes`, and that no terminal is exit 2 rather than a wait.
- `--version` for pinning, including going back to a known-good version.
- What it upgrades and what it refuses: a venv install and a `pip install --user` install; an editable checkout, a pipx install and anything else are refused with exit 2 and why.
- Its exit-code table: 0 upgraded / already current / answered no; 1 pip failed; 3 pip succeeded and the installed command reports the wrong version; 4 a bug in lmi; 2 config, unsupported installation, no terminal.

- [ ] **Step 2: Add the `~/.lmi/config.json` caveat**

In the Installing section, where the README says the clone is disposable, add that `lmi upgrade` reads the same config file, and `./config/lmi.json` goes away with the clone — so a machine that will be upgraded in place wants the config at `~/.lmi/config.json`:

```bash
mkdir -p ~/.lmi && cp config/lmi.json ~/.lmi/config.json
```

- [ ] **Step 3: Add the two README entries this design cannot settle**

Under **Still to verify**:

> **Whether pip can displace a running `lmi.exe` on Windows.** `lmi upgrade`
> replaces the package in place, and on Windows the console script being
> replaced is the one executing the command. pip stashes files by renaming
> rather than overwriting, and Windows permits renaming a running image on the
> same volume, so this is expected to work — but only a real Windows run
> settles it. If it fails, the exit-1 message already carries the
> `python -m pip …` line to run from a shell where no `lmi` is live.

Under **Known limitations**:

> **Do not upgrade while `lmi schedule` is looping.** The upgrade replaces
> files underneath that process. Modules it has already imported stay in
> memory, but one it has not yet imported would come from the new version. The
> locks are per state file in arbitrary directories, so there is nothing for
> `lmi upgrade` to enumerate and no honest way for it to detect this. Upgrade
> between runs.

- [ ] **Step 4: Update `CLAUDE.md`**

In §2, add `lmi/commands/upgrade/` to the architecture listing with one line per module, add `core/config.py` and `core/prompts.py` to the `core/` listing, and add a sentence to the "`core/` is for code with no command flavour" rule recording that those two were promoted when `lmi upgrade` became the second command to need them — which is the rule working, not an exception to it.

In §3, add these items after item 21:

> 22. **`lmi upgrade` never reports its own `__version__` as proof.** That
>     value was imported before pip ran, so it is the *old* version whatever is
>     now on disk. Success is confirmed by running the installed console script
>     in a subprocess and comparing. **Silent:** the command announces
>     "upgraded 0.1.0 → 0.2.0" while 0.1.0 is still installed, which is the
>     stale-wheel failure with a new front end.
> 23. **An installation shape that cannot be upgraded is refused, not guessed
>     at.** An editable checkout, a pipx install, a system-wide install:
>     `installation.detect` raises exit 2 for each, before pip is invoked.
>     **Silent** in three different ways — a released wheel over a developer's
>     working tree; pipx's record describing a version that is gone; a `--user`
>     copy that the `PATH` entry never reaches. The order of the checks is
>     load-bearing: editable is tested first because a dev checkout is usually
>     also inside a venv.
> 24. **The version probe's failure must never fail the command.** `pip index
>     versions` is experimental and absent from older pips. Every failure is
>     `None`, which degrades the question the user is asked and nothing else. A
>     diagnostic that blocks the thing it diagnoses is worse than no
>     diagnostic.

In §5, add `fake_pip` to the fixtures table: *"A fake interpreter that records every `-m pip` argv and answers `index versions`, plus a fake installed `lmi` command. pip is never found through `PATH` — it is `<interpreter> -m pip` — so the seam is the interpreter. `FAKE_PIP_RC`, `FAKE_PIP_LATEST`, `FAKE_SCRIPT_VERSION`, `FAKE_SCRIPT_RC`."*

In §4 rule 1, update the test count to the number Task 7 actually reported.

- [ ] **Step 5: Verify the documentation tests still pass**

Run: `python3 -m pytest tests/test_docs.py -q`
Expected: PASS. `test_the_readme_names_the_silent_keys` reads `README.md` for exact strings; if it fails, the README section is missing something it names.

- [ ] **Step 6: Run the whole suite and commit**

Run: `python3 -m pytest tests/ -q`
Expected: PASS, exactly the Task 7 total — documentation only, so the count must not move.

```bash
git add README.md CLAUDE.md
git commit -m "docs: lmi upgrade, and the three silent failures it introduces

The README gains the command, its config section, its exit codes and the
~/.lmi/config.json caveat on a disposable clone; the Windows running-.exe
question goes on Still to verify rather than being claimed; upgrading during a
schedule loop goes on Known limitations. CLAUDE.md section 3 gains the
self-reported version, the guessed installation shape and the probe that must
never fail the command."
```

---

## Self-Review

**Spec coverage.** Every section of `2026-08-09-lmi-upgrade-design.md` maps to a task: §1 goals → all; §2 command surface → Task 3; §3 detection → Task 4; §4 in-place pip → Task 5; §5 config → Task 3 and Task 5 (`_index_argv`); §6 the `core/` promotions → Tasks 1 and 2; §7 the flow → Task 7; §8 verification → Task 6; §9 exit codes → Tasks 3, 5, 6, 7; §10 testing → each task's tests, with the four MANDATORY cases in Tasks 4 (×2), 6 and 7; §11 documentation → Task 8; §12 decisions → all.

**Two spec details deliberately implemented differently**, both recorded in File Structure above: `install/prompts.py` survives as a wrapper rather than being deleted, and the install config tests stay where they are rather than moving. Both preserve a test seam the spec did not know about. Neither changes behaviour.

**One accepted rough edge, worth knowing before it looks like a bug.** Version comparison is exact string equality everywhere — there is no version parser in the standard library and `packaging` is not a dependency we may add. So `lmi upgrade --version 0.1` against an index carrying `0.1.0` pins `lmi==0.1`, pip installs `0.1.0`, and verification reports a mismatch and exits 3 on an upgrade that in fact worked. It is loud rather than silent, it needs the user to type a non-canonical version, and the alternative is either a dependency or a hand-rolled PEP 440 comparator. Left as is.
