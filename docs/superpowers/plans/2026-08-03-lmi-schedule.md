# lmi schedule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `lmi`, an installable Python CLI, and its first command `lmi schedule`, which runs the Claude Code CLI unattended in a foreground loop — replacing `run-claude.bat`.

**Architecture:** A vertical-slice package. `lmi/cli.py` does nothing but parse and dispatch; every command is a self-contained package under `lmi/commands/<name>/` registered by one line in `lmi/commands/__init__.py`. Only genuinely command-agnostic code lives in `lmi/core/`. Stdlib only at runtime.

**Tech Stack:** Python 3.9+, `argparse`, `subprocess`, `fcntl`/`msvcrt`, `pytest` as a dev extra.

**Spec:** `docs/superpowers/specs/2026-08-03-lmi-schedule-design.md`

## Global Constraints

- **Python 3.9 or newer.** No `match`, no `tomllib`, no `X | Y` type unions at runtime, no `dict[str, int]` builtin generics in annotations evaluated at runtime (use `typing.Optional`, `typing.List` or `from __future__ import annotations`).
- **Stdlib only at runtime.** `pytest` is a dev extra and must never be imported by `lmi/`.
- **Exit codes:** `0` success and `2` usage error are **global** to every command. `lmi schedule` additionally defines `1` (at least one claude call failed) and `3` (another run holds the lock). No other command may redefine `0` or `2`.
- **Three invariants:** iterations never overlap; a failing claude call never fails the runner; nothing ever waits for a keypress.
- **`subprocess.run` is always called with a list argv and never `shell=True`.**
- **`check=False`** (the default) on the claude call — a non-zero exit must return, not raise.
- **All files written with `encoding="utf-8", newline="\n"`.**
- **`core/` discipline:** a module earns a place in `lmi/core/` only when it has a second consumer. `paths.py` stays inside `commands/schedule/`.
- **No new runner features.** No per-iteration timeout, no quota retry, no log rotation.
- **Default paths keep the `run-claude-` prefix:** state `run-claude-state.md`, log `run-claude-<timestamp>.log`, lock `run-claude.lock`, so state files stay interchangeable with the `.bat` during the transition.
- **The prompt/state text names the tool as `lmi schedule`**, not `run-claude.bat`. That is the only permitted difference from the `.bat`'s literal text.
- **No real `claude` may be invoked by tests.** Tests put a fake executable on a temporary `PATH`. A real `claude` exists on this machine and would spend real quota.
- **macOS and Windows are unverified** during implementation. Write the `msvcrt` branch from documentation; do not claim it is tested.

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Create. Package metadata, `lmi` console script, dev extra. |
| `lmi/__init__.py` | Create. `__version__` only. |
| `lmi/__main__.py` | Create. `python -m lmi` entry. |
| `lmi/cli.py` | Create. Top-level parser, registry walk, dispatch, `LmiError` → exit code. Nothing else, ever. |
| `lmi/core/errors.py` | Create. `LmiError`, `EXIT_OK`, `EXIT_USAGE`. Global codes only. |
| `lmi/core/log.py` | Create. `Logger` writing one line to console and to the log file. |
| `lmi/core/lock.py` | Create. `single_instance_lock(path)` context manager, `fcntl`/`msvcrt`. |
| `lmi/commands/__init__.py` | Create. `COMMANDS` list, one entry per command. |
| `lmi/commands/schedule/__init__.py` | Create. `NAME`, `HELP`, `add_arguments`, `run`. |
| `lmi/commands/schedule/exit_codes.py` | Create. `EXIT_CALL_FAILED = 1`, `EXIT_LOCKED = 3`. |
| `lmi/commands/schedule/config.py` | Create. `add_arguments`, `Config` dataclass, `build_config`. |
| `lmi/commands/schedule/paths.py` | Create. `resolve_log`, `resolve_state`, directory creation. |
| `lmi/commands/schedule/state.py` | Create. Template, backup/resume, `check_complete`. |
| `lmi/commands/schedule/prompt.py` | Create. `read_prompt_source`, `compose_prompt`. |
| `lmi/commands/schedule/runner.py` | Create. The loop, the claude invocation, quota detection. |
| `tests/conftest.py` | Create. `fake_claude` fixture: a stub on a temporary PATH. |
| `tests/test_cli.py` | Create. Skeleton and dispatch tests. |
| `tests/commands/schedule/test_*.py` | Create. Per-module tests. |
| `README.md` | Modify. `lmi` install and usage section. |

---

## Task 1: Package skeleton, CLI dispatch and registry

Delivers an installable `lmi` whose `--help` lists a `schedule` subcommand that parses nothing yet.

**Files:**
- Create: `pyproject.toml`, `lmi/__init__.py`, `lmi/__main__.py`, `lmi/cli.py`, `lmi/core/__init__.py`, `lmi/core/errors.py`, `lmi/commands/__init__.py`, `lmi/commands/schedule/__init__.py`, `lmi/commands/schedule/exit_codes.py`, `tests/__init__.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `lmi.cli.main(argv=None) -> int`; `lmi.core.errors.LmiError(message, code=EXIT_USAGE)` with attribute `.code`; `EXIT_OK = 0`, `EXIT_USAGE = 2`; the command contract `NAME: str`, `HELP: str`, `add_arguments(parser) -> None`, `run(args) -> int`; `lmi.commands.COMMANDS` as a list of command modules.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli.py`:

```python
import pytest
from lmi.cli import main


def test_no_command_prints_help_and_exits_2(capsys):
    assert main([]) == 2
    assert "schedule" in capsys.readouterr().err


def test_version_flag_exits_0():
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_unknown_command_exits_2():
    with pytest.raises(SystemExit) as exc:
        main(["nosuchcommand"])
    assert exc.value.code == 2


def test_schedule_is_registered():
    from lmi.commands import COMMANDS
    assert [c.NAME for c in COMMANDS] == ["schedule"]


def test_every_command_satisfies_the_contract():
    from lmi.commands import COMMANDS
    for c in COMMANDS:
        assert isinstance(c.NAME, str) and c.NAME
        assert isinstance(c.HELP, str) and c.HELP
        assert callable(c.add_arguments)
        assert callable(c.run)


def test_lmi_error_carries_its_exit_code():
    from lmi.core.errors import LmiError, EXIT_USAGE
    assert LmiError("boom").code == EXIT_USAGE
    assert LmiError("boom", 3).code == 3
```

- [ ] **Step 2: Run and verify they fail**

Run: `python -m pytest tests/test_cli.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'lmi'`.

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "lmi"
version = "0.1.0"
description = "Helper CLI for the Claude Code CLI"
requires-python = ">=3.9"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=7"]

[project.scripts]
lmi = "lmi.cli:main"

[tool.setuptools.packages.find]
include = ["lmi*"]
```

- [ ] **Step 4: Write the core error module**

`lmi/core/errors.py`:

```python
"""Errors and the exit codes that are global to every lmi command.

Only 0 and 2 are global. A command's own codes live in that command's
package - see lmi/commands/schedule/exit_codes.py - so two commands can
never disagree about what 2 means.
"""

EXIT_OK = 0
EXIT_USAGE = 2


class LmiError(Exception):
    """An error with a chosen exit code. cli.main turns this into a status."""

    def __init__(self, message, code=EXIT_USAGE):
        super().__init__(message)
        self.code = code
```

`lmi/core/__init__.py`: empty.

- [ ] **Step 5: Write the CLI and the registry**

`lmi/__init__.py`:

```python
__version__ = "0.1.0"
```

`lmi/cli.py`:

```python
"""Top-level parser and dispatch.

This module deliberately knows nothing about any command beyond the four
names in the command contract (NAME, HELP, add_arguments, run). Adding a
command must never require editing this file.
"""

