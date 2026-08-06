# `lmi install claude` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an interactive `lmi install claude` command that installs the Claude Code CLI from an internal Artifactory npm registry on an air-gapped machine and writes the site's standard configuration.

**Architecture:** A new self-contained command package `lmi/commands/install/`, registered by one line in `lmi/commands/__init__.py`. `cli.py` is not touched. Leaf modules (config, prompts, npm, jsonfile, settings, claude_json, gitbash) are built and tested first; `runner.py` orchestrates them last. Mechanism is split from content: `jsonfile.py` knows how to read/back up/atomically write a JSON document, while `settings.py` and `claude_json.py` know only what goes inside one.

**Tech Stack:** Python 3.9, standard library only. `pytest` for tests (dev extra). No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-08-05-lmi-install-claude-design.md`. Where this plan and the spec disagree, the spec wins — raise it rather than guessing.

## Global Constraints

Every task's requirements implicitly include all of these.

- **Python 3.9 floor.** No `match`. No PEP 604 unions (`str | None`) in *evaluated* annotations — use `typing.Optional`/`Dict`/`List`. Function annotations are evaluated at `def` time, so this is an import-time `TypeError`, not a runtime one.
- **`Path.write_text(..., newline=...)` requires 3.10.** Always use `open(path, "w", encoding="utf-8", newline="\n")`. This killed every run at iteration 1 on the 3.9.6 macOS ships, and a syntax check cannot catch it.
- **Standard library only at runtime.** `lmi/` must never import `pytest`. `pyproject.toml` keeps `dependencies = []`; `tests/test_packaging.py` enforces it.
- **Never `subprocess.run(..., shell=True)`.** A registry URL from a config file must never reach a shell. Always a list argv.
- **Never use `pathlib`'s `is_dir()`/`is_file()`** on a user-supplied path. They raise `ENAMETOOLONG`, `EACCES` and more instead of returning `False`. Use `lmi.core.fs.classify` / `fs.kind`, which return a verdict, and turn `fs.UNKNOWN` into exit 2.
- **Never call `Path.expanduser()` unguarded.** It raises `RuntimeError` for a `~someuser` whose home cannot be resolved. Wrap it.
- **Commands never import each other.** `lmi/commands/install/` must not import from `lmi/commands/schedule/`. Duplicating a constant is correct; promoting to `core/` in advance is not.
- **Exit codes:** `0` and `2` are global, from `lmi.core.errors`, and must not be redefined. This command owns `1`, `3`, `4`.
- **Run `python3 -m pytest tests/ -q` after every task** and state that you did. Baseline is 135 passing.
- **No test may reach a real `npm`, `claude`, `git`, `setx`, or the user's real `~/.claude/`.** Fixtures replace `PATH` entirely (not prepend) and `HOME` is redirected to `tmp_path`.
- **Exact strings that fail silently if wrong** — copy verbatim, never retype:
  - `hasCompletedOnboarding` (lowercase `b`)
  - `extraKnownMarketplaces`
  - `CLAUDE_CODE_GIT_BASH_PATH`
  - `CLAUDE_CODE_MAX_CONTEXT_TOKENS` = `"256000"`
  - `CLAUDE_CODE_AUTO_COMPACT_WINDOW` = `"204800"`
  - `CLAUDE_CODE_MAX_OUTPUT_TOKENS` = `"64000"`
  - `ANTHROPIC_AUTH_TOKEN`
  - `@anthropic-ai/claude-code`
  - All `env` values are **JSON strings**, never numbers.

## File Structure

| File | Responsibility |
|---|---|
| `lmi/commands/install/__init__.py` | The four-name command contract: `NAME`, `HELP`, `add_arguments`, `run` |
| `lmi/commands/install/exit_codes.py` | This command's codes: 1, 3, 4 |
| `lmi/commands/install/config.py` | CLI arguments, config-file discovery, JSON validation, the frozen `Config` |
| `lmi/commands/install/prompts.py` | Every question asked, and the no-terminal guard |
| `lmi/commands/install/npm.py` | Locating npm, running one npm command, the `--global` fallback |
| `lmi/commands/install/jsonfile.py` | Read / back up / atomically write one JSON document |
| `lmi/commands/install/settings.py` | What goes into `~/.claude/settings.json` |
| `lmi/commands/install/claude_json.py` | What goes into `~/.claude.json` |
| `lmi/commands/install/gitbash.py` | Windows Git Bash discovery and the persisted env var |
| `lmi/commands/install/runner.py` | `run(args)` — orchestration and reporting |
| `lmi/commands/__init__.py` | Registration (modify) |
| `tests/commands/install/` | One test module per source module, plus `conftest.py` |
| `examples/lmi.json` | A complete config to copy and edit |
| `README.md`, `CLAUDE.md` | Documentation (modify) |

**Deviation from the spec, deliberate:** the spec's §3 file list puts `run` in `__init__.py`. This plan adds `runner.py` and keeps `__init__.py` as a four-line re-export, matching `lmi/commands/schedule/__init__.py` exactly. Orchestration and the command contract are two jobs.

---

### Task 1: Package skeleton, exit codes, and configuration

**Files:**
- Create: `lmi/commands/install/__init__.py`
- Create: `lmi/commands/install/exit_codes.py`
- Create: `lmi/commands/install/config.py`
- Create: `tests/commands/install/__init__.py`
- Create: `tests/commands/install/test_config.py`

**Interfaces:**
- Consumes: `lmi.core.errors.{LmiError, EXIT_USAGE}`, `lmi.core.fs.{classify, kind, FILE, DIR, UNKNOWN}`, `lmi.core.text.decode_with_bom`
- Produces:
  - `exit_codes.EXIT_NPM_FAILED = 1`, `EXIT_CONFIG_WRITE = 3`, `EXIT_INTERNAL = 4`
  - `config.PACKAGE: str` — `"@anthropic-ai/claude-code"`
  - `config.DEFAULT_ENV: Dict[str, str]` — the three 256K keys
  - `config.add_arguments(parser) -> None`
  - `config.Config` — frozen dataclass with fields `registry: str`, `cafile: Optional[Path]`, `marketplaces: Dict`, `env: Dict[str, str]`, `source: Path`
  - `config.build_config(args) -> Config`

- [ ] **Step 1: Create the package `__init__.py` as a stub**

`lmi/commands/install/__init__.py` — the real contract lands in Task 7. For now it must be importable and must **not** be registered:

```python
"""`lmi install` - install and configure a coding agent CLI.

The four-name command contract (NAME, HELP, add_arguments, run) is completed
in runner.py; this module is not registered in lmi/commands/__init__.py until
run() exists, so that test_every_command_satisfies_the_contract cannot see a
half-built command.
"""
```

Also create empty `tests/commands/install/__init__.py`.

- [ ] **Step 2: Write the failing tests**

`tests/commands/install/test_config.py`:

```python
"""Discovery and validation of the lmi install config file."""

import json

import pytest

from lmi.commands.install import config
from lmi.core.errors import LmiError


class Args:
    """argparse.Namespace stand-in: only the two attributes build_config reads."""

    def __init__(self, config=None, target="claude"):
        self.config = config
        self.target = target


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    return path


MINIMAL = {"claude": {"registry": "https://artifactory.corp.local/api/npm/npm/"}}


def test_explicit_config_wins(tmp_path, monkeypatch):
    chosen = write(tmp_path / "chosen.json", MINIMAL)
    write(tmp_path / "lmi.json", {"claude": {"registry": "https://wrong/"}})
    monkeypatch.chdir(tmp_path)
    cfg = config.build_config(Args(config=str(chosen)))
    assert cfg.registry == "https://artifactory.corp.local/api/npm/npm/"
    assert cfg.source == chosen


def test_missing_explicit_config_does_not_fall_through(tmp_path, monkeypatch):
    """MANDATORY. Silent failure: provisioning against the wrong registry.

    A --config the user named and that does not exist must be an error, never
    a quiet fall-through to ./lmi.json - which would install from a different
    registry than the one asked for and report success.
    """
    write(tmp_path / "lmi.json", MINIMAL)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(tmp_path / "nope.json")))
    assert exc.value.code == 2


def test_env_var_beats_cwd(tmp_path, monkeypatch):
    from_env = write(tmp_path / "env.json", MINIMAL)
    write(tmp_path / "lmi.json", {"claude": {"registry": "https://wrong/"}})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LMI_CONFIG", str(from_env))
    assert config.build_config(Args()).source == from_env


def test_cwd_beats_home(tmp_path, monkeypatch):
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    write(tmp_path / "home" / ".lmi" / "config.json",
          {"claude": {"registry": "https://wrong/"}})
    here = write(tmp_path / "work" / "lmi.json", MINIMAL)
    monkeypatch.chdir(tmp_path / "work")
    assert config.build_config(Args()).source == here


def test_home_is_the_last_resort(tmp_path, monkeypatch):
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    fallback = write(tmp_path / "home" / ".lmi" / "config.json", MINIMAL)
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    assert config.build_config(Args()).source == fallback


def test_no_config_anywhere_is_usage_with_an_example(tmp_path, monkeypatch):
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    with pytest.raises(LmiError) as exc:
        config.build_config(Args())
    assert exc.value.code == 2
    message = str(exc.value)
    assert "registry" in message          # the paste-ready example
    assert "lmi.json" in message          # the paths searched


@pytest.mark.parametrize("doc", [
    [1, 2, 3],                                        # top level not an object
    {},                                               # no "claude"
    {"claude": "nope"},                               # "claude" not an object
    {"claude": {}},                                   # no registry
    {"claude": {"registry": ""}},                     # empty registry
    {"claude": {"registry": 5}},                      # registry not a string
    {"claude": {"registry": "u", "marketplaces": []}},
    {"claude": {"registry": "u", "env": []}},
])
def test_rejected_shapes_are_usage_errors(tmp_path, monkeypatch, doc):
    path = write(tmp_path / "lmi.json", doc)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2


def test_invalid_json_names_the_file_and_the_position(tmp_path, monkeypatch):
    path = tmp_path / "lmi.json"
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        fh.write('{"claude": }')
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert "lmi.json" in str(exc.value)


def test_a_utf8_bom_is_tolerated(tmp_path):
    """Notepad and PowerShell's Set-Content both write one; json.loads rejects it."""
    path = tmp_path / "lmi.json"
    with open(str(path), "wb") as fh:
        fh.write(b"\xef\xbb\xbf" + json.dumps(MINIMAL).encode("utf-8"))
    assert config.build_config(Args(config=str(path))).registry.startswith("https://")


def test_non_string_env_value_is_rejected(tmp_path):
    """MANDATORY. Silent failure: the 256K profile does not apply.

    Claude Code types settings.json `env` as a map of string to string. A JSON
    number writes cleanly, parses cleanly, and the setting does nothing.
    """
    path = write(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/",
        "env": {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": 256000},
    }})
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert "string" in str(exc.value)


def test_the_256k_profile_is_the_default():
    assert config.DEFAULT_ENV == {
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000",
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "204800",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000",
    }


def test_config_env_overrides_one_key_and_keeps_the_others(tmp_path):
    path = write(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/",
        "env": {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "32000",
                "ANTHROPIC_BASE_URL": "https://gw.corp/"},
    }})
    env = config.build_config(Args(config=str(path))).env
    assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "32000"
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "256000"
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "204800"
    assert env["ANTHROPIC_BASE_URL"] == "https://gw.corp/"