import argparse
import sys

from . import __version__
from .commands import COMMANDS
from .core.errors import EXIT_USAGE, LmiError


def build_parser():
    parser = argparse.ArgumentParser(
        prog="lmi", description="Helper CLI for the Claude Code CLI."
    )
    parser.add_argument("--version", action="version", version="lmi " + __version__)
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    for command in COMMANDS:
        sp = sub.add_parser(command.NAME, help=command.HELP, description=command.HELP)
        command.add_arguments(sp)
        sp.set_defaults(_run=command.run)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    run = getattr(args, "_run", None)
    if run is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        return run(args)
    except LmiError as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
```

`lmi/__main__.py`:

```python
import sys

from .cli import main

sys.exit(main())
```

`lmi/commands/__init__.py`:

```python
"""The command registry.

One import and one list entry per command. Deliberately explicit rather
than pkgutil discovery: discovery makes --help ordering non-deterministic,
imports every command on every startup, and turns a typo into a silently
missing command.
"""

from . import schedule

COMMANDS = [schedule]
```

- [ ] **Step 6: Write the schedule command stub**

`lmi/commands/schedule/exit_codes.py`:

```python
"""Exit codes specific to `lmi schedule`.

0 and 2 are global and live in lmi.core.errors. Everything else is this
command's own, so another command can define its own 1 and 3 freely.
"""

EXIT_CALL_FAILED = 1
EXIT_LOCKED = 3
EXIT_INTERNAL = 4
```

`lmi/commands/schedule/__init__.py`:

```python
NAME = "schedule"
HELP = "Run Claude Code unattended, looping in the foreground"


def add_arguments(parser):
    return None


def run(args):
    return 0
```

- [ ] **Step 7: Install and run the tests**

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/ -v
lmi --help
lmi --version
```
Expected: 6 tests pass; `lmi --help` lists `schedule`; `lmi --version` prints `lmi 0.1.0`.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml lmi tests
git commit -s -m "feat: add the lmi package skeleton and command registry"
```

---

## Task 2: `lmi schedule` arguments and validation

**Files:**
- Create: `lmi/commands/schedule/config.py`, `tests/commands/__init__.py`, `tests/commands/schedule/__init__.py`, `tests/commands/schedule/test_config.py`
- Modify: `lmi/commands/schedule/__init__.py`

**Interfaces:**
- Consumes: `LmiError`, `EXIT_USAGE`.
- Produces: `add_arguments(parser)`; `Config` dataclass with fields `prompt_text: Optional[str]`, `prompt_file: Optional[Path]`, `at: Optional[datetime]`, `interval_min: int`, `max_runs: int`, `work_dir: Path`, `user_flags: List[str]`, `log_arg: Optional[str]`, `state_arg: Optional[str]`, `resume: bool`; `build_config(args) -> Config`.

- [ ] **Step 1: Write the failing tests**

Create `tests/commands/schedule/test_config.py`:

```python
from datetime import datetime
from pathlib import Path

import pytest

from lmi.cli import main
from lmi.commands.schedule.config import build_config
from lmi.core.errors import LmiError