def test_default_env_is_not_mutated_by_a_config(tmp_path):
    """A shared module-level dict updated in place would leak between runs."""
    path = write(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/", "env": {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "1"}}})
    config.build_config(Args(config=str(path)))
    assert config.DEFAULT_ENV["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "64000"


def test_cafile_must_exist(tmp_path):
    path = write(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/", "cafile": str(tmp_path / "absent.pem")}})
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2


def test_cafile_that_exists_is_resolved(tmp_path):
    pem = tmp_path / "ca.pem"
    pem.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    path = write(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/", "cafile": str(pem)}})
    assert config.build_config(Args(config=str(path))).cafile == pem


def test_tilde_user_that_cannot_resolve_is_usage_not_a_traceback():
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config="~nosuchuser-lmi/lmi.json"))
    assert exc.value.code == 2


def test_marketplaces_pass_through_unaltered(tmp_path):
    markets = {"corp": {"source": {"source": "git", "url": "https://g/c.git"},
                        "whateverUpstreamAddsNext": True}}
    path = write(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/", "marketplaces": markets}})
    assert config.build_config(Args(config=str(path))).marketplaces == markets
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m pytest tests/commands/install/test_config.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'lmi.commands.install.config'`.

- [ ] **Step 4: Write `exit_codes.py`**

```python
"""Exit codes specific to `lmi install`.

0 and 2 are global and live in lmi.core.errors. Everything else is this
command's own.

4 deliberately keeps the meaning it has in `lmi schedule`. The architecture
lets each command own its codes, but a provisioning script should not have to
learn a per-command definition of "a bug in lmi", so this one matches instead
of exercising that freedom.

3 is separate from 1 on purpose: by the time a Claude config file is written,
npm has already succeeded, so the outcome is a working `claude` with unwritten
settings. Folding it into 1 would report that the install failed.
"""

EXIT_NPM_FAILED = 1
EXIT_CONFIG_WRITE = 3
EXIT_INTERNAL = 4
```

- [ ] **Step 5: Write `config.py`**

```python
"""Arguments, config-file discovery and validation for `lmi install`.

Validation lives with the command, not in cli.py, so cli.py stays pure
parse-and-dispatch as commands accumulate.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from ...core import fs
from ...core.errors import EXIT_USAGE, LmiError
from ...core.text import decode_with_bom

# What this command installs. Deliberately not a config key: a command whose
# target is configurable is a different command.
PACKAGE = "@anthropic-ai/claude-code"

CONFIG_ENV_VAR = "LMI_CONFIG"
CWD_CONFIG_NAME = "lmi.json"
HOME_CONFIG = "~/.lmi/config.json"

# The 256K context profile, shipped as a default so a machine whose config
# omits `env` still gets it. Values are STRINGS: Claude Code types settings.json
# `env` as a map of string to string, and a JSON number there writes cleanly,
# parses cleanly and does nothing.
DEFAULT_ENV = {
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "204800",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000",
}

EXAMPLE = """{
  "claude": {
    "registry": "https://artifactory.example.com/api/npm/npm-virtual/",
    "cafile": "/etc/ssl/certs/corp-ca.pem",
    "marketplaces": {
      "corp-tools": {
        "source": {"source": "git", "url": "https://git.example.com/m.git"}
      }
    }
  }
}"""


def add_arguments(parser):
    parser.add_argument(
        "target", choices=["claude"], metavar="TARGET",
        help="what to install. Only 'claude' is supported",
    )
    parser.add_argument(
        "--config", dest="config", metavar="PATH",
        help="config file. Default: $%s, ./%s, %s"
             % (CONFIG_ENV_VAR, CWD_CONFIG_NAME, HOME_CONFIG),
    )


@dataclass(frozen=True)
class Config:
    registry: str
    cafile: Optional[Path]
    marketplaces: Dict
    env: Dict
    source: Path


def build_config(args):
    """Find, read and validate the config file. Never returns a partial Config."""
    path = _find(getattr(args, "config", None))
    section = _section(_load(path), path)
    return Config(
        registry=_registry(section, path),
        cafile=_cafile(section, path),
        marketplaces=_object(section, "marketplaces", path),
        env=_env(section, path),
        source=path,
    )


# --- discovery ------------------------------------------------------------

def _find(explicit):
    if explicit is not None:
        path = _expand(explicit)
        # An explicit --config that does not exist must NOT fall through to the
        # next candidate. A named file that quietly resolves to a different one
        # is how a machine gets provisioned against the wrong registry.
        if _kind(path) != fs.FILE:
            raise LmiError(
                "the config file given with --config does not exist: %s" % path,
                EXIT_USAGE,
            )
        return path

    candidates = []
    from_env = os.environ.get(CONFIG_ENV_VAR)
    if from_env:
        candidates.append(_expand(from_env))
    candidates.append(Path.cwd() / CWD_CONFIG_NAME)
    candidates.append(_expand(HOME_CONFIG))

    for candidate in candidates:
        if _kind(candidate) == fs.FILE:
            return candidate
    raise LmiError(_nothing_found(candidates), EXIT_USAGE)


def _nothing_found(candidates):
    return (
        "no config file found. `lmi install` needs one to know which registry "
        "to install from.\n"
        "    Looked in, in order:\n%s\n"
        "    Create one, or pass --config PATH. A minimal file:\n\n%s"
        % ("\n".join("      " + str(c) for c in candidates),
           "\n".join("      " + line for line in EXAMPLE.splitlines()))
    )


def _expand(raw):
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


def _kind(path):
    """fs.classify, but an unanswerable path is a usage error.

    Path.is_file() raises ENAMETOOLONG rather than returning False, so an
    over-long --config used to crash with a traceback and exit 1.
    """
    kind, reason = fs.classify(path)
    if kind == fs.UNKNOWN:
        raise LmiError(
            "the config file path cannot be used: %s (%s)" % (path, reason),
            EXIT_USAGE,
        )
    return kind


# --- reading and validation ----------------------------------------------

def _load(path):
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


def _section(doc, path):
    if not isinstance(doc, dict):
        raise LmiError(
            "the config file must contain a JSON object: %s" % path, EXIT_USAGE
        )
    section = doc.get("claude")
    if section is None:
        raise LmiError(
            'the config file has no "claude" section: %s\n'
            "    Expected:\n\n%s"
            % (path, "\n".join("      " + l for l in EXAMPLE.splitlines())),
            EXIT_USAGE,
        )
    if not isinstance(section, dict):
        raise LmiError(
            'the "claude" section must be a JSON object: %s' % path, EXIT_USAGE
        )
    return section


def _registry(section, path):
    value = section.get("registry")
    if not isinstance(value, str) or not value.strip():
        raise LmiError(
            '"claude.registry" must be a non-empty string - the npm registry '
            "URL to install from: %s" % path,
            EXIT_USAGE,
        )
    return value.strip()


def _cafile(section, path):
    value = section.get("cafile")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LmiError('"claude.cafile" must be a string: %s' % path, EXIT_USAGE)
    resolved = _expand(value)
    # Checked here rather than at npm time: `npm config set cafile /typo`
    # succeeds, and the mistake surfaces much later as an unrelated TLS error.
    if _kind(resolved) != fs.FILE:
        raise LmiError(
            '"claude.cafile" does not exist: %s (from %s)' % (resolved, path),
            EXIT_USAGE,
        )
    return resolved


def _object(section, key, path):
    value = section.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise LmiError(
            '"claude.%s" must be a JSON object: %s' % (key, path), EXIT_USAGE
        )
    return value


def _env(section, path):
    """The 256K defaults, overridden and extended by the config file."""
    merged = dict(DEFAULT_ENV)          # a copy: DEFAULT_ENV is module state
    for key, value in _object(section, "env", path).items():
        if not isinstance(value, str):
            raise LmiError(
                '"claude.env.%s" must be a string, not %s: %s\n'
                "    Claude Code types settings.json env as string-to-string; a "
                "number is silently ignored."
                % (key, type(value).__name__, path),
                EXIT_USAGE,
            )
        merged[key] = value
    return merged
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/commands/install/test_config.py -q`
Expected: PASS, 20 tests.

Then the whole suite: `python3 -m pytest tests/ -q` — expected 155 passed.

- [ ] **Step 7: Commit**

```bash
git add lmi/commands/install/ tests/commands/install/
git commit -m "feat(install): config file discovery and validation

Three site-specific keys, one required. The 256K profile ships as an
overridable default, with string values - Claude Code types settings.json
env as string-to-string and silently ignores a number."
```

---

### Task 2: Interactive prompts

**Files:**
- Create: `lmi/commands/install/prompts.py`
- Create: `tests/commands/install/test_prompts.py`

**Interfaces:**
- Consumes: `lmi.core.errors.{LmiError, EXIT_USAGE}`
- Produces:
  - `prompts.confirm(question: str, default: bool = False) -> bool`
  - `prompts.secret(question: str) -> str`
  - `prompts.text(question: str, default: Optional[str] = None) -> str`
  - `prompts.NO_TERMINAL: str`

- [ ] **Step 1: Write the failing test**

`tests/commands/install/test_prompts.py`:

```python
"""Every question the command asks, and the guard against hanging."""

import builtins

import pytest

from lmi.commands.install import prompts
from lmi.core.errors import LmiError


def feed(monkeypatch, *answers):
    """Queue answers for input(); raise if more are asked for than queued."""
    queue = list(answers)
    asked = []

    def fake_input(prompt=""):
        asked.append(prompt)
        if not queue:
            raise AssertionError("asked more questions than were answered")
        return queue.pop(0)

    monkeypatch.setattr(builtins, "input", fake_input)
    return asked


@pytest.mark.parametrize("answer,expected", [
    ("y", True), ("Y", True), ("yes", True), ("YES", True), (" y ", True),
    ("n", False), ("no", False), ("", False), ("maybe", False), ("yy", False),
])
def test_confirm_defaults_to_no(monkeypatch, answer, expected):
    feed(monkeypatch, answer)
    assert prompts.confirm("Repair?") is expected


def test_confirm_blank_takes_the_stated_default(monkeypatch):
    feed(monkeypatch, "")
    assert prompts.confirm("Repair?", default=True) is True


def test_confirm_shows_which_default_applies(monkeypatch):
    asked = feed(monkeypatch, "")
    prompts.confirm("Repair?")
    assert "[y/N]" in asked[0]
    asked = feed(monkeypatch, "")
    prompts.confirm("Repair?", default=True)
    assert "[Y/n]" in asked[0]


def test_text_returns_the_answer_stripped(monkeypatch):
    feed(monkeypatch, "  C:\\Git\\bin\\bash.exe  ")
    assert prompts.text("Path") == "C:\\Git\\bin\\bash.exe"


def test_text_blank_takes_the_default(monkeypatch):
    feed(monkeypatch, "")
    assert prompts.text("Path", default="/usr/bin/bash") == "/usr/bin/bash"


def test_text_blank_with_no_default_is_empty(monkeypatch):
    feed(monkeypatch, "")
    assert prompts.text("Path") == ""


def test_secret_uses_getpass_not_input(monkeypatch):
    """MANDATORY. A token echoed to the terminal lands in scrollback.

    If secret() ever falls back to input(), the credential is displayed, and on
    a shared or recorded session that is a disclosure. The fixture makes input()
    raise so the fallback cannot pass unnoticed.
    """
    def explode(prompt=""):
        raise AssertionError("secret() must not use input()")

    monkeypatch.setattr(builtins, "input", explode)
    monkeypatch.setattr(prompts.getpass, "getpass", lambda prompt="": " tok ")
    assert prompts.secret("Token") == "tok"


@pytest.mark.parametrize("ask", [
    lambda: prompts.confirm("q"),
    lambda: prompts.text("q"),
])
def test_eof_is_a_usage_error_not_a_hang(monkeypatch, ask):
    """MANDATORY. Without this the command blocks forever in a script.

    There is no --yes flag by design, so a run with no terminal cannot answer.
    It must fail fast and say why, not wait on a stdin that will never deliver.
    """
    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr(builtins, "input", eof)
    with pytest.raises(LmiError) as exc:
        ask()
    assert exc.value.code == 2
    assert "terminal" in str(exc.value)


def test_eof_from_getpass_is_also_a_usage_error(monkeypatch):
    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr(prompts.getpass, "getpass", eof)
    with pytest.raises(LmiError) as exc:
        prompts.secret("Token")
    assert exc.value.code == 2


def test_ctrl_c_is_a_clean_message_not_a_traceback(monkeypatch):
    def interrupt(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr(builtins, "input", interrupt)
    with pytest.raises(LmiError) as exc:
        prompts.confirm("q")
    assert exc.value.code == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/commands/install/test_prompts.py -q`
Expected: `ModuleNotFoundError: No module named 'lmi.commands.install.prompts'`.

- [ ] **Step 3: Write `prompts.py`**

```python
"""Every question `lmi install` asks.

One module, so the no-terminal guard exists once and the tests have a single
seam to drive the whole interactive flow.

`lmi install` is interactive by design and has no --yes flag, which means it
cannot be driven from a script. What it must not do is *hang*: with no
terminal, input() and getpass() raise EOFError, and an unguarded call would
block a provisioning run forever with nothing to answer it. That is the
difference between "not scriptable" and "wedged", and only the second is a bug.

Note this command is the reason invariant 3 in CLAUDE.md names `lmi schedule`
rather than lmi as a whole.
"""

import getpass

from ...core.errors import EXIT_USAGE, LmiError

NO_TERMINAL = (
    "lmi install is interactive and needs a terminal.\n"
    "    It asks before repairing an existing install, for the Claude Code auth\n"
    "    token, and for the Git Bash path when it cannot find one.\n"
    "    Run it directly in a terminal, not from a script, a pipe or a build step."
)

CANCELLED = "cancelled - nothing was changed."


def confirm(question, default=False):
    """A yes/no question. Anything but y/yes is no."""
    hint = " [Y/n]: " if default else " [y/N]: "
    answer = _ask(input, question + hint).strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def text(question, default=None):
    """A free-text answer. Blank takes `default`, or "" when there is none."""
    hint = " [%s]: " % default if default else ": "
    answer = _ask(input, question + hint).strip()
    return answer or (default or "")


def secret(question):
    """A secret answer, never echoed.

    getpass, not input: an echoed token lands in the terminal scrollback and in
    any recording of the session.
    """
    return _ask(getpass.getpass, question + ": ").strip()


def _ask(reader, prompt):
    try:
        return reader(prompt)
    except EOFError:
        raise LmiError(NO_TERMINAL, EXIT_USAGE)
    except KeyboardInterrupt:
        # Every prompt is asked before anything is modified, so Ctrl-C here is
        # genuinely a no-op - say so rather than printing a traceback.
        raise LmiError(CANCELLED, EXIT_USAGE)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/commands/install/test_prompts.py -q`
Expected: PASS, 19 tests. Then `python3 -m pytest tests/ -q` — 174 passed.

- [ ] **Step 5: Commit**

```bash
git add lmi/commands/install/prompts.py tests/commands/install/test_prompts.py
git commit -m "feat(install): interactive prompts with a no-terminal guard

No --yes flag by design, so a run with no terminal cannot answer. EOFError
becomes exit 2 with an explanation rather than an unbounded wait."
```

---

### Task 3: npm invocation and the `--global` fallback

**Files:**
- Create: `lmi/commands/install/npm.py`
- Create: `tests/commands/install/conftest.py`
- Create: `tests/commands/install/test_npm.py`

**Interfaces:**
- Consumes: `config.PACKAGE`, `exit_codes.EXIT_NPM_FAILED`, `lmi.core.errors.{LmiError, EXIT_USAGE}`
- Produces:
  - `npm.find() -> str` — absolute path to npm, or `LmiError(EXIT_USAGE)`
  - `npm.config_set(npm_exe: str, key: str, value: str, say) -> None`
  - `npm.install(npm_exe: str, say) -> None`
  - `say` is any `Callable[[str], None]`; tests pass a list's `append`.

- [ ] **Step 1: Write the `fake_npm` fixture**

`tests/commands/install/conftest.py`:

```python
"""Fixtures for the `lmi install` suite.

`fake_npm` replaces PATH ENTIRELY rather than prepending, exactly as the
schedule suite's fake_claude does: a real npm exists on a developer machine
and would otherwise win, rewriting their own ~/.npmrc and installing a real
package from a real registry.
"""

import os
import stat
import sys

import pytest

FAKE_NPM = """\
#!{python}
import os, sys

n_file = os.environ["FAKE_NPM_COUNT"]
n = 0
if os.path.exists(n_file):
    n = int(open(n_file).read() or 0)
n += 1
open(n_file, "w").write(str(n))

with open(os.path.join(os.environ["FAKE_NPM_DIR"], "argv-%d.txt" % n), "w") as fh:
    fh.write("\\n".join(sys.argv[1:]))

print("fake npm call %d: %s" % (n, " ".join(sys.argv[1:])))

# Fail only when --global is present, which is how the EACCES fallback that a
# root-owned global npmrc produces is exercised without needing root.
if os.environ.get("FAKE_NPM_FAIL_GLOBAL") and "--global" in sys.argv:
    sys.exit(243)

sys.exit(int(os.environ.get("FAKE_NPM_RC", "0")))
"""

# Windows has no #! mechanism, so a script with a shebang is not executable
# there. The fixture grows npm.cmd, the way the schedule suite grows claude.bat.
FAKE_CMD = '@"{python}" "%~dp0npm.py" %*\r\n'


class Npm:
    def __init__(self, recdir, count_file):
        self.dir = recdir
        self.count_file = count_file

    def calls(self):
        """Every invocation's argv, in order."""
        out = []
        for i in range(1, self.count() + 1):
            text = (self.dir / ("argv-%d.txt" % i)).read_text(encoding="utf-8")
            out.append(text.splitlines())
        return out

    def count(self):
        return int(self.count_file.read_text() or 0)


@pytest.fixture
def fake_npm(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / ("npm.py" if os.name == "nt" else "npm")
    exe.write_text(FAKE_NPM.format(python=sys.executable), encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    if os.name == "nt":
        (bindir / "npm.cmd").write_text(
            FAKE_CMD.format(python=sys.executable), encoding="utf-8"
        )

    recdir = tmp_path / "npmrec"
    recdir.mkdir()
    count_file = tmp_path / "npmcount.txt"
    count_file.write_text("0")

    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setenv("FAKE_NPM_DIR", str(recdir))
    monkeypatch.setenv("FAKE_NPM_COUNT", str(count_file))
    return Npm(recdir, count_file)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway HOME, so no test can touch the developer's real ~/.claude."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    return h
```

- [ ] **Step 2: Write the failing tests**

`tests/commands/install/test_npm.py`:

```python
"""Running npm: argv shape, the --global fallback, and failure handling."""

import pytest

from lmi.commands.install import npm
from lmi.core.errors import LmiError


def test_find_returns_the_npm_on_path(fake_npm):
    assert npm.find()


def test_find_without_npm_is_a_usage_error(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    with pytest.raises(LmiError) as exc:
        npm.find()
    assert exc.value.code == 2
    assert "Node" in str(exc.value)


def test_config_set_tries_global_first(fake_npm):
    npm.config_set(npm.find(), "registry", "https://r/", [].append)
    assert fake_npm.calls() == [["config", "set", "registry", "https://r/", "--global"]]


def test_config_set_falls_back_to_user_level(fake_npm, monkeypatch):
    """A root-owned global npmrc is the normal case on a system Node install.

    Dropping --global writes ~/.npmrc, which needs no root and still governs
    every `npm install -g` that user runs. A correct fallback, not a degraded one.
    """
    monkeypatch.setenv("FAKE_NPM_FAIL_GLOBAL", "1")
    said = []
    npm.config_set(npm.find(), "registry", "https://r/", said.append)
    assert fake_npm.calls() == [
        ["config", "set", "registry", "https://r/", "--global"],
        ["config", "set", "registry", "https://r/"],
    ]
    assert any("user level" in line for line in said)


def test_config_set_failing_both_ways_is_exit_1(fake_npm, monkeypatch):
    monkeypatch.setenv("FAKE_NPM_RC", "1")
    with pytest.raises(LmiError) as exc:
        npm.config_set(npm.find(), "registry", "https://r/", [].append)
    assert exc.value.code == 1
    assert fake_npm.count() == 2


def test_install_uses_the_package_constant(fake_npm):
    npm.install(npm.find(), [].append)
    assert fake_npm.calls() == [["install", "-g", "@anthropic-ai/claude-code"]]


def test_install_is_never_retried_without_g(fake_npm, monkeypatch):
    """MANDATORY. Silent failure: a package in ./node_modules and no `claude`.

    Dropping --global from `npm config set` is a correct fallback. Dropping -g
    from `npm install -g` is not a fallback at all - it installs into the
    current directory and creates no claude command, while npm exits 0. The
    only safe behaviour is to fail, so this pins that the retry never happens.
    """
    monkeypatch.setenv("FAKE_NPM_FAIL_GLOBAL", "1")
    monkeypatch.setenv("FAKE_NPM_RC", "0")
    with pytest.raises(LmiError) as exc:
        npm.install(npm.find(), [].append)
    assert exc.value.code == 1
    assert fake_npm.count() == 1
    assert fake_npm.calls()[0] == ["install", "-g", "@anthropic-ai/claude-code"]


def test_install_failure_names_both_ways_forward(fake_npm, monkeypatch):
    monkeypatch.setenv("FAKE_NPM_RC", "1")
    with pytest.raises(LmiError) as exc:
        npm.install(npm.find(), [].append)
    message = str(exc.value)
    assert "sudo" in message
    assert "prefix" in message


def test_a_registry_with_shell_metacharacters_is_passed_through_literally(fake_npm):
    """A list argv, never shell=True: a config value must not reach a shell."""
    nasty = "https://r/;rm -rf ~;#"
    npm.config_set(npm.find(), "registry", nasty, [].append)
    assert fake_npm.calls()[0][3] == nasty


def test_the_module_never_uses_shell_true():
    """MANDATORY. shell=True would make the registry URL executable."""
    import inspect
    assert "shell=True" not in inspect.getsource(npm)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m pytest tests/commands/install/test_npm.py -q`
Expected: `ModuleNotFoundError: No module named 'lmi.commands.install.npm'`.

- [ ] **Step 4: Write `npm.py`**

```python
"""Locating npm, and running one npm command.

Every invocation is a list argv through subprocess.run, never shell=True: the
registry URL comes from a config file and must never reach a shell. Output is
inherited rather than captured, so npm's own progress and errors reach the user
as they happen, and check=False so a non-zero exit returns instead of raising.
"""

import shutil
import subprocess

from .config import PACKAGE
from .exit_codes import EXIT_NPM_FAILED
from ...core.errors import EXIT_USAGE, LmiError

NO_NPM = (
    "npm was not found on PATH.\n"
    "    `lmi install claude` installs Claude Code through npm, so a Node.js\n"
    "    runtime has to be present first. Install Node.js 18 or newer, open a\n"
    "    new terminal, and run this again.\n"
    "    lmi deliberately does not install Node.js itself."
)

INSTALL_FAILED = (
    "npm install -g %s failed (exit %d).\n"
    "    The commonest cause is that the global node_modules directory is owned\n"
    "    by root. Either:\n"
    "      - re-run this command with sudo (an Administrator shell on Windows), or\n"
    "      - give npm a prefix you own:\n"
    "          npm config set prefix ~/.npm-global\n"
    "        and put ~/.npm-global/bin on your PATH, then run this again.\n"
    "    lmi never invokes sudo itself."
)


def find():
    """The npm executable, or a usage error naming what to install."""
    found = shutil.which("npm")
    if found is None:
        raise LmiError(NO_NPM, EXIT_USAGE)
    return found


def config_set(npm_exe, key, value, say):
    """`npm config set key value`, --global first, then user level.

    --global writes the npmrc under `npm prefix -g`, which on a system-wide Node
    install is root-owned. Retrying without the flag writes ~/.npmrc, which needs
    no root and still governs every `npm install -g` that user runs - a correct
    fallback, not a degraded one.
    """
    args = ["config", "set", key, value]
    if _run(npm_exe, args + ["--global"], say) == 0:
        return
    say("  --global failed; retrying at user level (~/.npmrc)")
    code = _run(npm_exe, args, say)
    if code != 0:
        raise LmiError(
            "npm config set %s failed (exit %d)" % (key, code), EXIT_NPM_FAILED
        )


def install(npm_exe, say):
    """`npm install -g @anthropic-ai/claude-code`.

    Deliberately NO fallback. Do not simplify this into config_set's
    retry-without-the-flag shape: dropping -g does not degrade, it does
    something else entirely - it installs into ./node_modules of whatever
    directory the user happened to be in, creates no `claude` command, and
    exits 0. A silent wrong-install is worse than a clean failure.
    """
    code = _run(npm_exe, ["install", "-g", PACKAGE], say)
    if code != 0:
        raise LmiError(INSTALL_FAILED % (PACKAGE, code), EXIT_NPM_FAILED)


def _run(npm_exe, args, say):
    say("  $ npm " + " ".join(args))
    return subprocess.run([npm_exe] + args).returncode
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/commands/install/test_npm.py -q`
Expected: PASS, 9 tests. Then `python3 -m pytest tests/ -q` — 183 passed.

- [ ] **Step 6: Commit**

```bash
git add lmi/commands/install/npm.py tests/commands/install/
git commit -m "feat(install): npm invocation with a --global fallback

npm config set retries without --global (writing ~/.npmrc, which needs no
root). npm install -g deliberately does not: dropping -g installs into
./node_modules and creates no claude command while exiting 0."
```

---

### Task 4: JSON document read / backup / atomic write

**Files:**
- Create: `lmi/commands/install/jsonfile.py`
- Create: `tests/commands/install/test_jsonfile.py`

**Interfaces:**
- Consumes: `exit_codes.EXIT_CONFIG_WRITE`, `lmi.core.{fs, text}`, `lmi.core.errors.LmiError`
- Produces:
  - `jsonfile.TS_FORMAT: str` — `"%Y%m%d-%H%M%S"`
  - `jsonfile.timestamp() -> str`
  - `jsonfile.read(path: Path, what: str) -> dict` — `{}` when absent or empty
  - `jsonfile.backup(path: Path, stamp: str, what: str) -> Optional[Path]`
  - `jsonfile.write(path: Path, doc: dict, what: str, mode: Optional[int] = None) -> None`

- [ ] **Step 1: Write the failing test**

`tests/commands/install/test_jsonfile.py`:

```python
"""The mechanism for touching a JSON file the user cares about."""

import json
import os
import re
import stat

import pytest

from lmi.commands.install import jsonfile
from lmi.core.errors import LmiError
from tests.conftest import skip_as_root


def write_json(path, doc, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    if mode is not None:
        os.chmod(str(path), mode)
    return path


def test_timestamp_shape():
    assert re.match(r"^\d{8}-\d{6}$", jsonfile.timestamp())


def test_read_missing_file_is_empty(tmp_path):
    assert jsonfile.read(tmp_path / "nope.json", "settings") == {}


def test_read_empty_file_is_empty(tmp_path):
    path = tmp_path / "e.json"
    path.write_bytes(b"   \n")
    assert jsonfile.read(path, "settings") == {}


def test_read_returns_the_document(tmp_path):
    path = write_json(tmp_path / "s.json", {"model": "opus", "n": 1})
    assert jsonfile.read(path, "settings") == {"model": "opus", "n": 1}


def test_read_tolerates_a_bom(tmp_path):
    path = tmp_path / "s.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'{"model": "opus"}')
    assert jsonfile.read(path, "settings") == {"model": "opus"}


def test_read_invalid_json_is_exit_3(tmp_path):
    """MANDATORY. Silent failure: a user's hand-edited settings discarded.

    Treating unparseable JSON as {} and writing over it would silently destroy
    every setting the user had. Refusing, and naming the file, lets them fix it.
    """
    path = tmp_path / "s.json"
    path.write_text('{"model": }', encoding="utf-8")
    with pytest.raises(LmiError) as exc:
        jsonfile.read(path, "settings")
    assert exc.value.code == 3
    assert "s.json" in str(exc.value)


def test_read_a_json_array_is_exit_3(tmp_path):
    path = write_json(tmp_path / "s.json", [1, 2])
    with pytest.raises(LmiError) as exc:
        jsonfile.read(path, "settings")
    assert exc.value.code == 3


def test_backup_of_a_missing_file_is_none(tmp_path):
    assert jsonfile.backup(tmp_path / "nope.json", "20260806-120000", "s") is None


def test_backup_naming_and_content(tmp_path):
    path = write_json(tmp_path / "settings.json", {"model": "opus"})
    dest = jsonfile.backup(path, "20260806-120000", "settings")
    assert dest.name == "settings.json.bk_20260806-120000"
    assert json.loads(dest.read_text(encoding="utf-8")) == {"model": "opus"}
    assert path.exists(), "the original must remain"


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_backup_preserves_mode(tmp_path):
    """~/.claude.json is 0600 and holds per-project history.

    A backup at the default 0644 would publish it to every user on the box.
    """
    path = write_json(tmp_path / ".claude.json", {"a": 1}, mode=0o600)
    dest = jsonfile.backup(path, "20260806-120000", "claude.json")
    assert stat.S_IMODE(os.stat(str(dest)).st_mode) == 0o600


def test_write_creates_missing_parents(tmp_path):
    path = tmp_path / "home" / ".claude" / "settings.json"
    jsonfile.write(path, {"model": "opus"}, "settings")
    assert json.loads(path.read_text(encoding="utf-8")) == {"model": "opus"}


def test_write_is_indented_and_newline_terminated(tmp_path):
    path = tmp_path / "s.json"
    jsonfile.write(path, {"a": {"b": 1}}, "settings")
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert '\n  "a"' in text, "2-space indent, matching what Claude Code writes"


def test_write_uses_lf_even_on_windows(tmp_path):
    path = tmp_path / "s.json"
    jsonfile.write(path, {"a": 1}, "settings")
    assert b"\r\n" not in path.read_bytes()


def test_write_leaves_no_temp_file(tmp_path):
    path = tmp_path / "s.json"
    jsonfile.write(path, {"a": 1}, "settings")
    assert [p.name for p in tmp_path.iterdir()] == ["s.json"]


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_write_preserves_an_existing_mode(tmp_path):
    path = write_json(tmp_path / ".claude.json", {"a": 1}, mode=0o600)
    jsonfile.write(path, {"a": 2}, "claude.json")
    assert stat.S_IMODE(os.stat(str(path)).st_mode) == 0o600


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_write_can_force_a_mode(tmp_path):
    path = write_json(tmp_path / "settings.json", {"a": 1}, mode=0o644)
    jsonfile.write(path, {"a": 2}, "settings", mode=0o600)
    assert stat.S_IMODE(os.stat(str(path)).st_mode) == 0o600


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_the_mode_is_set_before_the_file_becomes_visible(tmp_path, monkeypatch):
    """MANDATORY. Silent failure: a token briefly readable by everyone.

    The chmod must land on the temp file BEFORE os.replace publishes it, or
    there is a window in which settings.json holds an auth token at the default
    0644 and any user on the box can read it. Nothing observable afterwards
    distinguishes the two orderings - the end state is identical - so the only
    way to pin it is to look at the mode at the instant of the rename.

    Deliberately behavioural. An earlier draft asserted
    `inspect.getsource(...).index("chmod") < ....index("os.replace")`, which
    could never fail: getsource includes the docstring, and the docstring says
    "chmod ... BEFORE os.replace", so the assertion was satisfied by prose no
    matter what the code did.
    """
    captured = {}
    real_replace = os.replace

    def spy(src, dst):
        captured["mode"] = stat.S_IMODE(os.stat(src).st_mode)
        return real_replace(src, dst)

    monkeypatch.setattr(jsonfile.os, "replace", spy)
    jsonfile.write(tmp_path / "s.json", {"a": 1}, "settings", mode=0o600)
    assert captured["mode"] == 0o600


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_write_to_an_unwritable_directory_is_exit_3(tmp_path, readonly_dir):
    with pytest.raises(LmiError) as exc:
        jsonfile.write(readonly_dir / "s.json", {"a": 1}, "settings")
    assert exc.value.code == 3


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_a_failed_write_leaves_no_temp_file(tmp_path, readonly_dir):
    with pytest.raises(LmiError):
        jsonfile.write(readonly_dir / "s.json", {"a": 1}, "settings")
    assert list(readonly_dir.iterdir()) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/commands/install/test_jsonfile.py -q`
Expected: `ModuleNotFoundError: No module named 'lmi.commands.install.jsonfile'`.

- [ ] **Step 3: Write `jsonfile.py`**

```python
"""Reading, backing up and atomically writing one JSON document.

Split from settings.py and claude_json.py on purpose: those two know *what*
belongs in a document, this one knows *how* to touch a file the user cares
about. The dangerous part is here, tested once and thoroughly, without knowing
anything about Claude Code's schema.

Every write is atomic - a temp file beside the target, then os.replace, which
is atomic on POSIX and on Windows. A half-written settings.json is invalid
JSON and Claude Code cannot start without it.
"""

import json
import os
import shutil
import stat as _stat
from datetime import datetime

from .exit_codes import EXIT_CONFIG_WRITE
from ...core import fs, text
from ...core.errors import LmiError

# Re-declared rather than imported from commands/schedule/paths.py: commands do
# not import each other, and promoting a format string to core/ in advance is
# the thing the architecture rule warns against.
TS_FORMAT = "%Y%m%d-%H%M%S"

BACKUP_SUFFIX = ".bk_"


def timestamp():
    return datetime.now().strftime(TS_FORMAT)


def read(path, what):
    """The document, or {} when the file is absent or empty.

    An unparseable file is an error rather than an empty document: treating it
    as {} would write over settings the user hand-edited and silently discard
    every one of them.
    """
    if fs.kind(path) != fs.FILE:
        return {}
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LmiError(
            "the %s file cannot be read: %s (%s)" % (what, path, exc),
            EXIT_CONFIG_WRITE,
        )
    if not raw.strip():
        return {}
    try:
        doc = json.loads(text.decode_with_bom(raw))
    except (UnicodeDecodeError, ValueError) as exc:
        raise LmiError(
            "the %s file is not valid JSON: %s (%s)\n"
            "    Refusing to overwrite it - fix or move the file and run this "
            "again." % (what, path, exc),
            EXIT_CONFIG_WRITE,
        )
    if not isinstance(doc, dict):
        raise LmiError(
            "the %s file must contain a JSON object: %s\n"
            "    Refusing to overwrite it." % (what, path),
            EXIT_CONFIG_WRITE,
        )
    return doc


def backup(path, stamp, what):
    """Copy `path` beside itself as <name>.bk_<stamp>. None if there is nothing.

    copy2, not copy: it preserves the mode, and ~/.claude.json is 0600 and holds
    per-project history. A backup at the default 0644 would publish it.
    """
    if fs.kind(path) != fs.FILE:
        return None
    dest = path.with_name(path.name + BACKUP_SUFFIX + stamp)
    try:
        shutil.copy2(str(path), str(dest))
    except OSError as exc:
        raise LmiError(
            "could not back up the %s file: %s -> %s (%s)\n"
            "    Nothing was changed: modifying a file we cannot preserve is "
            "not worth the risk." % (what, path, dest, exc),
            EXIT_CONFIG_WRITE,
        )
    return dest


def write(path, doc, what, mode=None):
    """Replace `path` with `doc`, atomically.

    `mode` forces a permission; without it an existing file's mode is preserved.
    Either way the chmod happens on the temp file BEFORE os.replace, so there is
    no window in which the contents exist at the default 0644 - which matters
    because settings.json can contain an auth token.
    """
    existing = _mode_of(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Not fatal on its own - the open below produces the better message.
        pass

    tmp = path.with_name("%s.lmi-tmp-%d" % (path.name, os.getpid()))
    try:
        # open(), not Path.write_text(newline=...): that parameter arrived in
        # 3.10 and the floor here is 3.9.
        with open(str(tmp), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        effective = mode if mode is not None else existing
        if effective is not None:
            os.chmod(str(tmp), effective)
        os.replace(str(tmp), str(path))
    except OSError as exc:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise LmiError(
            "could not write the %s file: %s (%s)" % (what, path, exc),
            EXIT_CONFIG_WRITE,
        )


def _mode_of(path):
    if fs.kind(path) != fs.FILE:
        return None
    try:
        return _stat.S_IMODE(os.stat(str(path)).st_mode)
    except OSError:
        return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/commands/install/test_jsonfile.py -q`
Expected: PASS, 19 tests. Then `python3 -m pytest tests/ -q` — 202 passed.

- [ ] **Step 5: Commit**

```bash
git add lmi/commands/install/jsonfile.py tests/commands/install/test_jsonfile.py
git commit -m "feat(install): atomic read/backup/write for a JSON document

Unparseable input is refused rather than treated as empty, which would
silently discard hand-edited settings. Modes are preserved and applied
before os.replace, so a token is never briefly on disk at 0644."
```

---

### Task 5: The two Claude configuration documents

**Files:**
- Create: `lmi/commands/install/settings.py`
- Create: `lmi/commands/install/claude_json.py`
- Create: `tests/commands/install/test_settings.py`
- Create: `tests/commands/install/test_claude_json.py`

**Interfaces:**
- Consumes: `jsonfile`
- Produces:
  - `settings.path() -> Path` — `~/.claude/settings.json`
  - `settings.merge(doc: dict, env: dict, marketplaces: dict) -> dict`
  - `settings.token_of(doc: dict) -> Optional[str]`
  - `settings.TOKEN_KEY: str` — `"ANTHROPIC_AUTH_TOKEN"`
  - `settings.MARKETPLACES_KEY: str` — `"extraKnownMarketplaces"`
  - `claude_json.path() -> Path` — `~/.claude.json`
  - `claude_json.ONBOARDING_KEY: str` — `"hasCompletedOnboarding"`
  - `claude_json.needs_update(doc: dict) -> bool`
  - `claude_json.mark_complete(doc: dict) -> dict`

- [ ] **Step 1: Write the failing tests**

`tests/commands/install/test_settings.py`:

```python
"""What goes into ~/.claude/settings.json."""

from pathlib import Path

from lmi.commands.install import settings


def test_path_is_under_home(home):
    assert settings.path() == Path(str(home)) / ".claude" / "settings.json"


def test_the_marketplaces_key_is_spelled_exactly(): 
    """MANDATORY. Silent failure: marketplaces never register.

    Verified against the Claude Code 2.1.222 settings schema. Any other spelling
    writes cleanly, parses cleanly, and is ignored.
    """
    assert settings.MARKETPLACES_KEY == "extraKnownMarketplaces"


def test_the_token_key_is_spelled_exactly():
    assert settings.TOKEN_KEY == "ANTHROPIC_AUTH_TOKEN"


def test_unrelated_keys_survive():
    doc = {"model": "opus[1m]", "theme": "dark", "enabledPlugins": {"a": True}}
    merged = settings.merge(doc, {"X": "1"}, {})
    assert merged["model"] == "opus[1m]"
    assert merged["theme"] == "dark"
    assert merged["enabledPlugins"] == {"a": True}


def test_an_unmanaged_env_key_survives():
    doc = {"env": {"SOMETHING_ELSE": "keep me"}}
    merged = settings.merge(doc, {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000"}, {})
    assert merged["env"]["SOMETHING_ELSE"] == "keep me"
    assert merged["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "256000"


def test_a_managed_env_key_is_overwritten_not_duplicated():
    doc = {"env": {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "8000"}}
    merged = settings.merge(doc, {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"}, {})
    assert merged["env"] == {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"}


def test_marketplaces_under_other_names_survive():
    doc = {"extraKnownMarketplaces": {"existing": {"source": {"source": "github",
                                                              "repo": "a/b"}}}}
    merged = settings.merge(doc, {}, {"corp": {"source": {"source": "git",
                                                          "url": "https://g/"}}})
    assert set(merged["extraKnownMarketplaces"]) == {"existing", "corp"}


def test_a_same_named_marketplace_is_replaced():
    doc = {"extraKnownMarketplaces": {"corp": {"source": {"source": "github",
                                                          "repo": "old/old"}}}}
    new = {"corp": {"source": {"source": "git", "url": "https://new/"}}}
    merged = settings.merge(doc, {}, new)
    assert merged["extraKnownMarketplaces"]["corp"] == new["corp"]


def test_marketplaces_are_passed_through_unaltered():
    """lmi does not model source types; upstream may add one tomorrow."""
    exotic = {"m": {"source": {"source": "something-new-in-2027", "x": [1, {"y": 2}]}}}
    merged = settings.merge({}, {}, exotic)
    assert merged["extraKnownMarketplaces"] == exotic


def test_a_corrupt_env_value_of_the_wrong_type_is_replaced_not_merged():
    """If env is somehow a list, merging into it would raise. Replace it."""
    merged = settings.merge({"env": ["not", "a", "dict"]}, {"A": "1"}, {})
    assert merged["env"] == {"A": "1"}


def test_empty_inputs_add_no_keys():
    assert settings.merge({}, {}, {}) == {}


def test_token_of_reads_the_env_block():
    assert settings.token_of({"env": {"ANTHROPIC_AUTH_TOKEN": "sk-x"}}) == "sk-x"


def test_token_of_missing_is_none():
    assert settings.token_of({}) is None
    assert settings.token_of({"env": {}}) is None
    assert settings.token_of({"env": "corrupt"}) is None
```

`tests/commands/install/test_claude_json.py`:

```python
"""What goes into ~/.claude.json."""

from pathlib import Path

from lmi.commands.install import claude_json


def test_path_is_the_dotfile_in_home(home):
    assert claude_json.path() == Path(str(home)) / ".claude.json"


def test_the_onboarding_key_has_a_lowercase_b():
    """MANDATORY. Silent failure: onboarding still runs.

    Verified in the Claude Code 2.1.222 key list and in a live ~/.claude.json.
    'hasCompletedOnBoarding' writes cleanly, parses cleanly, and does nothing -
    the user is greeted by the onboarding flow the command promised to skip.
    """
    assert claude_json.ONBOARDING_KEY == "hasCompletedOnboarding"


def test_absent_key_needs_an_update():
    assert claude_json.needs_update({}) is True


def test_false_needs_an_update():
    """A machine image shipping false must be corrected, not left alone."""
    assert claude_json.needs_update({"hasCompletedOnboarding": False}) is True


def test_already_true_needs_nothing():
    assert claude_json.needs_update({"hasCompletedOnboarding": True}) is False


def test_a_truthy_non_true_value_still_needs_an_update():
    assert claude_json.needs_update({"hasCompletedOnboarding": "yes"}) is True


def test_mark_complete_sets_exactly_one_key():
    doc = {"projects": {"/a": {"history": [1, 2]}}, "firstStartTime": "x"}
    marked = claude_json.mark_complete(doc)
    assert marked["hasCompletedOnboarding"] is True
    assert marked["projects"] == {"/a": {"history": [1, 2]}}
    assert marked["firstStartTime"] == "x"
    assert len(marked) == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/commands/install/test_settings.py tests/commands/install/test_claude_json.py -q`
Expected: two `ModuleNotFoundError`s.

- [ ] **Step 3: Write `settings.py`**

```python
"""What goes into ~/.claude/settings.json.

Content only - jsonfile.py owns reading, backing up and writing. Nothing here
touches the filesystem except path().
"""

from pathlib import Path

# Verified against the Claude Code 2.1.222 settings schema, which declares
# extraKnownMarketplaces as record(name, {source}) and whose own writer defaults
# to "userSettings" scope - so this file, not managed settings, is the right
# place. Any other spelling writes cleanly and is ignored.
MARKETPLACES_KEY = "extraKnownMarketplaces"
TOKEN_KEY = "ANTHROPIC_AUTH_TOKEN"
ENV_KEY = "env"


def path():
    return Path.home() / ".claude" / "settings.json"


def merge(doc, env, marketplaces):
    """Merge `env` and `marketplaces` into `doc` and return it.

    Merged one level down, not at the document root, so an env key lmi does not
    manage and a marketplace under another name both survive. A key lmi does
    manage is overwritten, so re-running after editing the config converges on
    the config instead of accumulating stale entries.
    """
    if env:
        doc[ENV_KEY] = _merged(doc.get(ENV_KEY), env)
    if marketplaces:
        doc[MARKETPLACES_KEY] = _merged(doc.get(MARKETPLACES_KEY), marketplaces)
    return doc


def token_of(doc):
    """The auth token already configured, or None.

    Used only to tell the user a token exists - never to print one.
    """
    env = doc.get(ENV_KEY)
    if not isinstance(env, dict):
        return None
    return env.get(TOKEN_KEY) or None


def _merged(current, additions):
    # A value of the wrong type is replaced rather than merged into: dict.update
    # on a list raises, and the file is Claude Code's to validate, not ours.
    if not isinstance(current, dict):
        current = {}
    else:
        current = dict(current)
    current.update(additions)
    return current
```

- [ ] **Step 4: Write `claude_json.py`**

```python
"""What goes into ~/.claude.json.

Content only - jsonfile.py owns reading, backing up and writing.
"""

from pathlib import Path

# Lowercase "b". Verified in the Claude Code 2.1.222 key list and in a live
# ~/.claude.json. "hasCompletedOnBoarding" - the natural way to write it, and
# the way the requirement was written - parses cleanly, writes cleanly and does
# nothing at all: the onboarding flow this command promised to skip still runs.
ONBOARDING_KEY = "hasCompletedOnboarding"


def path():
    return Path.home() / ".claude.json"


def needs_update(doc):
    """True unless onboarding is already marked complete.

    `is not True` rather than a falsiness check: a key present but False must be
    corrected, because the requirement is that onboarding is skipped and a False
    left in place does not achieve it. Already True means the file is not
    rewritten at all - no backup and no timestamp churn on a 63 KB document for
    a no-op.
    """
    return doc.get(ONBOARDING_KEY) is not True


def mark_complete(doc):
    doc[ONBOARDING_KEY] = True
    return doc
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/commands/install/ -q`
Expected: PASS. Then `python3 -m pytest tests/ -q` — 222 passed.

- [ ] **Step 6: Commit**

```bash
git add lmi/commands/install/settings.py lmi/commands/install/claude_json.py tests/commands/install/
git commit -m "feat(install): the two Claude configuration documents

Keys verified against the shipped 2.1.222 binary. hasCompletedOnboarding
has a lowercase b; a present-but-false value is corrected, and an
already-true one is not rewritten at all."
```

---

### Task 6: Git Bash discovery (Windows only)

**Files:**
- Create: `lmi/commands/install/gitbash.py`
- Create: `tests/commands/install/test_gitbash.py`

**Interfaces:**
- Consumes: `lmi.core.fs`
- Produces:
  - `gitbash.VAR: str` — `"CLAUDE_CODE_GIT_BASH_PATH"`
  - `gitbash.VALID_NAMES: tuple`
  - `gitbash.on_windows() -> bool`
  - `gitbash.is_valid(path: Optional[str]) -> bool`
  - `gitbash.candidates() -> List[str]`
  - `gitbash.find() -> Optional[str]`
  - `gitbash.persist(path: str, say) -> bool`

- [ ] **Step 1: Write the failing test**

`tests/commands/install/test_gitbash.py`:

```python
"""Finding Git Bash and persisting CLAUDE_CODE_GIT_BASH_PATH.

Windows-only behaviour, driven on any OS by patching gitbash.on_windows and the
environment variables the search reads. The point of the off-Windows tests is
the opposite one: proving nothing happens there.
"""

import os

import pytest

from lmi.commands.install import gitbash


@pytest.fixture
def winenv(tmp_path, monkeypatch):
    """A fake Windows filesystem layout, with every search root redirected."""
    monkeypatch.setattr(gitbash, "on_windows", lambda: True)
    monkeypatch.setattr(gitbash, "_registry_paths", lambda: [])
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    monkeypatch.delenv(gitbash.VAR, raising=False)
    empty = tmp_path / "nopath"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    return tmp_path


def make(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    return path


def test_the_variable_is_spelled_exactly():
    assert gitbash.VAR == "CLAUDE_CODE_GIT_BASH_PATH"


def test_is_valid_accepts_the_names_claude_code_accepts(tmp_path):
    for name in ("bash.exe", "sh.exe", "bash", "sh"):
        assert gitbash.is_valid(str(make(tmp_path / name)))


def test_is_valid_rejects_another_binary(tmp_path):
    """MANDATORY. Silent failure: Claude Code discards what we wrote.

    Claude Code checks the basename is bash/sh before honouring the variable,
    warns, and falls back to its own two-path search. Writing git.exe there is
    worse than writing nothing: it looks configured and is not.
    """
    assert gitbash.is_valid(str(make(tmp_path / "git.exe"))) is False


def test_is_valid_rejects_a_path_that_does_not_exist(tmp_path):
    assert gitbash.is_valid(str(tmp_path / "gone" / "bash.exe")) is False


def test_is_valid_rejects_empty_and_none():
    assert gitbash.is_valid("") is False
    assert gitbash.is_valid(None) is False


def test_is_valid_survives_an_impossible_path():
    """fs.kind, not Path.is_file(): an over-long name raises ENAMETOOLONG."""
    assert gitbash.is_valid("/" + "x" * 5000 + "/bash.exe") is False


def test_an_existing_valid_variable_wins(winenv, monkeypatch):
    already = make(winenv / "custom" / "bash.exe")
    monkeypatch.setenv(gitbash.VAR, str(already))
    make(winenv / "pf" / "Git" / "bin" / "bash.exe")
    assert gitbash.find() == str(already)


def test_an_existing_invalid_variable_is_ignored(winenv, monkeypatch):
    monkeypatch.setenv(gitbash.VAR, str(winenv / "gone" / "bash.exe"))
    expected = make(winenv / "pf" / "Git" / "bin" / "bash.exe")
    assert gitbash.find() == str(expected)


def test_the_registry_beats_program_files(winenv, monkeypatch):
    """HKLM\\SOFTWARE\\GitForWindows is authoritative; the fixed paths guess."""
    from_registry = make(winenv / "elsewhere" / "Git" / "bin" / "bash.exe")
    monkeypatch.setattr(gitbash, "_registry_paths", lambda: [str(from_registry)])
    make(winenv / "pf" / "Git" / "bin" / "bash.exe")
    assert gitbash.find() == str(from_registry)


@pytest.mark.parametrize("relative", [
    ("pf", "Git", "bin", "bash.exe"),
    ("pf86", "Git", "bin", "bash.exe"),
    ("pf", "Git", "usr", "bin", "bash.exe"),
    ("lad", "Programs", "Git", "bin", "bash.exe"),
])
def test_each_fixed_candidate_is_found_in_isolation(winenv, relative):
    expected = make(winenv.joinpath(*relative))
    assert gitbash.find() == str(expected)


def test_program_files_beats_the_per_user_install(winenv):
    make(winenv / "lad" / "Programs" / "Git" / "bin" / "bash.exe")
    expected = make(winenv / "pf" / "Git" / "bin" / "bash.exe")
    assert gitbash.find() == str(expected)


def test_derived_from_git_on_path(winenv, monkeypatch):
    """Git installed somewhere unusual, but on PATH: <root>/cmd/git -> <root>/bin/bash."""
    root = winenv / "opt" / "Git"
    make(root / "bin" / "bash.exe")
    git = make(root / "cmd" / "git.exe")
    monkeypatch.setattr(gitbash.shutil, "which", lambda name: str(git))
    assert gitbash.find() == str(root / "bin" / "bash.exe")


def test_nothing_installed_is_none(winenv):
    assert gitbash.find() is None


def test_off_windows_nothing_is_probed(tmp_path, monkeypatch):
    """MANDATORY. CLAUDE_CODE_GIT_BASH_PATH is read through path/win32.

    It is never consulted on Linux or macOS, so probing there and writing the
    key into settings.json would be pure noise in a file the user reads.
    """
    monkeypatch.setattr(gitbash, "on_windows", lambda: False)
    make(tmp_path / "pf" / "Git" / "bin" / "bash.exe")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    assert gitbash.candidates() == []
    assert gitbash.find() is None


def test_persist_off_windows_does_nothing(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("setx must not run off Windows")

    monkeypatch.setattr(gitbash, "on_windows", lambda: False)
    monkeypatch.setattr(gitbash.subprocess, "run", explode)
    assert gitbash.persist("/anything", [].append) is False


def test_persist_calls_setx_with_a_list_argv(monkeypatch):
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(gitbash, "on_windows", lambda: True)
    monkeypatch.setattr(gitbash.subprocess, "run",
                        lambda argv, **k: calls.append(argv) or Result())
    assert gitbash.persist(r"C:\Git\bin\bash.exe", [].append) is True
    assert calls == [["setx", "CLAUDE_CODE_GIT_BASH_PATH", r"C:\Git\bin\bash.exe"]]


def test_persist_reports_failure_without_raising(monkeypatch):
    """A failed setx must not fail the install: npm already succeeded."""
    class Result:
        returncode = 1

    monkeypatch.setattr(gitbash, "on_windows", lambda: True)
    monkeypatch.setattr(gitbash.subprocess, "run", lambda argv, **k: Result())
    said = []
    assert gitbash.persist(r"C:\Git\bin\bash.exe", said.append) is False
    assert any("WARN" in line for line in said)


def test_persist_survives_setx_being_absent(monkeypatch):
    monkeypatch.setattr(gitbash, "on_windows", lambda: True)

    def missing(argv, **kwargs):
        raise OSError("no setx")

    monkeypatch.setattr(gitbash.subprocess, "run", missing)
    assert gitbash.persist("x", [].append) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/commands/install/test_gitbash.py -q`
Expected: `ModuleNotFoundError: No module named 'lmi.commands.install.gitbash'`.

- [ ] **Step 3: Write `gitbash.py`**

```python
"""Finding Git Bash on Windows, and persisting CLAUDE_CODE_GIT_BASH_PATH.

Windows only, and not "runs and no-ops elsewhere" - Claude Code resolves this
variable through require("path/win32") and never reads it on Linux or macOS, so
probing there would be noise and writing the key into settings.json would put a
meaningless line in a file the user reads.

Claude Code's own auto-detection checks exactly two paths, so a Git installed
anywhere else is invisible to it. That is what makes searching harder here
worth doing - and also why every candidate is validated the same way Claude
Code validates: it requires the basename to be bash/sh AND the file to exist,
and warns and ignores the variable otherwise. Writing a path it rejects is
worse than writing nothing, because it looks configured.
"""

import os
import shutil
import subprocess
from pathlib import Path

from ...core import fs

VAR = "CLAUDE_CODE_GIT_BASH_PATH"

# Exactly the set Claude Code accepts. Do not widen it.
VALID_NAMES = ("bash.exe", "sh.exe", "bash", "sh")


def on_windows():
    """os.name == "nt", in a form a test can override.

    Monkeypatching os.name itself is not an option: pathlib chooses its concrete
    class from it at instantiation, so setting it to "nt" on Linux makes every
    Path() raise NotImplementedError - including pytest's own.
    """
    return os.name == "nt"


def is_valid(path):
    """Would Claude Code honour this path?"""
    if not path:
        return False
    if Path(path).name.lower() not in VALID_NAMES:
        return False
    # fs.kind, not Path.is_file(): an over-long path raises ENAMETOOLONG rather
    # than returning False, and a user-typed answer can be anything.
    return fs.kind(path) == fs.FILE


def candidates():
    """Every place to look, best first. Empty off Windows."""
    if not on_windows():
        return []

    found = []
    existing = os.environ.get(VAR)
    if existing:
        found.append(existing)

    # Authoritative: this is what the Git for Windows installer records.
    found.extend(_registry_paths())

    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)",
                                       r"C:\Program Files (x86)")
    found.append(str(Path(program_files) / "Git" / "bin" / "bash.exe"))
    found.append(str(Path(program_files_x86) / "Git" / "bin" / "bash.exe"))
    found.append(str(Path(program_files) / "Git" / "usr" / "bin" / "bash.exe"))

    # A per-user Git install needs no admin, so it is common on locked-down
    # machines - and it is one Claude Code cannot find on its own.
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        found.append(
            str(Path(local_appdata) / "Programs" / "Git" / "bin" / "bash.exe")
        )

    git = shutil.which("git")
    if git:
        # git.exe lives in <root>\cmd\ or <root>\bin\; bash is in <root>\bin\.
        found.append(str(Path(git).parent.parent / "bin" / "bash.exe"))

    return found


def find():
    """The first candidate Claude Code would accept, or None."""
    for candidate in candidates():
        if is_valid(candidate):
            return candidate
    return None


def persist(path, say):
    """Set CLAUDE_CODE_GIT_BASH_PATH for future shells. True if it took.

    setx rather than a raw winreg write because setx broadcasts WM_SETTINGCHANGE
    itself. Its 1024-byte truncation - the trap pylmi walks into - applies to
    PATH, an accumulated list; this value is a single short path. lmi never uses
    setx for PATH.

    Never raises. npm has already succeeded by the time this runs, so a failure
    here is a warning, not a failed installation.
    """
    if not on_windows():
        return False
    try:
        code = subprocess.run(["setx", VAR, path]).returncode
    except OSError as exc:
        say("[WARN] could not run setx to set %s (%s)" % (VAR, exc))
        return False
    if code != 0:
        say("[WARN] setx %s failed (exit %d). The value is still written into "
            "settings.json, so claude will pick it up." % (VAR, code))
        return False
    return True


def _registry_paths():
    """InstallPath from HKLM\\SOFTWARE\\GitForWindows, 64- and 32-bit views.

    Its own module-level function so a test can replace it wholesale: winreg
    does not exist off Windows, and importing it is the only Windows-specific
    import in the package.
    """
    try:
        import winreg
    except ImportError:
        return []

    found = []
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GitForWindows", 0,
                winreg.KEY_READ | view,
            )
        except OSError:
            continue
        try:
            root, _ = winreg.QueryValueEx(key, "InstallPath")
        except OSError:
            root = None
        finally:
            winreg.CloseKey(key)
        if root:
            found.append(str(Path(root) / "bin" / "bash.exe"))
    return found
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/commands/install/test_gitbash.py -q`
Expected: PASS, 22 tests. Then `python3 -m pytest tests/ -q` — 244 passed.

- [ ] **Step 5: Commit**

```bash
git add lmi/commands/install/gitbash.py tests/commands/install/test_gitbash.py
git commit -m "feat(install): Windows Git Bash discovery

Seven candidates including the GitForWindows registry key and per-user
installs, which Claude Code's own two-path search cannot see. Every
candidate is basename-validated the way Claude Code validates, since a
path it rejects looks configured and is not."
```

---

### Task 7: Orchestration and registration

**Files:**
- Create: `lmi/commands/install/runner.py`
- Modify: `lmi/commands/install/__init__.py` (replace the Task 1 stub)
- Modify: `lmi/commands/__init__.py`
- Modify: `tests/test_cli.py:22-24` (`test_schedule_is_registered`)
- Create: `tests/commands/install/test_runner.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6
- Produces: `runner.run(args) -> int`; the package exports `NAME`, `HELP`, `add_arguments`, `run`

- [ ] **Step 1: Write the failing test**

`tests/commands/install/test_runner.py`:

```python
"""End-to-end orchestration, with npm and every prompt faked."""

import json
import os
import stat

import pytest

from lmi.commands.install import gitbash, prompts, runner, settings
from lmi.core.errors import LmiError
from tests.conftest import skip_as_root


class Args:
    def __init__(self, config, target="claude"):
        self.config = config
        self.target = target


@pytest.fixture
def cfg_file(tmp_path):
    path = tmp_path / "lmi.json"
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"claude": {
            "registry": "https://artifactory.corp.local/api/npm/npm/",
            "marketplaces": {"corp": {"source": {"source": "git",
                                                 "url": "https://g/c.git"}}},
        }}, fh)
    return path


@pytest.fixture
def answers(monkeypatch):
    """Script the interactive flow; record what was asked."""
    state = {"confirm": [], "secret": [], "text": [], "asked": []}

    def take(kind, question, *rest):
        state["asked"].append(question)
        queue = state[kind]
        if not queue:
            raise AssertionError("unscripted %s: %r" % (kind, question))
        return queue.pop(0)

    monkeypatch.setattr(prompts, "confirm",
                        lambda q, default=False: take("confirm", q))
    monkeypatch.setattr(prompts, "secret", lambda q: take("secret", q))
    monkeypatch.setattr(prompts, "text",
                        lambda q, default=None: take("text", q))
    # Off Windows by default: Git Bash is Windows-only.
    monkeypatch.setattr(gitbash, "on_windows", lambda: False)
    return state


@pytest.fixture
def no_claude(monkeypatch):
    """`claude` is not installed - the fresh-install path."""
    real = runner.shutil.which

    def which(name):
        return None if name == "claude" else real(name)

    monkeypatch.setattr(runner.shutil, "which", which)


def read_settings(home):
    path = home / ".claude" / "settings.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_fresh_install_runs_npm_then_writes_both_files(
        fake_npm, home, cfg_file, answers, no_claude, capsys):
    answers["secret"] = ["sk-corp-token"]
    assert runner.run(Args(str(cfg_file))) == 0

    assert fake_npm.calls() == [
        ["config", "set", "strict-ssl", "false", "--global"],
        ["config", "set", "registry",
         "https://artifactory.corp.local/api/npm/npm/", "--global"],
        ["install", "-g", "@anthropic-ai/claude-code"],
    ]

    doc = read_settings(home)
    assert doc["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-corp-token"
    assert doc["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "256000"
    assert doc["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "204800"
    assert doc["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "64000"
    assert "corp" in doc["extraKnownMarketplaces"]
    assert gitbash.VAR not in doc["env"], "Git Bash is Windows-only"

    marker = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    assert marker["hasCompletedOnboarding"] is True


def test_a_cafile_replaces_strict_ssl_false(
        tmp_path, fake_npm, home, answers, no_claude):
    pem = tmp_path / "ca.pem"
    pem.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    path = tmp_path / "lmi.json"
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"claude": {"registry": "https://r/", "cafile": str(pem)}}, fh)
    answers["secret"] = [""]

    assert runner.run(Args(str(path))) == 0
    flat = [" ".join(call) for call in fake_npm.calls()]
    assert any("cafile" in c for c in flat)
    assert not any("strict-ssl" in c for c in flat)


def test_no_cafile_warns_about_tls(
        fake_npm, home, cfg_file, answers, no_claude, capsys):
    answers["secret"] = [""]
    runner.run(Args(str(cfg_file)))
    out = capsys.readouterr().out
    assert "[WARN]" in out and "verification" in out


def test_declining_repair_changes_nothing(
        fake_npm, home, cfg_file, answers, monkeypatch, capsys):
    """MANDATORY. Silent failure: a machine reconfigured after the user said no.

    "Already installed - repair?" answered no must be a complete no-op: no npm
    command, no settings written, no backup, no onboarding flag. Exit 0, because
    the user answered the question rather than hitting an error.
    """
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/" + name)
    answers["confirm"] = [False]

    assert runner.run(Args(str(cfg_file))) == 0
    assert fake_npm.count() == 0
    assert not (home / ".claude" / "settings.json").exists()
    assert not (home / ".claude.json").exists()


def test_accepting_repair_backs_up_and_reports_both_files(
        fake_npm, home, cfg_file, answers, monkeypatch, capsys):
    (home / ".claude").mkdir()
    with open(str(home / ".claude" / "settings.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"model": "opus[1m]", "theme": "dark"}, fh)
    with open(str(home / ".claude.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"projects": {"/x": {}}}, fh)

    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/" + name)
    answers["confirm"] = [True]
    answers["secret"] = ["sk-new"]

    assert runner.run(Args(str(cfg_file))) == 0

    backups = sorted(p.name for p in (home / ".claude").iterdir()
                     if ".bk_" in p.name)
    assert len(backups) == 1 and backups[0].startswith("settings.json.bk_")
    assert any(".claude.json.bk_" in p.name for p in home.iterdir())

    out = capsys.readouterr().out
    assert "settings.json.bk_" in out
    assert ".claude.json.bk_" in out

    doc = read_settings(home)
    assert doc["model"] == "opus[1m]", "unrelated keys must survive a repair"
    assert doc["theme"] == "dark"


def test_a_blank_token_leaves_an_existing_one_alone(
        fake_npm, home, cfg_file, answers, monkeypatch):
    (home / ".claude").mkdir()
    with open(str(home / ".claude" / "settings.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"env": {"ANTHROPIC_AUTH_TOKEN": "sk-old"}}, fh)
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/" + name)
    answers["confirm"] = [True]
    answers["secret"] = [""]

    assert runner.run(Args(str(cfg_file))) == 0
    assert read_settings(home)["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-old"


def test_an_already_onboarded_file_is_not_rewritten(
        fake_npm, home, cfg_file, answers, no_claude):
    with open(str(home / ".claude.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"hasCompletedOnboarding": True, "projects": {}}, fh)
    before = (home / ".claude.json").read_bytes()
    answers["secret"] = [""]

    assert runner.run(Args(str(cfg_file))) == 0
    assert (home / ".claude.json").read_bytes() == before
    assert not any(".claude.json.bk_" in p.name for p in home.iterdir()), \
        "no write means no backup"


def test_onboarding_false_is_corrected(
        fake_npm, home, cfg_file, answers, no_claude):
    with open(str(home / ".claude.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"hasCompletedOnboarding": False}, fh)
    answers["secret"] = [""]

    assert runner.run(Args(str(cfg_file))) == 0
    doc = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    assert doc["hasCompletedOnboarding"] is True


def test_a_failed_npm_install_touches_no_config_file(
        fake_npm, home, cfg_file, answers, no_claude, monkeypatch):
    """MANDATORY. Silent failure: settings seeded for a claude that is absent.

    If the config steps ran anyway, the machine would look provisioned - the
    256K profile, the marketplaces, onboarding skipped - with no claude binary.
    """
    monkeypatch.setenv("FAKE_NPM_RC", "1")
    answers["secret"] = ["sk-x"]

    with pytest.raises(LmiError) as exc:
        runner.run(Args(str(cfg_file)))
    assert exc.value.code == 1
    assert not (home / ".claude" / "settings.json").exists()
    assert not (home / ".claude.json").exists()


def test_every_question_is_asked_before_npm_runs(
        fake_npm, home, cfg_file, answers, monkeypatch):
    """A user who abandons the command at a prompt leaves nothing half-done."""
    seen = []
    real_run = runner.npm.install

    def spy(npm_exe, say):
        seen.append(("npm", len(answers["asked"])))
        return real_run(npm_exe, say)

    monkeypatch.setattr(runner.npm, "install", spy)
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/" + name)
    answers["confirm"] = [True]
    answers["secret"] = ["sk-x"]

    runner.run(Args(str(cfg_file)))
    assert seen and seen[0][1] == len(answers["asked"]), \
        "no question may be asked after the first npm command"


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_a_written_token_forces_mode_600(
        fake_npm, home, cfg_file, answers, no_claude):
    answers["secret"] = ["sk-secret"]
    runner.run(Args(str(cfg_file)))
    path = home / ".claude" / "settings.json"
    assert stat.S_IMODE(os.stat(str(path)).st_mode) == 0o600


def test_a_missing_claude_afterwards_warns_but_exits_0(
        fake_npm, home, cfg_file, answers, no_claude, capsys):
    """PATH in this process cannot see an npmrc prefix change made a second ago.

    Exiting non-zero here would fail runs that in fact succeeded.
    """
    answers["secret"] = [""]
    assert runner.run(Args(str(cfg_file))) == 0
    assert "[WARN]" in capsys.readouterr().out


def test_windows_writes_the_git_bash_path_into_settings(
        fake_npm, home, cfg_file, answers, no_claude, monkeypatch, tmp_path):
    bash = tmp_path / "Git" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_text("", encoding="utf-8")
    monkeypatch.setattr(gitbash, "on_windows", lambda: True)
    monkeypatch.setattr(gitbash, "find", lambda: str(bash))
    persisted = []
    monkeypatch.setattr(gitbash, "persist",
                        lambda p, say: persisted.append(p) or True)
    answers["secret"] = [""]

    assert runner.run(Args(str(cfg_file))) == 0
    assert read_settings(home)["env"][gitbash.VAR] == str(bash)
    assert persisted == [str(bash)]


def test_windows_without_git_bash_asks_then_warns(
        fake_npm, home, cfg_file, answers, no_claude, monkeypatch):
    monkeypatch.setattr(gitbash, "on_windows", lambda: True)
    monkeypatch.setattr(gitbash, "find", lambda: None)
    answers["secret"] = [""]
    answers["text"] = [""]          # user declines to supply one

    assert runner.run(Args(str(cfg_file))) == 0
    assert gitbash.VAR not in read_settings(home).get("env", {})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/commands/install/test_runner.py -q`
Expected: `ImportError: cannot import name 'runner'`.

- [ ] **Step 3: Write `runner.py`**

```python
"""The `lmi install claude` flow.

Order matters twice over.

First: every question is asked BEFORE anything is modified. A user who
abandons the command at a prompt, or answers "no" to the repair question,
leaves the machine exactly as they found it.

Second: npm runs before any Claude configuration file is touched. If the
install fails there is no claude to configure, and a machine carrying the site's
settings, its marketplaces and a skipped onboarding but no binary looks
provisioned and is not.
"""

import shutil

from . import claude_json, gitbash, jsonfile, npm, prompts, settings
from .config import build_config
from .exit_codes import EXIT_INTERNAL
from ...core.errors import EXIT_OK, LmiError

TLS_WARNING = (
    "[WARN] certificate verification is now OFF for every npm install by this\n"
    "       user, not just Claude Code. Anyone who can answer as the registry\n"
    "       host can serve a package whose install scripts run.\n"
    "       Set \"cafile\" in the config file to your internal CA to close this."
)

NO_CLAUDE_ON_PATH = (
    "[WARN] npm reported success but `claude` is not on PATH in this shell.\n"
    "       That is normal the first time npm's global bin directory is used:\n"
    "       this process cannot see a PATH change made a moment ago.\n"
    "       Open a new terminal and run `claude`. If it is still missing, add\n"
    "       the `bin` subdirectory of `npm prefix -g` to your PATH."
)

GIT_BASH_MISSING = (
    "[WARN] no Git Bash was found, so %s was not set.\n"
    "       Claude Code needs it to run shell commands on Windows. Install Git\n"
    "       for Windows, or set the variable by hand, and it will pick it up."
)


def run(args):
    try:
        return _run(args)
    except LmiError:
        # A usage or npm or config-file error, already carrying its exit code
        # and a message cli.main will print. Not ours to reinterpret.
        raise
    except Exception as exc:                    # noqa: BLE001 - deliberate
        raise LmiError(
            "unexpected failure in lmi install: %s: %s"
            % (type(exc).__name__, exc),
            EXIT_INTERNAL,
        )


def _run(args):
    cfg = build_config(args)
    say("Config: %s" % cfg.source)

    npm_exe = npm.find()
    say("npm:    %s" % npm_exe)

    # --- ask everything, change nothing ---------------------------------
    if not _agreed_to_proceed():
        say("Nothing was changed.")
        return EXIT_OK

    settings_path = settings.path()
    current = jsonfile.read(settings_path, "Claude Code settings")
    token = _ask_for_token(current)
    bash_path = _resolve_git_bash()

    # --- from here on the machine changes -------------------------------
    _configure_npm(cfg, npm_exe)
    npm.install(npm_exe, say)

    if bash_path:
        gitbash.persist(bash_path, say)

    stamp = jsonfile.timestamp()
    backups = []
    _write_settings(cfg, current, token, bash_path, settings_path, stamp, backups)
    _write_onboarding_flag(stamp, backups)

    _report(backups)
    return EXIT_OK


# --- questions ------------------------------------------------------------

def _agreed_to_proceed():
    """True unless an install already exists and the user declines to repair."""
    existing = shutil.which("claude")
    if existing is None:
        return True
    say("Claude Code is already installed at %s" % existing)
    return prompts.confirm("Repair the installation?", default=False)


def _ask_for_token(current):
    """The token to write, or None to leave whatever is there."""
    if settings.token_of(current):
        say("An auth token is already configured.")
        answer = prompts.secret(
            "Claude Code auth token (blank to keep the existing one)"
        )
    else:
        answer = prompts.secret(
            "Claude Code auth token (blank to skip and sign in later)"
        )
    return answer or None


def _resolve_git_bash():
    """The Git Bash path to record, or None. Always None off Windows."""
    if not gitbash.on_windows():
        return None
    found = gitbash.find()
    if found:
        say("Git Bash: %s" % found)
        return found
    say("Git Bash was not found in any of the usual places.")
    answer = prompts.text("Full path to bash.exe (blank to skip)")
    if gitbash.is_valid(answer):
        return answer
    if answer:
        say("That is not a bash or sh executable, or it does not exist.")
    say(GIT_BASH_MISSING % gitbash.VAR)
    return None


# --- changes --------------------------------------------------------------

def _configure_npm(cfg, npm_exe):
    if cfg.cafile:
        say("Trusting the CA in %s" % cfg.cafile)
        npm.config_set(npm_exe, "cafile", str(cfg.cafile), say)
    else:
        npm.config_set(npm_exe, "strict-ssl", "false", say)
        say(TLS_WARNING)
    npm.config_set(npm_exe, "registry", cfg.registry, say)


def _write_settings(cfg, current, token, bash_path, path, stamp, backups):
    env = dict(cfg.env)
    if token:
        env[settings.TOKEN_KEY] = token
    if bash_path:
        env[gitbash.VAR] = bash_path

    _back_up(path, stamp, "Claude Code settings", backups)
    merged = settings.merge(current, env, cfg.marketplaces)
    # 0600 whenever the file ends up holding a credential. On Windows os.chmod
    # only toggles the read-only bit and grants no protection - lmi does not
    # claim otherwise there.
    mode = 0o600 if settings.token_of(merged) else None
    jsonfile.write(path, merged, "Claude Code settings", mode=mode)
    say("Wrote %s" % path)


def _write_onboarding_flag(stamp, backups):
    path = claude_json.path()
    doc = jsonfile.read(path, "Claude Code state")
    if not claude_json.needs_update(doc):
        say("Onboarding is already marked complete.")
        return
    _back_up(path, stamp, "Claude Code state", backups)
    jsonfile.write(path, claude_json.mark_complete(doc), "Claude Code state")
    say("Marked onboarding complete in %s" % path)


def _back_up(path, stamp, what, backups):
    made = jsonfile.backup(path, stamp, what)
    if made:
        backups.append(made)


# --- reporting ------------------------------------------------------------

def _report(backups):
    say("")
    if backups:
        say("Your previous configuration was saved:")
        for path in backups:
            say("  %s" % path)
        say("These are never deleted; remove them yourself when you are happy.")
    found = shutil.which("claude")
    if found:
        say("Claude Code is installed: %s" % found)
    else:
        say(NO_CLAUDE_ON_PATH)


def say(message=""):
    """Console output.

    Deliberately not core.log.Logger: this command writes no log file, and a
    Logger needs a path. `print` is the whole requirement.
    """
    print(message)
```

- [ ] **Step 4: Replace the package `__init__.py`**

```python
from .config import add_arguments  # noqa: F401
from .runner import run  # noqa: F401

NAME = "install"
HELP = "Install and configure the Claude Code CLI"
```

- [ ] **Step 5: Register the command**

`lmi/commands/__init__.py` — replace the import and the list:

```python
from . import install, schedule

COMMANDS = [install, schedule]
```

- [ ] **Step 6: Update the registration tripwire**

In `tests/test_cli.py`, replace `test_schedule_is_registered` (lines 22-24):

```python
def test_the_registry_lists_every_command_in_help_order():
    """The intended tripwire: adding a command must update this list.

    Registry order is --help order, and `install` comes first because that is
    the order a user meets the commands - install the tool, then schedule it.
    """
    from lmi.commands import COMMANDS
    assert [c.NAME for c in COMMANDS] == ["install", "schedule"]
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python3 -m pytest tests/ -q`
Expected: all pass, 261 total.

Then confirm the command is really wired up:

```bash
python3 -m lmi install --help
python3 -m lmi install codex ; echo "expect 2, got $?"
```

- [ ] **Step 8: Commit**

```bash
git add lmi/commands/ tests/
git commit -m "feat(install): orchestrate the flow and register the command

Every question is asked before anything changes, and npm runs before any
Claude config file is touched - a machine carrying the site's settings
with no binary looks provisioned and is not."
```

---

### Task 8: Documentation

**Files:**
- Create: `examples/lmi.json`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Create: `tests/test_docs.py`

- [ ] **Step 1: Write the failing test**

`tests/test_docs.py`:

```python
"""Documentation facts that go stale silently.

The example config is the thing users copy. If it drifts from what the
validator accepts, every new site starts with a broken file and a usage error.
"""

import json
from pathlib import Path

from lmi.commands.install import claude_json, config, gitbash, settings

REPO = Path(__file__).resolve().parent.parent


class Args:
    def __init__(self, config, target="claude"):
        self.config = config
        self.target = target


def test_the_example_config_is_accepted_by_the_validator(tmp_path):
    example = REPO / "examples" / "lmi.json"
    doc = json.loads(example.read_text(encoding="utf-8"))
    # cafile has to point somewhere real for validation, so rewrite just that.
    pem = tmp_path / "ca.pem"
    pem.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    doc["claude"]["cafile"] = str(pem)
    staged = tmp_path / "lmi.json"
    with open(str(staged), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)

    cfg = config.build_config(Args(str(staged)))
    assert cfg.registry
    assert cfg.marketplaces


def test_the_example_documents_every_supported_key():
    doc = json.loads((REPO / "examples" / "lmi.json").read_text(encoding="utf-8"))
    assert set(doc["claude"]) == {"registry", "cafile", "marketplaces", "env"}


def test_the_readme_names_the_silent_keys():
    """Anyone editing these by hand needs the exact spelling in front of them."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for key in (claude_json.ONBOARDING_KEY, settings.MARKETPLACES_KEY,
                gitbash.VAR, "lmi install claude"):
        assert key in readme, "README.md must document %s" % key


def test_claude_md_scopes_the_keypress_invariant_to_schedule():
    """MANDATORY. Invariant 3 was global and `lmi install` contradicts it.

    Left unscoped it reads as a rule this command breaks, which invites someone
    to "fix" the command by removing its prompts.
    """
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    start = text.index("Nothing may ever wait for a keypress")
    assert "schedule" in text[start - 400:start + 400]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_docs.py -q`
Expected: FAIL — `examples/lmi.json` does not exist.

- [ ] **Step 3: Write `examples/lmi.json`**

```json
{
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

- [ ] **Step 4: Add the README section**

Append a `## lmi install claude` section to `README.md`, after the `lmi schedule` material. It must contain, at minimum:

- the one-line purpose and the fact that it is interactive and needs a terminal;
- the config file, its four search paths in order, and the table of the four keys with `registry` marked required;
- that `env` defaults to the 256K profile and that values are strings;
- what each of the three prompts asks, and that blank answers are meaningful (keep existing token; skip Git Bash);
- the exit codes table from spec §11;
- the sudo / `npm config set prefix` advice and the "open a new terminal" advice;
- that backups are `<name>.bk_<YYYYmmdd-HHMMSS>`, are reported at the end, and are never pruned;
- the exact spellings `hasCompletedOnboarding`, `extraKnownMarketplaces`, `CLAUDE_CODE_GIT_BASH_PATH`;
- that Git Bash handling is Windows-only;
- **the real-run checklist**, since no test can cover these:
  1. Artifactory actually serves `@anthropic-ai/claude-code` and its dependency tree.
  2. `--global` behaves as documented on the site's Node layout (or the fallback fires).
  3. `extraKnownMarketplaces` in user scope really registers the marketplace — check `/plugin marketplace list` in `claude`.
  4. A Windows box with Git in a non-default location ends up with a working Bash tool.

- [ ] **Step 5: Update `CLAUDE.md`**

Three edits:

1. **Section 1, invariant 3** — re-scope it. Replace "Nothing may ever wait for a keypress." with:

```
3. **`lmi schedule` may never wait for a keypress.** The prompt is fed on
   stdin; every wait is a `time.sleep`. This is a property of the unattended
   runner, not of `lmi`: `lmi install` is interactive by design and asks
   before it changes anything. It has no `--yes`, and guards only against
   *hanging* - with no terminal it exits 2 rather than waiting forever.
```

2. **Section 2, architecture map** — add the new package under `lmi/commands/`:

```
lmi/commands/install/       `lmi install claude`, as a self-contained package
  config.py                 arguments, config-file discovery, the frozen Config
  prompts.py                every question, and the no-terminal guard
  npm.py                    locating npm, one npm command, the --global fallback
  jsonfile.py               read / back up / atomically write a JSON document
  settings.py               what goes into ~/.claude/settings.json
  claude_json.py            what goes into ~/.claude.json
  gitbash.py                Windows Git Bash discovery and the env var
  runner.py                 the flow
  exit_codes.py             this command's codes (1, 3, 4)
```

3. **Section 3, behaviours that must not regress** — append these, continuing the numbering:

```
13. **The onboarding key is `hasCompletedOnboarding`, lowercase `b`.**
    Verified in the 2.1.222 binary. **Silent:** the natural spelling
    `hasCompletedOnBoarding` writes cleanly, parses cleanly and does nothing -
    the user meets the onboarding flow the command promised to skip, and the
    run reports success.
14. **`npm install -g` is never retried without `-g`.** `npm config set`
    retrying without `--global` is a correct fallback to `~/.npmrc`. The same
    move on the install is not: **silent:** it installs into `./node_modules`
    of the current directory, creates no `claude`, and exits 0.
15. **A failing npm step must touch no Claude config file.** **Silent:** the
    machine ends up with the 256K profile, the marketplaces and onboarding
    skipped, but no binary - it looks provisioned and is not.
16. **Declining the repair question changes nothing at all.** No npm command,
    no backup, no write. Exit 0, because the user answered rather than erred.
17. **Git Bash work is Windows-only.** `CLAUDE_CODE_GIT_BASH_PATH` is resolved
    through `path/win32` and is never read elsewhere. Candidates are validated
    the way Claude Code validates - basename in bash/sh, and the file exists -
    because a path it rejects looks configured and is not.
18. **`settings.json` `env` values are strings.** A JSON number is silently
    the wrong type, so the 256K profile does not apply.
19. **An unparseable `settings.json` or `.claude.json` is refused, not
    overwritten.** Treating it as `{}` would discard everything the user had.
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/ -q`
Expected: all pass, 265 total.

- [ ] **Step 7: Commit**

```bash
git add examples/lmi.json README.md CLAUDE.md tests/test_docs.py
git commit -m "docs(install): README section, example config, CLAUDE.md guards

Re-scopes invariant 3 to lmi schedule: lmi install is interactive by
design, and left unscoped the invariant reads as a rule this command
breaks - inviting someone to remove its prompts."
```

---

## Self-Review

**Spec coverage** — every section maps to a task:

| Spec | Task |
|---|---|
| §1 non-goals (no mirror, no npm bootstrap, no `--version`/`--dry-run`/`--yes`) | Enforced by omission; `--yes` absence pinned by Task 2 |
| §2 verified facts | Tasks 1, 5, 6 constants + MANDATORY tests |
| §3 package structure | Tasks 1–7 (with the documented `runner.py` deviation) |
| §4 config discovery, shape, validation | Task 1 |
| §5 step order | Task 7 |
| §6.1 interactive + no-terminal guard | Task 2 |
| §6.2 repair + backup policy | Task 7 |
| §6.3 token, blank-keeps-existing, mode 600 | Tasks 5, 7 |
| §6.4 `--global` fallback, no `-g` retry, no sudo | Task 3 |
| §6.5 cafile vs strict-ssl + warning | Tasks 1, 7 |
| §6.6 PATH check exits 0 with a warning | Task 7 |
| §7 settings.json merge semantics | Task 5 |
| §8 Git Bash discovery and persistence | Task 6 |
| §9 `.claude.json` onboarding | Task 5 |
| §10 backups, naming, atomicity, reporting | Tasks 4, 7 |
| §11 exit codes | Task 1 (`exit_codes.py`), asserted throughout |
| §12 testing, incl. all seven MANDATORY items | Tasks 1–7 |
| §13 documentation | Task 8 |

**14 tests carry `MANDATORY`.** All seven the spec §12 named are present: onboarding spelling (T5), failed npm touches nothing (T7), no `-g` retry (T3), unparseable settings not overwritten (T4), declining repair changes nothing (T7), Git Bash basename validation (T6), no Git Bash work off Windows (T6).

Seven more were added, each meeting the same bar — the failure it pins reports success while being wrong: `--config` not falling through to a different registry (T1), non-string `env` values (T1), `secret()` not falling back to `input()` (T2), EOF failing fast instead of hanging (T2), `shell=True` absent (T3), the `extraKnownMarketplaces` spelling (T5), and `CLAUDE.md` keeping invariant 3 scoped to `schedule` (T8).

Verify the count with `grep -c 'MANDATORY\.' ` on this file before trusting any summary of it.

**Placeholder scan:** clean. Every code step carries real code. Task 8 Step 4 is a content checklist rather than literal prose — deliberate, because the README's existing voice should be matched by whoever writes it, and `tests/test_docs.py` mechanically enforces the parts that matter.

**Type consistency:** `say` is `Callable[[str], None]` everywhere (`npm.config_set`, `npm.install`, `gitbash.persist`, `runner.say`). `jsonfile.read/backup/write` take `(path, ..., what)` consistently. `settings.merge(doc, env, marketplaces)` and `claude_json.mark_complete(doc)` both return the mutated doc. `gitbash.on_windows` is patched by name in three test modules and defined once. `config.Config` field names match every consumer in `runner.py`.

**Test count check:** baseline 135 → 155 → 174 → 183 → 202 → 222 → 244 → 261 → 265.