def _args(**kw):
    """A Namespace shaped like argparse produces, with defaults."""
    import argparse
    base = dict(prompt="do a thing", at=None, interval=None, count=None,
                workdir=None, flags="", log=None, state=None, resume=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_interval_without_count_is_a_usage_error():
    with pytest.raises(LmiError) as exc:
        build_config(_args(interval=5))
    assert exc.value.code == 2
    assert "-c" in str(exc.value)


def test_count_without_interval_is_a_usage_error():
    with pytest.raises(LmiError) as exc:
        build_config(_args(count=3))
    assert exc.value.code == 2
    assert "-i" in str(exc.value)


def test_interval_zero_counts_as_given():
    """-i 0 must not be mistaken for "not supplied"."""
    with pytest.raises(LmiError):
        build_config(_args(interval=0))
    cfg = build_config(_args(interval=0, count=2))
    assert cfg.interval_min == 0 and cfg.max_runs == 2


def test_count_must_be_positive():
    with pytest.raises(LmiError) as exc:
        build_config(_args(interval=1, count=0))
    assert exc.value.code == 2


def test_leading_zero_count_is_decimal_not_octal():
    """argparse type=int already does this; pin it so nobody 'fixes' it."""
    assert build_config(_args(interval=0, count=int("008"))).max_runs == 8


def test_no_interval_or_count_means_a_single_run():
    cfg = build_config(_args())
    assert cfg.max_runs == 1 and cfg.interval_min == 0


def test_malformed_at_is_a_usage_error():
    with pytest.raises(LmiError) as exc:
        build_config(_args(at="05/08/2026 22:00"))
    assert exc.value.code == 2
    assert "YYYY-MM-DD HH:MM" in str(exc.value)


def test_well_formed_at_is_parsed():
    cfg = build_config(_args(at="2026-08-05 22:00"))
    assert cfg.at == datetime(2026, 8, 5, 22, 0)


def test_missing_workdir_is_a_usage_error(tmp_path):
    with pytest.raises(LmiError) as exc:
        build_config(_args(workdir=str(tmp_path / "nope")))
    assert exc.value.code == 2


def test_prompt_that_is_a_directory_is_a_usage_error(tmp_path):
    with pytest.raises(LmiError) as exc:
        build_config(_args(prompt=str(tmp_path)))
    assert exc.value.code == 2
    assert "directory" in str(exc.value)


def test_prompt_file_is_detected(tmp_path):
    p = tmp_path / "task.md"
    p.write_text("from a file\n", encoding="utf-8")
    cfg = build_config(_args(prompt=str(p)))
    assert cfg.prompt_file == p.resolve() and cfg.prompt_text is None


def test_prompt_text_is_used_when_not_a_path():
    cfg = build_config(_args(prompt="just some words"))
    assert cfg.prompt_text == "just some words" and cfg.prompt_file is None


def test_flags_are_split_respecting_quotes():
    cfg = build_config(_args(flags='--verbose --model "sonnet 5"'))
    assert cfg.user_flags == ["--verbose", "--model", "sonnet 5"]


def test_non_numeric_interval_exits_2_via_argparse():
    with pytest.raises(SystemExit) as exc:
        main(["schedule", "x", "-i", "abc", "-c", "2"])
    assert exc.value.code == 2


def test_two_positional_prompts_exits_2_via_argparse():
    with pytest.raises(SystemExit) as exc:
        main(["schedule", "one", "two"])
    assert exc.value.code == 2


def test_unquoted_two_token_at_is_rejected():
    """A deliberate deviation from the .bat, which tolerates this. Supporting
    it needs nargs="+" on -t, which is greedy and would swallow the prompt in
    `-t "2026-08-05 22:00" "my prompt"`. A silent mis-parse is worse than
    requiring a quote, so the two-token form must fail loudly."""
    with pytest.raises(SystemExit) as exc:
        main(["schedule", "x", "-t", "2026-08-05", "22:00"])
    assert exc.value.code == 2
```

- [ ] **Step 2: Run and verify they fail**

Run: `python -m pytest tests/commands/schedule/test_config.py -v`
Expected: `ModuleNotFoundError: No module named 'lmi.commands.schedule.config'`.

- [ ] **Step 3: Implement `config.py`**

```python
"""Arguments and validation for `lmi schedule`.

Validation lives with the command, not in cli.py, so that cli.py stays
pure parse-and-dispatch as commands accumulate.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import shlex

from ...core.errors import EXIT_USAGE, LmiError

AT_FORMAT = "%Y-%m-%d %H:%M"


def add_arguments(parser):
    parser.add_argument(
        "prompt",
        help="the prompt text, or the path of a UTF-8 file containing it",
    )
    parser.add_argument(
        "-t", dest="at", metavar="WHEN",
        help='start at this time, "YYYY-MM-DD HH:MM" (quote it). Default: now',
    )
    parser.add_argument(
        "-i", dest="interval", type=int, metavar="MINUTES",
        help="minutes between iterations; requires -c. 0 runs them back to back",
    )
    parser.add_argument(
        "-c", dest="count", type=int, metavar="N",
        help="number of iterations; requires -i. Must be greater than 0",
    )
    parser.add_argument(
        "-d", dest="workdir", metavar="DIR",
        help="working directory for claude. Default: the current directory",
    )
    parser.add_argument(
        "-f", dest="flags", default="", metavar="FLAGS",
        help="extra claude flags, appended after --allowed-tools=Edit,Write",
    )
    parser.add_argument(
        "-l", dest="log", metavar="PATH",
        help="log folder, or a full log file path",
    )
    parser.add_argument(
        "-s", dest="state", metavar="FILE",
        help="state file. Default: <workdir>/run-claude-state.md",
    )
    parser.add_argument(
        "-r", dest="resume", action="store_true",
        help="resume: keep the existing state file instead of backing it up",
    )


@dataclass
class Config:
    prompt_text: Optional[str]
    prompt_file: Optional[Path]
    at: Optional[datetime]
    interval_min: int
    max_runs: int
    work_dir: Path
    user_flags: List[str] = field(default_factory=list)
    log_arg: Optional[str] = None
    state_arg: Optional[str] = None
    resume: bool = False


def build_config(args):
    # -i and -c are mutually required. argparse gives None when a flag is
    # absent, so `-i 0` is distinguishable from "-i not given" with no
    # sentinel variable - unlike the .bat, which needed INTERVAL_GIVEN.
    if args.interval is not None and args.count is None:
        raise LmiError(
            "-i requires -c: an unattended loop must have a stop condition",
            EXIT_USAGE,
        )
    if args.count is not None and args.interval is None:
        raise LmiError(
            "-c requires -i: give the interval between iterations too", EXIT_USAGE
        )

    if args.interval is None:
        interval_min, max_runs = 0, 1
    else:
        interval_min, max_runs = args.interval, args.count
        if max_runs <= 0:
            raise LmiError("-c must be greater than 0", EXIT_USAGE)
        if interval_min < 0:
            raise LmiError("-i must not be negative", EXIT_USAGE)

    at = None
    if args.at is not None:
        try:
            at = datetime.strptime(args.at, AT_FORMAT)
        except ValueError:
            raise LmiError(
                '-t must look like YYYY-MM-DD HH:MM (quoted), got: ' + args.at,
                EXIT_USAGE,
            )

    if args.workdir is None:
        work_dir = Path.cwd()
    else:
        work_dir = Path(args.workdir)
        if not work_dir.is_dir():
            raise LmiError(
                "working directory does not exist: " + str(args.workdir), EXIT_USAGE
            )
        work_dir = work_dir.resolve()

    candidate = Path(args.prompt)
    prompt_text, prompt_file = None, None
    if candidate.is_dir():
        raise LmiError(
            "the prompt argument is a directory: " + args.prompt, EXIT_USAGE
        )
    if candidate.is_file():
        prompt_file = candidate.resolve()
    else:
        prompt_text = args.prompt

    return Config(
        prompt_text=prompt_text,
        prompt_file=prompt_file,
        at=at,
        interval_min=interval_min,
        max_runs=max_runs,
        work_dir=work_dir,
        user_flags=shlex.split(args.flags) if args.flags else [],
        log_arg=args.log,
        state_arg=args.state,
        resume=args.resume,
    )
```

- [ ] **Step 4: Wire the arguments into the command**

Replace `lmi/commands/schedule/__init__.py` with:

```python
from .config import add_arguments  # noqa: F401  (re-exported as the contract)

NAME = "schedule"
HELP = "Run Claude Code unattended, looping in the foreground"


def run(args):
    # Real implementation arrives in Task 7. Returning 0 keeps `lmi schedule`
    # importable and the contract test green; nothing calls it until then.
    return 0
```

Create empty `tests/commands/__init__.py` and `tests/commands/schedule/__init__.py`.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/ -v`
Expected: 22 tests pass (6 from Task 1, 16 here).

- [ ] **Step 6: Commit**

```bash
git add lmi tests
git commit -s -m "feat: parse and validate lmi schedule arguments"
```

---

## Task 3: Log and state path resolution

**Files:**
- Create: `lmi/commands/schedule/paths.py`, `tests/commands/schedule/test_paths.py`

**Interfaces:**
- Consumes: `Config`, `LmiError`.
- Produces: `timestamp() -> str` (format `%Y%m%d-%H%M%S`); `resolve_state(cfg) -> Path` (absolute, parent created); `resolve_log(cfg, run_ts) -> Path` (absolute, parent created); `has_extension(name: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `tests/commands/schedule/test_paths.py`:

```python
from pathlib import Path

import pytest

from lmi.commands.schedule.config import Config
from lmi.commands.schedule.paths import (
    has_extension, resolve_log, resolve_state, timestamp,
)
from lmi.core.errors import LmiError

TS = "20260803-101500"


def _cfg(tmp_path, **kw):
    base = dict(prompt_text="x", prompt_file=None, at=None, interval_min=0,
                max_runs=1, work_dir=tmp_path, user_flags=[], log_arg=None,
                state_arg=None, resume=False)
    base.update(kw)
    return Config(**base)


def test_timestamp_shape():
    ts = timestamp()
    assert len(ts) == 15 and ts[8] == "-" and ts.replace("-", "").isdigit()


def test_default_state_path_is_beside_the_workdir(tmp_path):
    assert resolve_state(_cfg(tmp_path)) == tmp_path / "run-claude-state.md"


def test_state_parent_is_created_when_missing(tmp_path):
    """The .bat mkdirs a missing parent and only fails if that fails."""
    target = tmp_path / "deep" / "dir" / "st.md"
    assert resolve_state(_cfg(tmp_path, state_arg=str(target))) == target
    assert target.parent.is_dir()


def test_default_log_is_timestamped_in_the_workdir(tmp_path):
    assert resolve_log(_cfg(tmp_path), TS) == tmp_path / ("run-claude-%s.log" % TS)


def test_rule_1_existing_directory_receives_a_timestamped_log(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    assert resolve_log(_cfg(tmp_path, log_arg=str(d)), TS) == d / ("run-claude-%s.log" % TS)


def test_rule_2_trailing_separator_is_a_folder_not_yet_created(tmp_path):
    d = tmp_path / "later"
    got = resolve_log(_cfg(tmp_path, log_arg=str(d) + "/"), TS)
    assert got == d / ("run-claude-%s.log" % TS)
    assert d.is_dir()


def test_rule_3_a_basename_with_an_extension_is_the_log_file(tmp_path):
    target = tmp_path / "a" / "b" / "my.log"
    assert resolve_log(_cfg(tmp_path, log_arg=str(target)), TS) == target
    assert target.parent.is_dir()


def test_rule_4_extensionless_nonexistent_path_is_a_folder(tmp_path):
    """The trap: the .bat falls through to :rl_folder here, so this must be
    a DIRECTORY containing a timestamped log, not a file named 'newlogs'."""
    d = tmp_path / "newlogs"
    got = resolve_log(_cfg(tmp_path, log_arg=str(d)), TS)
    assert got == d / ("run-claude-%s.log" % TS)
    assert d.is_dir()


def test_dotfile_does_not_count_as_having_an_extension():
    assert has_extension(".hidden") is False
    assert has_extension("my.log") is True
    assert has_extension("plain") is False
    assert has_extension("a.b.c") is True


def test_unwritable_log_parent_is_a_clear_error(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        with pytest.raises(LmiError) as exc:
            resolve_log(_cfg(tmp_path, log_arg=str(ro / "sub" / "x.log")), TS)
        assert exc.value.code == 2
    finally:
        ro.chmod(0o700)
```

- [ ] **Step 2: Run and verify they fail**

Run: `python -m pytest tests/commands/schedule/test_paths.py -v`
Expected: `ModuleNotFoundError: No module named 'lmi.commands.schedule.paths'`.

- [ ] **Step 3: Implement `paths.py`**

```python
"""Where the log and the state file go.

The folder-versus-file rules are copied from run-claude.bat's :resolve_log
and are load-bearing: an extension-less path that does not exist yet is a
FOLDER, not a log file. Getting rule 4 wrong makes `-l some/new/logdir`
create a file called logdir instead of a directory.
"""

from datetime import datetime
from pathlib import Path

from ...core.errors import EXIT_USAGE, LmiError

TS_FORMAT = "%Y%m%d-%H%M%S"
STATE_NAME = "run-claude-state.md"
LOG_PREFIX = "run-claude-"


def timestamp():
    return datetime.now().strftime(TS_FORMAT)


def has_extension(name):
    """Mirror cmd's %%~xF: a dot after the first character. '.hidden' has none."""
    return "." in name[1:]


def _ensure_parent(path, what):
    # The .bat attempts the mkdir and only fails if the directory is still
    # missing afterwards; a missing parent is not itself an error.
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if not path.parent.is_dir():
        raise LmiError(
            "the folder for the %s does not exist and could not be created: %s"
            % (what, path),
            EXIT_USAGE,
        )
    return path


def resolve_state(cfg):
    raw = cfg.state_arg or str(cfg.work_dir / STATE_NAME)
    return _ensure_parent(Path(raw).expanduser().absolute(), "state file")


def resolve_log(cfg, run_ts):
    name = LOG_PREFIX + run_ts + ".log"
    if cfg.log_arg is None:
        return _ensure_parent(cfg.work_dir / name, "log file")

    raw = cfg.log_arg
    trailing = raw.endswith("/") or raw.endswith("\\")
    path = Path(raw).expanduser().absolute()

    # Order matches run-claude.bat's :resolve_log exactly.
    if path.is_dir():                       # 1 existing directory
        return _ensure_parent(path / name, "log file")
    if trailing:                            # 2 folder, not yet created
        return _ensure_parent(path / name, "log file")
    if has_extension(path.name):            # 3 the log file itself
        return _ensure_parent(path, "log file")
    return _ensure_parent(path / name, "log file")   # 4 otherwise: folder
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/ -v`
Expected: 32 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lmi tests
git commit -s -m "feat: resolve the log and state paths, creating parents"
```

---

## Task 4: Logging

**Files:**
- Create: `lmi/core/log.py`, `tests/test_log.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Logger(path: Path)` with `.line(msg="")`, `.warn(msg)`, `.error(msg)`, `.quota(msg)`, and `.path`. Every method writes one line to stdout and appends the same line to the log file.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_log.py`:

```python
from lmi.core.log import Logger


def test_writes_to_console_and_file(tmp_path, capsys):
    log = Logger(tmp_path / "run.log")
    log.line("hello")
    assert capsys.readouterr().out == "hello\n"
    assert (tmp_path / "run.log").read_text(encoding="utf-8") == "hello\n"


def test_tags(tmp_path, capsys):
    log = Logger(tmp_path / "run.log")
    log.warn("careful")
    log.error("broken")
    log.quota("limits")
    out = capsys.readouterr().out
    assert "[WARN] careful" in out
    assert "[ERROR] broken" in out
    assert "[QUOTA] limits" in out
    assert (tmp_path / "run.log").read_text(encoding="utf-8").count("[") == 3


def test_blank_line(tmp_path, capsys):
    log = Logger(tmp_path / "run.log")
    log.line()
    assert capsys.readouterr().out == "\n"


def test_non_ascii_survives_a_round_trip(tmp_path):
    log = Logger(tmp_path / "run.log")
    log.line("שלום עולם")
    assert "שלום עולם" in (tmp_path / "run.log").read_text(encoding="utf-8")


def test_appends_rather_than_truncating(tmp_path):
    log = Logger(tmp_path / "run.log")
    log.line("first")
    Logger(tmp_path / "run.log").line("second")
    body = (tmp_path / "run.log").read_text(encoding="utf-8")
    assert body == "first\nsecond\n"
```

- [ ] **Step 2: Run and verify they fail**

Run: `python -m pytest tests/test_log.py -v`
Expected: `ModuleNotFoundError: No module named 'lmi.core.log'`.

- [ ] **Step 3: Implement `log.py`**

```python
"""One line to the console and to the log file.

Format matches run-claude.bat: plain lines, no per-line timestamps, and the
same [WARN] / [ERROR] / [QUOTA] tags, so existing logs stay comparable.
"""


class Logger:
    def __init__(self, path):
        self.path = path

    def line(self, msg=""):
        print(msg)
        with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(msg + "\n")

    def warn(self, msg):
        self.line("[WARN] " + msg)

    def error(self, msg):
        self.line("[ERROR] " + msg)

    def quota(self, msg):
        self.line("[QUOTA] " + msg)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/ -v`
Expected: 37 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lmi tests
git commit -s -m "feat: add the console-and-file logger"
```

---

## Task 5: State file lifecycle

Contains one of the two mandatory tests: the landmine-14 prose fixture.

**Files:**
- Create: `lmi/commands/schedule/state.py`, `tests/commands/schedule/test_state.py`

**Interfaces:**
- Consumes: `Logger`, `LmiError`.
- Produces: `STATE_TEMPLATE` (a format string with one `{now}` field); `write_template(path, now_str)`; `prepare(path, resume: bool, run_ts: str, log) -> None`; `check_complete(path) -> bool`; `COMPLETE_RE`.

- [ ] **Step 1: Write the failing tests**

Create `tests/commands/schedule/test_state.py`:

```python
from pathlib import Path

import pytest

from lmi.commands.schedule.state import (
    check_complete, prepare, write_template,
)
from lmi.core.errors import LmiError
from lmi.core.log import Logger

TS = "20260803-101500"


def _log(tmp_path):
    return Logger(tmp_path / "run.log")


# --- check_complete: landmine 14 -----------------------------------------

def test_complete_on_line_one_is_complete(tmp_path):
    p = tmp_path / "s.md"
    p.write_text("TASK_STATUS: COMPLETE\n\n## Completed\n", encoding="utf-8")
    assert check_complete(p) is True


def test_prose_mentioning_complete_lower_down_is_NOT_complete(tmp_path):
    """MANDATORY. Landmine 14: real claude restates the protocol sentence
    inside the state file. A whole-file search matches that prose and stops
    the loop after one iteration while reporting success - silently
    abandoning most of the work. Widening this check must turn this red."""
    p = tmp_path / "s.md"
    p.write_text(
        "TASK_STATUS: IN_PROGRESS\n\n## Goal\n\n"
        "Only after step 5 may the first line become TASK_STATUS: COMPLETE.\n",
        encoding="utf-8",
    )
    assert check_complete(p) is False


def test_utf8_bom_before_complete_still_counts(tmp_path):
    p = tmp_path / "s.md"
    p.write_bytes(b"\xef\xbb\xbfTASK_STATUS: COMPLETE\n")
    assert check_complete(p) is True


def test_leading_whitespace_and_tight_colon(tmp_path):
    p = tmp_path / "s.md"
    p.write_text("   TASK_STATUS:COMPLETE\n", encoding="utf-8")
    assert check_complete(p) is True


def test_trailing_punctuation_counts_word_boundary(tmp_path):
    """The .bat's PowerShell regex uses \\b, so a trailing period counts."""
    p = tmp_path / "s.md"
    p.write_text("TASK_STATUS: COMPLETE.\n", encoding="utf-8")
    assert check_complete(p) is True


def test_completed_does_not_count(tmp_path):
    p = tmp_path / "s.md"
    p.write_text("TASK_STATUS: COMPLETED\n", encoding="utf-8")
    assert check_complete(p) is False


def test_missing_or_empty_file_is_not_complete(tmp_path):
    assert check_complete(tmp_path / "absent.md") is False
    (tmp_path / "empty.md").write_text("", encoding="utf-8")
    assert check_complete(tmp_path / "empty.md") is False


# --- template and prepare ------------------------------------------------

def test_template_starts_in_progress_and_names_lmi(tmp_path):
    p = tmp_path / "s.md"
    write_template(p, "2026-08-03 10:15:00")
    body = p.read_text(encoding="utf-8")
    assert body.splitlines()[0] == "TASK_STATUS: IN_PROGRESS"
    assert "lmi schedule" in body
    assert "run-claude.bat" not in body
    for heading in ("## Goal", "## Completed", "## In progress",
                    "## Next steps", "## Notes and blockers"):
        assert heading in body


def test_unwritable_state_path_is_a_clear_error(tmp_path):
    """MANDATORY. The .bat logs "created new" even when the write failed,
    so the loop then repeats iteration 1 forever while reporting success.
    That silent shape is landmine 13; lmi must fail loudly instead."""
    with pytest.raises(LmiError) as exc:
        write_template(tmp_path, "2026-08-03 10:15:00")  # a directory
    assert exc.value.code == 2


def test_prepare_creates_a_fresh_file_when_none_exists(tmp_path):
    p = tmp_path / "s.md"
    prepare(p, resume=False, run_ts=TS, log=_log(tmp_path))
    assert p.read_text(encoding="utf-8").splitlines()[0] == "TASK_STATUS: IN_PROGRESS"


def test_prepare_backs_up_and_starts_clean(tmp_path):
    p = tmp_path / "s.md"
    p.write_text("TASK_STATUS: IN_PROGRESS\nold content\n", encoding="utf-8")
    prepare(p, resume=False, run_ts=TS, log=_log(tmp_path))
    backups = list(tmp_path.glob("s.md.*.bak"))
    assert len(backups) == 1
    assert "old content" in backups[0].read_text(encoding="utf-8")
    assert "old content" not in p.read_text(encoding="utf-8")


def test_resume_keeps_the_existing_file(tmp_path):
    p = tmp_path / "s.md"
    p.write_text("TASK_STATUS: IN_PROGRESS\nkeep me\n", encoding="utf-8")
    prepare(p, resume=True, run_ts=TS, log=_log(tmp_path))
    assert "keep me" in p.read_text(encoding="utf-8")
    assert list(tmp_path.glob("s.md.*.bak")) == []


def test_failed_backup_reuses_the_file_rather_than_clobbering(tmp_path, monkeypatch):
    """The .bat logs [WARN] and reuses the file as is when the move fails."""
    p = tmp_path / "s.md"
    p.write_text("TASK_STATUS: IN_PROGRESS\nprecious\n", encoding="utf-8")

    def boom(*a, **k):
        raise OSError("nope")

    monkeypatch.setattr("lmi.commands.schedule.state.os.replace", boom)
    log = _log(tmp_path)
    prepare(p, resume=False, run_ts=TS, log=log)
    assert "precious" in p.read_text(encoding="utf-8")
    assert "[WARN]" in (tmp_path / "run.log").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run and verify they fail**

Run: `python -m pytest tests/commands/schedule/test_state.py -v`
Expected: `ModuleNotFoundError: No module named 'lmi.commands.schedule.state'`.

- [ ] **Step 3: Implement `state.py`**

```python
"""The state file: template, backup-or-resume, and the completion check."""

import os
import re

from ...core.errors import EXIT_USAGE, LmiError

# Only the FIRST line is ever tested against this. A whole-file search is
# wrong and fails silently: real claude restates the protocol sentence
# "write TASK_STATUS: COMPLETE on the first line only when ..." inside the
# state file, so a file-wide match stops the loop after one iteration while
# line 1 still says IN_PROGRESS. This is landmine 14 in CLAUDE.md.
# \b (not "whitespace or end of line") matches the .bat's PowerShell regex,
# so "COMPLETE." counts and "COMPLETED" does not.
COMPLETE_RE = re.compile(r"^\s*TASK_STATUS:\s*COMPLETE\b")

STATE_TEMPLATE = """\
TASK_STATUS: IN_PROGRESS

## Goal

See the TASK section of the prompt supplied by lmi schedule.
Restate it here in your own words during the first iteration.

## Completed

- nothing yet

## In progress

- nothing yet

## Next steps

- read the task and plan the first chunk of work

## Notes and blockers

- state file created by lmi schedule on {now}
"""


def write_template(path, now_str):
    body = STATE_TEMPLATE.format(now=now_str)
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
    except OSError as exc:
        # The .bat swallows this and still logs success, after which the
        # loop can never see COMPLETE and repeats iteration 1 forever.
        # Fail loudly instead.
        raise LmiError(
            "cannot write the state file %s: %s" % (path, exc), EXIT_USAGE
        )


def prepare(path, resume, run_ts, log):
    if path.exists():
        if resume:
            log.line("State file       : keeping the existing file, -r was given")
            return
        backup = path.with_name(path.name + "." + run_ts + ".bak")
        try:
            os.replace(str(path), str(backup))
        except OSError:
            log.warn(
                "Could not back up the existing state file - it is reused as is."
            )
            return
        log.line("State file       : old state backed up to " + str(backup))
        log.line(
            "                   a new run starts clean - pass -r to continue "
            "an old task"
        )
    else:
        log.line("State file       : created new")
    write_template(path, _now_str())


def _now_str():
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def check_complete(path):
    try:
        with open(path, "rb") as fh:
            first = fh.readline()
    except OSError:
        return False
    if first.startswith(b"\xef\xbb\xbf"):
        first = first[3:]
    return COMPLETE_RE.search(first.decode("utf-8", "replace")) is not None
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/ -v`
Expected: 50 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lmi tests
git commit -s -m "feat: state file template, backup, resume and completion check"
```

---

## Task 6: Prompt composition and encoding

**Files:**
- Create: `lmi/commands/schedule/prompt.py`, `tests/commands/schedule/test_prompt.py`

**Interfaces:**
- Consumes: `Config`, `LmiError`.
- Produces: `read_prompt_source(cfg) -> str`; `compose(cfg, state_path, iter_label, started_str, state_body) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/commands/schedule/test_prompt.py`:

```python
import pytest

from lmi.commands.schedule.config import Config
from lmi.commands.schedule.prompt import compose, read_prompt_source
from lmi.core.errors import LmiError


def _cfg(tmp_path, **kw):
    base = dict(prompt_text="write a haiku", prompt_file=None, at=None,
                interval_min=0, max_runs=1, work_dir=tmp_path, user_flags=[],
                log_arg=None, state_arg=None, resume=False)
    base.update(kw)
    return Config(**base)


def test_inline_text_is_returned_verbatim(tmp_path):
    assert read_prompt_source(_cfg(tmp_path)) == "write a haiku"


def test_metacharacters_survive_untouched(tmp_path):
    text = "a & b | c < d > e ( f ) %PATH% !x!"
    assert read_prompt_source(_cfg(tmp_path, prompt_text=text)) == text


def test_utf8_file_is_read(tmp_path):
    p = tmp_path / "t.md"
    p.write_text("שלום עולם\n", encoding="utf-8")
    got = read_prompt_source(_cfg(tmp_path, prompt_text=None, prompt_file=p))
    assert "שלום עולם" in got


def test_utf8_bom_file_is_read_without_the_bom(tmp_path):
    p = tmp_path / "t.md"
    p.write_bytes("﻿hello\n".encode("utf-8"))
    got = read_prompt_source(_cfg(tmp_path, prompt_text=None, prompt_file=p))
    assert got.startswith("hello")


def test_utf16_file_is_decoded_not_mangled(tmp_path):
    """The .bat could only warn about UTF-16; Python decodes it properly."""
    p = tmp_path / "t.md"
    p.write_bytes("שלום\n".encode("utf-16"))
    got = read_prompt_source(_cfg(tmp_path, prompt_text=None, prompt_file=p))
    assert "שלום" in got


def test_undecodable_file_is_a_clear_usage_error(tmp_path):
    p = tmp_path / "t.md"
    p.write_bytes(b"\xff\xfe\xfe\xff\x00\x81\x8d")  # not valid UTF-8 or UTF-16
    with pytest.raises(LmiError) as exc:
        read_prompt_source(_cfg(tmp_path, prompt_text=None, prompt_file=p))
    assert exc.value.code == 2
    assert "t.md" in str(exc.value)


def test_composed_prompt_has_every_section(tmp_path):
    state = tmp_path / "s.md"
    body = "TASK_STATUS: IN_PROGRESS\n\n## Goal\n\nsomething\n"
    out = compose(_cfg(tmp_path), state, "2 of 5", "2026-08-03 10:15:00", body)
    assert out.startswith("# Unattended automated run")
    assert "lmi schedule" in out
    assert "run-claude.bat" not in out
    assert "Iteration: 2 of 5" in out
    assert "Started: 2026-08-03 10:15:00" in out
    assert "State file: " + str(state) in out
    assert "## State protocol - read this first" in out
    assert "## CURRENT STATE - " + str(state) in out
    assert "something" in out            # the state body is inlined
    assert "## TASK" in out
    assert out.rstrip().endswith("write a haiku")


def test_task_section_comes_after_current_state(tmp_path):
    out = compose(_cfg(tmp_path), tmp_path / "s.md", "1 of 1", "now", "body")
    assert out.index("## CURRENT STATE") < out.index("## TASK")
```

- [ ] **Step 2: Run and verify they fail**

Run: `python -m pytest tests/commands/schedule/test_prompt.py -v`
Expected: `ModuleNotFoundError: No module named 'lmi.commands.schedule.prompt'`.

- [ ] **Step 3: Implement `prompt.py`**

The header text is copied from `run-claude.bat`'s `:write_prompt_head`, with the tool name changed as the spec permits.

```python
"""Composing the per-iteration prompt.

The text is run-claude.bat's :write_prompt_head / :write_prompt_tail with
one substitution: the tool names itself `lmi schedule`, because telling
claude it was started by run-claude.bat would be false.
"""

from ...core.errors import EXIT_USAGE, LmiError

HEAD = """\
# Unattended automated run

You were started by the command lmi schedule with the -p flag.
Nobody is watching the terminal: never ask a question and never wait for
confirmation. Decide on your own and write down what you decided.

Iteration: {iter_label}
Started: {started}
Working directory: {work_dir}
State file: {state_file}

## State protocol - read this first

The state file above is the only memory shared between iterations. Its
current contents are copied under CURRENT STATE below.

1. Start from CURRENT STATE. Continue where the previous iteration stopped
   and never redo work that is already listed as completed.
2. Whenever you make progress, update the state file with Write or Edit.
   Do it as you go, not only at the end, so an interrupted run is not lost.
3. Keep the state file factual, self contained and under about 200 lines.
   A fresh session must be able to continue from it alone.
4. Keep this layout in the state file:
      TASK_STATUS: IN_PROGRESS
      ## Goal
      ## Completed
      ## In progress
      ## Next steps
      ## Notes and blockers
5. Write TASK_STATUS: COMPLETE on the first line only when the whole task is
   really finished. The runner stops looping as soon as it sees COMPLETE, so
   never write it while work remains.
6. If you are blocked, keep TASK_STATUS: IN_PROGRESS, describe the blocker
   under Notes and blockers and record the smallest useful next step.
7. Work in sensible chunks. Stopping this iteration once a meaningful piece
   of work is done is fine, as long as the state file is up to date first.

## CURRENT STATE - {state_file}

```markdown
"""

TAIL = """```

## TASK

"""


def read_prompt_source(cfg):
    if cfg.prompt_file is None:
        return cfg.prompt_text
    raw = cfg.prompt_file.read_bytes()
    # Sniff the BOM. The .bat could only detect UTF-16 and warn; decoding it
    # properly is free here. ANSI text carries no BOM and stays undetectable
    # by construction - that limit is unchanged.
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LmiError(
            "the prompt file %s is not UTF-8 and has no byte order mark; "
            "save it as UTF-8 (%s)" % (cfg.prompt_file, exc),
            EXIT_USAGE,
        )


def compose(cfg, state_path, iter_label, started_str, state_body):
    head = HEAD.format(
        iter_label=iter_label,
        started=started_str,
        work_dir=cfg.work_dir,
        state_file=state_path,
    )
    task = read_prompt_source(cfg)
    if not task.endswith("\n"):
        task += "\n"
    return head + state_body + TAIL + task
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/ -v`
Expected: 58 tests pass.

- [ ] **Step 5: Commit**

```bash
git add lmi tests
git commit -s -m "feat: compose the per-iteration prompt, decoding any BOM"
```

---

## Task 7: The lock, the loop, and the claude invocation

Delivers a working `lmi schedule`.

**Files:**
- Create: `lmi/core/lock.py`, `lmi/commands/schedule/runner.py`, `tests/conftest.py`, `tests/commands/schedule/test_runner.py`
- Modify: `lmi/commands/schedule/__init__.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `lmi.core.lock.single_instance_lock(path)` — a context manager raising `LockBusy` when held elsewhere; `lmi.core.lock.LockBusy`; `runner.run(args) -> int`; `runner.QUOTA_RE`.

- [ ] **Step 1: Write the fake claude fixture**

Create `tests/conftest.py`:

```python
"""A fake `claude` on a temporary PATH.

No test may reach a real claude: one exists on this machine and would spend
real quota. The fixture replaces PATH entirely rather than prepending.
"""

import os
import stat
import sys

import pytest

FAKE = """\
#!{python}
import os, sys
n_file = os.environ["FAKE_COUNT_FILE"]
n = 0
if os.path.exists(n_file):
    n = int(open(n_file).read() or 0)
n += 1
open(n_file, "w").write(str(n))

rec = os.environ.get("FAKE_DIR")
if rec:
    with open(os.path.join(rec, "argv-%d.txt" % n), "w") as fh:
        fh.write("\\n".join(sys.argv[1:]))
    with open(os.path.join(rec, "prompt-%d.txt" % n), "w", encoding="utf-8") as fh:
        fh.write(sys.stdin.read())
else:
    sys.stdin.read()

print("fake claude call %d" % n)
out = os.environ.get("FAKE_OUT")
if out:
    print(out)

sf = os.environ.get("FAKE_STATE_FILE")
if sf:
    at = os.environ.get("FAKE_COMPLETE_AT")
    prose = os.environ.get("FAKE_PROSE")
    if prose:
        open(sf, "w", encoding="utf-8").write(
            "TASK_STATUS: IN_PROGRESS\\n\\n## Goal\\n\\n"
            "only then may line 1 say TASK_STATUS: COMPLETE\\n"
        )
    elif at and int(at) == n:
        open(sf, "w", encoding="utf-8").write("TASK_STATUS: COMPLETE\\n")

sys.exit(int(os.environ.get("FAKE_RC", "0")))
"""


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / ("claude.py" if os.name == "nt" else "claude")
    exe.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    recdir = tmp_path / "rec"
    recdir.mkdir()
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setenv("FAKE_DIR", str(recdir))
    monkeypatch.setenv("FAKE_COUNT_FILE", str(tmp_path / "count.txt"))
    return type("F", (), {"dir": recdir, "count_file": tmp_path / "count.txt",
                          "exe": exe})()
```

> **Windows note for the implementer:** a `#!` line is not executable on Windows. If `os.name == "nt"`, `runner` must be able to find the fake. Rather than special-casing the runner, the fixture on Windows should write a `claude.bat` that invokes `python claude.py`. Implement that branch; do not add Windows-only code to `runner.py`.

- [ ] **Step 2: Write the failing tests**

Create `tests/commands/schedule/test_runner.py`:

```python
import os

from lmi.cli import main


def _count(fake):
    return int(fake.count_file.read_text())


def test_single_run_invokes_claude_once(tmp_path, fake_claude, capsys):
    rc = main(["schedule", "hello", "-d", str(tmp_path)])
    assert rc == 0
    assert _count(fake_claude) == 1
    assert "fake claude call 1" in capsys.readouterr().out


def test_default_flags_and_add_dir_reach_the_cli(tmp_path, fake_claude):
    main(["schedule", "hello", "-d", str(tmp_path)])
    argv = (fake_claude.dir / "argv-1.txt").read_text().splitlines()
    assert argv[0] == "-p"
    assert "--allowed-tools=Edit,Write" in argv
    assert "--add-dir" in argv


def test_user_flags_are_appended(tmp_path, fake_claude):
    main(["schedule", "hello", "-d", str(tmp_path), "-f", "--verbose --model x"])
    argv = (fake_claude.dir / "argv-1.txt").read_text().splitlines()
    assert argv[-2:] == ["--model", "x"] or "--verbose" in argv


def test_the_composed_prompt_reaches_claude_on_stdin(tmp_path, fake_claude):
    main(["schedule", "write a haiku", "-d", str(tmp_path)])
    body = (fake_claude.dir / "prompt-1.txt").read_text(encoding="utf-8")
    assert "# Unattended automated run" in body
    assert "## CURRENT STATE" in body
    assert "write a haiku" in body


def test_back_to_back_loop_runs_count_times(tmp_path, fake_claude):
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "3"]) == 0
    assert _count(fake_claude) == 3


def test_early_stop_when_line_one_becomes_complete(tmp_path, fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_STATE_FILE", str(tmp_path / "run-claude-state.md"))
    monkeypatch.setenv("FAKE_COMPLETE_AT", "2")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "5"]) == 0
    assert _count(fake_claude) == 2


def test_prose_complete_does_not_stop_the_loop(tmp_path, fake_claude, monkeypatch):
    """MANDATORY, landmine 14. Widening the check must turn this red."""
    monkeypatch.setenv("FAKE_STATE_FILE", str(tmp_path / "run-claude-state.md"))
    monkeypatch.setenv("FAKE_PROSE", "1")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "3"]) == 0
    assert _count(fake_claude) == 3


def test_failing_claude_call_never_kills_the_runner(tmp_path, fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_RC", "7")
    rc = main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "2"])
    assert rc == 1                      # at least one call failed
    assert _count(fake_claude) == 2      # but the loop kept going


def test_quota_wording_is_flagged(tmp_path, fake_claude, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_OUT", "Error: you have exceeded your usage limit")
    main(["schedule", "x", "-d", str(tmp_path)])
    assert "[QUOTA]" in capsys.readouterr().out


def test_claude_output_reaches_the_log(tmp_path, fake_claude):
    main(["schedule", "x", "-d", str(tmp_path)])
    log = next(tmp_path.glob("run-claude-*.log"))
    assert "fake claude call 1" in log.read_text(encoding="utf-8")


def test_at_in_the_past_starts_immediately(tmp_path, fake_claude):
    rc = main(["schedule", "x", "-d", str(tmp_path), "-t", "2020-01-01 00:00"])
    assert rc == 0 and _count(fake_claude) == 1


def test_second_run_is_refused_while_the_lock_is_held(tmp_path, fake_claude):
    from lmi.core.lock import single_instance_lock
    lock = tmp_path / "run-claude.lock"
    with single_instance_lock(lock):
        rc = main(["schedule", "x", "-d", str(tmp_path)])
    assert rc == 3
    assert _count(fake_claude) == 0      # claude was never started


def test_the_lock_is_free_again_afterwards(tmp_path, fake_claude):
    assert main(["schedule", "x", "-d", str(tmp_path)]) == 0
    assert main(["schedule", "x", "-d", str(tmp_path)]) == 0


def test_an_internal_failure_is_written_to_the_log(tmp_path, fake_claude, monkeypatch):
    """A crash in the runner must land in the log, not only on the terminal -
    otherwise an unattended run that died is undiagnosable afterwards."""
    def boom(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr("lmi.commands.schedule.runner.prompt.compose", boom)
    rc = main(["schedule", "x", "-d", str(tmp_path)])
    assert rc == 4
    body = next(tmp_path.glob("run-claude-*.log")).read_text(encoding="utf-8")
    assert "[ERROR]" in body
    assert "RuntimeError: synthetic" in body
```

- [ ] **Step 3: Run and verify they fail**

Run: `python -m pytest tests/commands/schedule/test_runner.py -v`
Expected: `ModuleNotFoundError: No module named 'lmi.core.lock'`.

- [ ] **Step 4: Implement `core/lock.py`**

```python
"""A single-instance lock that the OS releases when the process dies.

fcntl.flock on Unix, msvcrt.locking on Windows. Both are released by the
kernel on process exit, which is why there is no PID file and no staleness
check here: a hard kill cannot leave a lock behind. run-claude.bat gets the
same property from holding handle 9 open.
"""

import contextlib
import os


class LockBusy(Exception):
    """Another process holds the lock."""


if os.name == "nt":
    import msvcrt

    def _acquire(fh):
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise LockBusy()

    def _release(fh):
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def _acquire(fh):
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise LockBusy()

    def _release(fh):
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


@contextlib.contextmanager
def single_instance_lock(path):
    """Hold an exclusive lock on `path` for the duration of the block.

    Raises LockBusy immediately if another process holds it.
    """
    fh = open(path, "a+")
    try:
        _acquire(fh)
    except LockBusy:
        fh.close()
        raise
    try:
        yield
    finally:
        _release(fh)
        fh.close()
```

- [ ] **Step 5: Implement `runner.py`**

```python
"""The iteration loop and the claude invocation."""

import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

from ...core.errors import EXIT_OK, EXIT_USAGE, LmiError
from ...core.lock import LockBusy, single_instance_lock
from ...core.log import Logger
from . import paths, prompt, state
from .config import build_config
from .exit_codes import EXIT_CALL_FAILED, EXIT_INTERNAL, EXIT_LOCKED

DEFAULT_FLAGS = ["--allowed-tools=Edit,Write"]

QUOTA_RE = re.compile(
    r"usage limit|rate.?limit|quota|credit balance|insufficient credit"
    r"|too many requests|overloaded|exceeded your",
    re.IGNORECASE,
)


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run(args):
    cfg = build_config(args)
    run_ts = paths.timestamp()
    state_path = paths.resolve_state(cfg)
    log_path = paths.resolve_log(cfg, run_ts)
    log = Logger(log_path)

    claude = shutil.which("claude")
    if claude is None:
        raise LmiError("claude is not on PATH", EXIT_USAGE)

    lock_path = state_path.parent / "run-claude.lock"
    try:
        with single_instance_lock(lock_path):
            return _run_locked(cfg, log, state_path, run_ts, claude)
    except LockBusy:
        print(
            "[ERROR] another run is working on this state file: %s" % state_path,
            file=sys.stderr,
        )
        return EXIT_LOCKED
    except LmiError:
        raise
    except Exception:
        # Everything the runner itself reports must reach the log, not just the
        # terminal. run-claude.bat gets this by capturing its own stderr to a
        # file and appending it under [WARN]; here the traceback goes straight
        # into the log so a crashed unattended run is diagnosable afterwards.
        log.error("the runner itself failed - this is a bug in lmi:")
        for line in traceback.format_exc().rstrip().splitlines():
            log.error("  " + line)
        return EXIT_INTERNAL


def _run_locked(cfg, log, state_path, run_ts, claude):
    log.line("=" * 75)
    log.line("lmi schedule starting at " + _now_str())
    log.line("Working directory: " + str(cfg.work_dir))
    log.line("State file: " + str(state_path))
    log.line("Log file  : " + str(log.path))
    log.line("Iterations: %d" % cfg.max_runs)
    log.line("Interval  : %d minute/s" % cfg.interval_min)
    if cfg.at is not None:
        log.line("Start time: " + cfg.at.strftime("%Y-%m-%d %H:%M"))
    log.line("=" * 75)

    state.prepare(state_path, cfg.resume, run_ts, log)
    _wait_until(cfg.at, log)

    tmp_dir = Path(tempfile.mkdtemp(prefix="lmi-schedule-"))
    exit_code = EXIT_OK
    runs = fails = 0
    try:
        for iteration in range(1, cfg.max_runs + 1):
            label = "%d of %d" % (iteration, cfg.max_runs)
            started = _now_str()
            log.line("")
            log.line("--- iteration %s started %s ---" % (label, started))

            rc = _one_iteration(
                cfg, log, state_path, claude, tmp_dir, iteration, label, started
            )
            runs += 1
            if rc != 0:
                fails += 1
                exit_code = EXIT_CALL_FAILED
                log.error("claude exited with code %d. The runner continues." % rc)

            if state.check_complete(state_path):
                log.line(
                    "State file line 1 says TASK_STATUS: COMPLETE - stopping early."
                )
                break
            if iteration >= cfg.max_runs:
                break
            if cfg.interval_min > 0:
                secs = cfg.interval_min * 60
                nxt = datetime.fromtimestamp(time.time() + secs)
                log.line("Next iteration at " + nxt.strftime("%Y-%m-%d %H:%M:%S"))
                time.sleep(secs)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    log.line("")
    log.line("=" * 75)
    log.line("lmi schedule finished at " + _now_str())
    log.line("%d run/s, %d succeeded, %d failed." % (runs, runs - fails, fails))
    log.line("State file: " + str(state_path))
    log.line("Log file  : " + str(log.path))
    log.line("=" * 75)
    if fails:
        log.error(
            "%d iteration/s failed - search the log for [ERROR] and [QUOTA]." % fails
        )
    return exit_code


def _one_iteration(cfg, log, state_path, claude, tmp_dir, n, label, started):
    try:
        body = state_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        body = ""
    composed = prompt.compose(cfg, state_path, label, started, body)

    prompt_path = tmp_dir / ("prompt-%d.txt" % n)
    prompt_path.write_text(composed, encoding="utf-8", newline="\n")
    out_path = tmp_dir / ("out-%d.txt" % n)

    argv = [claude, "-p"] + DEFAULT_FLAGS + \
        ["--add-dir", str(state_path.parent)] + cfg.user_flags

    log.line("--- claude output ---")
    with open(prompt_path, "rb") as stdin_fh, \
            open(out_path, "wb") as out_fh:
        # check=False by default: a non-zero exit must be returned, never
        # raised. That is invariant 2 - a failing call must not end the run.
        completed = subprocess.run(
            argv, stdin=stdin_fh, stdout=out_fh,
            stderr=subprocess.STDOUT, cwd=str(cfg.work_dir),
        )
    output = out_path.read_text(encoding="utf-8", errors="replace")
    for line in output.splitlines():
        log.line(line)
    log.line("--- end of claude output ---")

    if QUOTA_RE.search(output):
        log.quota(
            "*** Possible quota, rate limit or overload problem in the claude "
            "output above."
        )
        log.quota(
            "*** Check your usage before trusting the result of this iteration."
        )
    return completed.returncode


def _wait_until(target, log):
    if target is None:
        return
    secs = (target - datetime.now()).total_seconds()
    if secs <= 0:
        log.line(
            "Start time %s has already passed - starting now."
            % target.strftime("%Y-%m-%d %H:%M")
        )
        return
    log.line(
        "Waiting until %s (%d seconds)."
        % (target.strftime("%Y-%m-%d %H:%M"), int(secs))
    )
    time.sleep(secs)
```

- [ ] **Step 6: Wire `run` directly**

Replace `lmi/commands/schedule/__init__.py` with:

```python
from .config import add_arguments  # noqa: F401
from .runner import run  # noqa: F401

NAME = "schedule"
HELP = "Run Claude Code unattended, looping in the foreground"
```

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest tests/ -v`
Expected: 72 tests pass.

- [ ] **Step 8: Commit**

```bash
git add lmi tests
git commit -s -m "feat: the iteration loop, the lock and the claude invocation"
```

---

## Task 8: README and the retirement gate

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add an `lmi` section to README.md**

Cover: `pip install -e ".[dev]"` (or `pipx install .`), that `lmi schedule` takes the same flags as `run-claude.bat` with the option table applying to both, `lmi --help` and `lmi schedule --help`, running the suite with `python -m pytest tests/ -v`, and the exit codes.

State plainly: `lmi` is intended to replace `run-claude.bat`, but the `.bat` **stays until the two verifications below pass**; and macOS and Windows are unverified so far.

- [ ] **Step 2: Record the two verification gates in README.md**

1. A real end-to-end run on Linux against the actual `claude` CLI — one iteration, then a loop reaching `TASK_STATUS: COMPLETE`.
2. A Windows Task Scheduler run with "run whether user is logged on or not", because the development machine's Python is a Microsoft Store install reached through an App Execution Alias with no `py.exe`. If the `pip`-generated `lmi` shim does not resolve there, `run-claude.bat` stays.

- [ ] **Step 3: Verify the suite once more and commit**

```bash
python -m pytest tests/ -v
git add README.md
git commit -s -m "docs: document lmi and the gates on retiring run-claude.bat"
```

---

## After the plan

Neither of these can be settled by the suite, and both must be reported as outstanding rather than assumed:

1. **A real end-to-end run on Linux** against the actual `claude` CLI. Landmines 13 and 14 were both found this way; a fake CLI cannot surface them.
2. **macOS and Windows.** Development happens on Linux. The `msvcrt` lock branch and the console-script installation are untested elsewhere. Treat both platforms as intended rather than tested.
