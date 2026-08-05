# run-claude.bat

A Windows batch script that runs the [Claude Code](https://claude.com/claude-code)
CLI **unattended**: start now or at a scheduled time, repeat on an interval, carry
progress across iterations through a state file, log everything, and never die
because a single `claude` call failed.

It exists because a long task usually does not fit in one session. Instead of one
huge prompt, you give `run-claude.bat` a task and an iteration count; each
iteration is a fresh `claude -p` invocation that reads the state file the previous
iteration wrote, continues from there, and updates it. The loop stops early the
moment the state file reports the task is done.

Pure `cmd.exe` plus PowerShell for time handling. No install step, no
dependencies beyond the Claude Code CLI itself.

This repository also contains `lmi schedule`, a Python reimplementation of
this same runner, intended to eventually replace it. See
[lmi schedule — the Python successor](#lmi-schedule--the-python-successor)
below. The `.bat` documented in this section is unaffected and stays exactly
as described until that section's two verification gates pass.

---

## Requirements

- Windows with `cmd.exe` and either `powershell.exe` or `pwsh.exe` on `PATH`
  (PowerShell handles all date arithmetic and waits — batch date maths is
  locale-dependent and unreliable).
- The Claude Code CLI on `PATH`. The script accepts `claude.exe`, `claude.cmd`,
  `claude.bat` or a bare `claude`, in that order.
- **Authentication already done**, interactively, once: `claude auth login` in a
  Windows cmd window. An unattended run has nobody to complete a sign-in prompt.
  Credentials live in `%USERPROFILE%\.claude\.credentials.json` and are per-user —
  WSL credentials do not carry over to a Windows install.

The script validates all of the above and exits with a clear message rather than
failing halfway through a scheduled overnight run.

---

## Usage

```
run-claude.bat "<prompt or prompt-file>" [-t "YYYY-MM-DD HH:MM"] [-i minutes]
               [-c count] [-d workdir] [-f "flags"] [-l logfolder]
               [-s statefile] [-r]
```

Run `run-claude.bat -h` for the built-in help, which is the authoritative option
list.

### Options

| Option | Meaning |
|---|---|
| `<prompt>` | **Mandatory, and the only mandatory parameter.** Either the prompt text itself, quoted, or the path of a file containing the prompt. If the argument names an existing file it is treated as a file; otherwise as literal text. |
| `-t "YYYY-MM-DD HH:MM"` | Wait until this time before the first iteration. Omitted = start immediately. A time already in the past starts immediately. |
| `-i <minutes>` | Minutes to wait between iterations. **Requires `-c`.** `-i 0` runs them back to back. The wait starts only after an iteration has *ended*. |
| `-c <count>` | Total number of iterations, must be > 0. **Requires `-i`.** Omit both for a single run. |
| `-d <dir>` | Working directory for claude. Omitted = the directory `run-claude.bat` was invoked from. |
| `-f "<flags>"` | Extra claude CLI flags, appended after the always-on defaults. |
| `-l <folder or file>` | Log destination. A folder receives `run-claude-<timestamp>.log`; a path with an extension is used as the log file itself. Omitted = `<workdir>\run-claude-<timestamp>.log`. |
| `-s <file>` | State file. Omitted = `<workdir>\run-claude-state.md`. |
| `-r` | Resume: keep the existing state file instead of backing it up and starting clean. |
| `-h` | Show help and exit 0. |

`-i` and `-c` are **mutually required** — either both or neither. Each alone exits
2, with a message explaining why. On its own, `-i` says how long to wait but never
when to stop; `-c` says how many iterations but never how long to wait between
them. There is deliberately no unlimited-loop mode: an unattended runner with no
stop condition is a liability.

Every invocation always passes `--allowed-tools=Edit,Write` and
`--add-dir <state file directory>`. Anything you give with `-f` is appended after
those, so `-f "--model opus"` composes rather than replaces.

### Examples

```bat
rem one run, inline prompt
run-claude.bat "Add unit tests for the parser module"

rem 8 iterations, half an hour apart, against another repo, logging to C:\logs
run-claude.bat task.md -i 30 -c 8 -d C:\work\myrepo -l C:\logs

rem start tonight at 22:00, then hourly for 12 iterations
run-claude.bat task.md -t "2026-08-01 22:00" -i 60 -c 12 -f "--model opus"

rem continue yesterday's task instead of starting clean
run-claude.bat task.md -i 20 -c 5 -r
```

---

## How the iteration loop works

Each iteration composes a prompt file containing, in order:

1. A header stating the run is unattended, and that claude must never ask a
   question or wait for confirmation.
2. The iteration number, start time, working directory and state file path.
3. A numbered **state protocol** (see below).
4. `## CURRENT STATE` — the full current contents of the state file, inline.
5. `## TASK` — your prompt, or the contents of your prompt file.

That file is fed to claude on stdin:

```bat
cmd /c claude -p --allowed-tools=Edit,Write --add-dir "<stateDir>" <yourFlags> < promptfile > outfile 2>&1
```

The state protocol instructs claude to keep this layout in the state file:

```
TASK_STATUS: IN_PROGRESS
## Goal
## Completed
## In progress
## Next steps
## Notes and blockers
```

and to write `TASK_STATUS: COMPLETE` on the **first line** only when the whole
task is genuinely finished. After each iteration the runner reads line 1 of the
state file and stops the loop early if it matches. It checks the first line only,
on purpose: claude reliably restates the "write TASK_STATUS: COMPLETE when…"
sentence *inside* the state file, and a whole-file search matches that prose and
stops the loop after one iteration while the task is barely started.

### State file lifecycle

A new run **backs up** an existing state file to
`<statefile>.<timestamp>.bak` and starts from a clean template, so an unrelated
task never inherits stale context. Pass `-r` to keep the existing file and
continue where the last run stopped.

> **Do not put the state file inside a `.claude` folder.** The CLI treats
> everything there as sensitive and refuses to Write or Edit it; unattended there
> is nobody to approve, so the write silently fails, the state file stays at the
> template, and the loop repeats iteration 1 forever while reporting success.
> This is why the default is `<workdir>\run-claude-state.md` rather than
> `.claude\state.md`.

---

## Guarantees

These are treated as invariants, not aspirations, and each is covered by the test
suite.

**Iterations never overlap.** The script is sequential and the interval wait
begins only after `claude` exits. A second *instance* is blocked by a lock file
next to the state file, held as an open file handle for the whole run. A second
run on the same state file refuses to start and exits 3. The lock cannot go
stale — Windows releases the handle when the process dies, however it dies. The
lock file itself staying on disk between runs is normal. To run two tasks in
parallel, give them different `-s` state files.

**A failing claude call never fails the runner.** The exit code, the output and
the failure are printed and logged with `[ERROR]`, the iteration is counted as
failed, and the loop continues to the next one. Output matching quota,
rate-limit or overload wording is additionally flagged `[QUOTA]`, since hitting a
plan limit mid-loop is the common case and needs to be noticeable in a log you
read the next morning. claude is invoked through `cmd /c` specifically so that a
fatal error inside it — including a parse error, if `claude` resolves to a
`.cmd` shim — stays contained in the child process.

**Nothing ever waits for a keypress.** No `pause`, no bare `timeout`; the prompt
arrives via stdin redirection and all waits use PowerShell `Start-Sleep`.

### Logging

Everything claude prints, plus every runner action, goes to both the console and
the log file: the resolved configuration, each iteration's start, end, exit code
and duration, state file handling, and a final summary of how many iterations ran,
succeeded and failed.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | All iterations completed fine |
| 1 | At least one claude call failed (the runner still ran to the end) |
| 2 | Bad parameters, or a missing prerequisite |
| 3 | Another run holds the lock on this state file |

---

## Quoting and encoding — the cmd.exe facts of life

An inline prompt may safely contain `& | < > ( )` and `!`. Two things cannot be
fixed in batch and are documented rather than worked around:

- An inline prompt containing a **double quote**, or a `%` when you call this
  script from another `.bat`, is mangled by cmd before the script ever sees it.
  Use a prompt file.
- `-t` always needs its quotes: `-t "2026-08-01 22:00"`. (An unquoted
  `-t 2026-08-01 22:00` is tolerated as two tokens, but quoting is the supported
  form.)

**Save prompt files as UTF-8.** The file is copied into the composed prompt as raw
bytes, which is correct for UTF-8. A **UTF-16** file gets converted by cmd to the
console codepage on the way in, so on a non-Latin console every non-ASCII
character reaches claude corrupted while the run still reports success — a UTF-16
byte order mark is detected and reported as `[WARN]`. **ANSI** text carries no
mark and cannot be distinguished from UTF-8 at all, so it is not detectable by
construction. If your task file contains Hebrew or any accented character, save it
as UTF-8.

Inline prompts are immune to all of this: the text travels from the cmd argument
to an environment variable to PowerShell, never through a codepage conversion.

---

## Project layout

```
run-claude.bat        the runner, 866 lines, CRLF line endings
runner-test-task.md   a deliberately 5-step task file, used to exercise the loop
test\run-tests.bat    the regression suite, 43 cases
test\bin\claude.cmd   a stub CLI, so the suite costs nothing and no quota
CLAUDE.md             developer handoff: architecture, solved cmd.exe landmines
pyproject.toml        packaging for lmi: name, entry point, Python >=3.9, pytest
lmi\                  the Python reimplementation
  cli.py              top-level argparse parser and command dispatch
  core\               errors and exit codes shared by every command, the
                      single-instance lock (fcntl / msvcrt), logging
  commands\
    schedule\         the lmi schedule command: config/validation, paths,
                      prompt composition, the state file, the iteration loop
tests\                pytest suite for lmi, 117 cases, mirrors the lmi\ tree
docs\install\         per-platform install guides, one file each
scripts\              install scripts, all four installing the same wheel:
                      install-linux.sh, install-macos.sh,
                      install-windows.cmd, install-windows.ps1
README.md             this file
LICENSE               MIT
```

All `.bat` and `.cmd` files use **CRLF** line endings and must keep them — cmd can
misparse a batch file saved with LF.

`CLAUDE.md` is the document to read before editing the script. It records fifteen
specific `cmd.exe` landmines that are already solved, each with the symptom it
produced, so a regression is recognisable rather than mysterious.

---

## Testing

This section covers `run-claude.bat`'s own suite. `lmi schedule` has a
separate one, run with `python3 -m pytest tests/ -v` — see
[Testing lmi](#testing-lmi) below.

```bat
cd test
run-tests.bat          rem 41 cases, ~15 seconds
run-tests.bat -full    rem 43 cases, adds two slow timing cases, ~2.5 minutes
```

Exit 0 all passed, 1 something failed, 9 the suite could not start. Artefacts of
every case — console output, log, state file, and the stub's record of exactly how
it was called — are kept under `%TEMP%\rc-suite-<timestamp>\caseN\`.

The suite runs against the stub CLI, so it is free and consumes no quota. It
rebuilds `PATH` from scratch and aborts with exit 9 if it can still see a real
`claude`, so it can never quietly spend real tokens. Run it after every change to
the script.

What it covers: every validation error and its exit code, `-h`, single runs both
inline and from a file, an inline prompt full of shell metacharacters, the
composed prompt's contents, back-to-back and counted loops, early stop on
`TASK_STATUS: COMPLETE`, the completion-in-prose false positive, a failing claude
call (runner survives, exits 1), quota flagging, `-l` as folder and as file, `-s`,
`-f` pass-through, the default flags reaching the CLI, prompt file encoding
warnings, state backup and `-r`, paths containing spaces / `&` / `(x86)`, lock
contention and release, and `-t` in the past. With `-full`: a real future `-t`
wait and a real measured `-i 1 -c 2` interval.

What a stub can **never** cover is how the real CLI behaves. The two nastiest bugs
in this script's history — the `.claude\` state file and the completion-in-prose
false positive — were both silent successes that the suite reported as healthy,
and both were found only by real end-to-end runs. So also run a real one:

```bat
mkdir C:\claude-test & cd /d C:\claude-test
copy <repo>\run-claude.bat .
copy <repo>\runner-test-task.md .
run-claude.bat runner-test-task.md -i 0 -c 5
```

Success = `runner-test.txt` has five lines, one per iteration, and line 1 of the
state file reads `TASK_STATUS: COMPLETE`. Both failure modes to watch for report
exit 0, so check the artefacts, not the exit code: a state file that still looks
like the blank template means the state write was blocked; a loop that stopped
after iteration 1 with work abandoned means a false completion match.

### Debugging

Copy the script to `dbg.bat` with `@echo off` changed to `@echo on` and run that —
the trace stops at the offending line. Runner stderr goes to
`%TEMP%\run-claude-<timestamp>\rc-runner-stderr.txt`, and that temp folder survives
a crash, so read it when a run dies quietly.

---

## Known limitations

- **No per-iteration timeout.** A hung `claude` call stalls the loop
  indefinitely. No test can surface this as a failure; it is a missing feature.
- **A quota failure consumes an iteration.** There is no retry with backoff — the
  failure is flagged `[QUOTA]` and the loop moves on to the next iteration.
- **No log rotation.** Each run writes a new timestamped log file.
- An inline prompt cannot contain a double quote (see above).
- **The state file cannot live on a Windows network share**, so `lmi schedule`
  refuses a UNC working directory with exit 2 and an explanation. The lock file
  is created beside the state file, and Windows byte-range locking is
  unsupported on a share: on a WSL 9p mount `msvcrt.locking` fails with
  `EINVAL`, which `lmi/core/lock.py` cannot tell apart from a lock someone else
  holds — so the original symptom was exit 3, "another run is working on this
  state file", with nothing else running.

  The restriction is only on the **state file**, so the working directory can
  stay on the share:

  ```
  lmi schedule "..." -s C:\lmi\run-claude-state.md
  ```

  Verified: state file and lock on the local drive, log on the share, working
  directory still the UNC path, exit 0. Local NTFS is unaffected throughout.

None of these are scheduled work. If you want one, say so before building it.

---

## lmi schedule — the Python successor

`lmi` is a Python CLI, built to eventually replace `run-claude.bat`. Its
`schedule` subcommand is that replacement: it runs the Claude Code CLI
unattended in a foreground loop, taking the same eight flags with the same
meanings (`-t -i -c -d -f -l -s -r`), the same state-file protocol, and the
same default file names (`run-claude-state.md`, `run-claude-<timestamp>.log`)
as the `.bat` above — a state file written by one is a valid state file for
the other. Everything in [Usage](#usage) and
[How the iteration loop works](#how-the-iteration-loop-works) above describes
`lmi schedule` too, except where this section says otherwise.

**`lmi` is intended to replace `run-claude.bat`, but the `.bat` stays in this
repository, unmodified and undeprecated, until both verification gates below
have passed.** Treat it as the current, supported tool until then.

Requires Python 3.9 or newer. No runtime dependencies beyond the standard
library.

### Installing

Step-by-step guides, one per platform. Each ends with a bare `lmi` command on
your PATH — no `python -m` prefix and nothing to activate.

| Platform | Guide | Status |
|---|---|---|
| Linux, including WSL | [docs/install/linux.md](docs/install/linux.md) | verified on Ubuntu 24.04, Python 3.12 and 3.9.23 |
| Windows — `cmd.exe` | [docs/install/windows-cmd.md](docs/install/windows-cmd.md) | verified on Windows, Python 3.13 |
| Windows — PowerShell | [docs/install/windows-powershell.md](docs/install/windows-powershell.md) | verified on Windows, Python 3.13 |
| macOS | [docs/install/macos.md](docs/install/macos.md) | script written — **never run on a Mac** |

Each guide gives a scripted route, the same steps by hand, and `pipx` if you
prefer it to manage isolation for you — plus a first run, updating,
uninstalling, and the troubleshooting specific to that platform.

#### One wheel, every platform

You install **one file: `lmi-0.1.0-py3-none-any.whl`**, about 22 KB. That name is
the compatibility contract: `py3` any Python 3, `none` no compiled ABI, `any`
**any operating system**. `lmi` is pure Python with no third-party dependencies
(`dependencies = []`, every import from the standard library, no `.c` or `.so`
anywhere), which is what earns the universal tag. There is no per-platform
artefact to build, test, or keep in sync — `tests/test_packaging.py` fails if any
of those properties is lost.

pip then generates whatever launcher the local OS needs from that same wheel: a
real `lmi.exe` on Windows, a shebang script elsewhere. The platform-specific work
happens on the user's machine, at install time, by pip.

Build it once, on any machine with a network:

```bash
python3 -m pip wheel --no-deps -w dist .
```

Linux and WSL:

```bash
git clone -b lmi-schedule https://github.com/dawnburst/run-claude.git ~/lmi
cd ~/lmi && ./scripts/install-linux.sh
```

It installs the wheel into a virtual environment of its own at
`~/.local/share/lmi/venv` and symlinks the generated command into
`~/.local/bin`, so **the clone is disposable afterwards**. Re-running it is how
you upgrade; `--uninstall` reverses it.

Windows:

```bat
scripts\install-windows.cmd
```

It installs the wheel with `pip install --user`, which produces a **real
`lmi.exe`**, and adds that Scripts directory to your user PATH. Run the `.cmd`
even from PowerShell: it wraps `install-windows.ps1` with `-ExecutionPolicy
Bypass` for that one invocation, because a default Windows refuses to run a local
`.ps1`. Note **git is not on a stock Windows** — both Windows guides start from
downloading the wheel and the script into one folder, which the installer expects.

macOS has `scripts/install-macos.sh`, a close mirror of the Linux one. Its shared
logic has been exercised on Linux; its macOS-specific parts — the `python3`
search, the `readlink -f`-free ownership check, naming `~/.zshrc`, bash 3.2
syntax — are written from documentation. **It has never run on a Mac.** Treat it
as intended rather than proven.

**Installing needs no network.** Every install command passes `--no-index`, and a
wheel needs no build backend — unlike `pip install .`, which fetches
`setuptools>=61` to build. So an air-gapped machine needs the 22 KB wheel and
nothing else. Only *building* the wheel wants a network.

Three pitfalls the guides exist to steer around:

- **On Windows, `pip install --user` appears to work and then `lmi` is still
  "not recognized"**, because the user Scripts directory is not on PATH by
  default. The installer adds it. Its location comes from `sysconfig`, not
  `%APPDATA%\Python\PythonXX\Scripts`, which is wrong for a Microsoft Store
  Python — that inserts a version level.
- **On Debian and Ubuntu, `pip install --user` is refused outright** with "This
  environment is externally managed" (PEP 668), and `python3 -m venv` fails with
  `ensurepip is not available` because Debian ships that separately. The
  installer needs neither root nor apt: it falls back to
  `python3 -m venv --without-pip` and populates it with the system pip's
  `--python` flag. Verified on Ubuntu 24.04 with `python3-venv` absent.
- **Running from a UNC path on Windows.** The `.exe` keeps the real working
  directory where the old `.cmd` shim degraded to `C:\Windows`. But Windows
  cannot lock a file on a share, so `lmi schedule` **refuses** a UNC working
  directory with exit 2 and points at the fix — `-s` on a local drive, which
  lets the working directory stay on the share. See
  [Known limitations](#known-limitations).

For development in a repo-local environment:

```bash
python3 -m venv .venv          # or: virtualenv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

You do not need to install anything to run the test suite — see
[Testing lmi](#testing-lmi).

### Usage and options

```
lmi schedule "<prompt or prompt-file>" [-t "YYYY-MM-DD HH:MM"] [-i minutes]
             [-c count] [-d workdir] [-f "flags"] [-l logfolder]
             [-s statefile] [-r]
```

Run `lmi --help` for the list of available commands, and
`lmi schedule --help` for the authoritative flag list. The
[Options](#options) table above applies to `lmi schedule` unchanged, with two
deliberate differences:

- **`-t` must be quoted.** The `.bat` tolerates an unquoted
  `-t 2026-08-05 22:00` as two loose tokens; `lmi schedule` rejects it with a
  usage error. Supporting the unquoted form would make `-t` consume
  arguments greedily, which risks silently swallowing the prompt argument
  that follows it. Always write `-t "2026-08-05 22:00"`.
- **`-l` and `-s` expand a leading `~` themselves**, so a quoted
  `-s "~/notes/state.md"` — which the shell leaves untouched — still lands in
  your home directory instead of creating a directory literally named `~`.

### What lmi fixes

Three behaviors of `run-claude.bat` that fail silently are fixed in `lmi
schedule`:

- A state file that cannot be written now **raises an error** instead of
  logging success and looping on an unwritten template forever (landmine 13
  in `CLAUDE.md`).
- A crash inside the runner itself is **logged with its full traceback**,
  not just printed to a terminal nobody may be watching.
- A **UTF-16** prompt file is **decoded correctly** from its byte order mark,
  rather than silently mangled through the console codepage (landmine 15).
  ANSI prompt files remain undetectable by construction, same as the `.bat`.

### Exit codes

`0` and `2` are **global to every `lmi` command**, not just `schedule`: no
future command may redefine what they mean. The rest are specific to
`schedule`.

| Code | Meaning | Scope |
|---|---|---|
| 0 | All iterations completed fine | global |
| 1 | At least one claude call failed (the runner still ran to the end) | `schedule` |
| 2 | Bad parameters, or a missing prerequisite | global |
| 3 | Another run holds the lock on this state file | `schedule` |
| 4 | The runner itself crashed — a bug in `lmi`, not in your task | `schedule` |

### Testing lmi

```bash
python3 -m pytest tests/ -v
```

No install is required first — pytest puts the repository root on `sys.path`,
so the suite runs against a clean checkout. A virtual environment is only
needed to exercise the installed `lmi` console script itself, not to run the
tests. Currently **117 tests, all passing**.

### Platform status — be precise about this

Development happens on Linux. What has actually been executed elsewhere:

- **Windows: verified.** Install and uninstall through both
  `install-windows.cmd` and `install-windows.ps1` against a Microsoft Store
  Python 3.13; a real `lmi.exe` produced by pip; a bare `lmi` resolving in a new
  window; exit codes 0 and 2 coming back through the `.exe`; and a full
  `lmi schedule` run on local NTFS writing its log, state file and lock. The
  **Windows file-locking branch** (`msvcrt.locking`) has therefore now run — and
  running it is what exposed the UNC limitation in
  [Known limitations](#known-limitations).
- **macOS: never executed.** Neither the install script nor `lmi` itself. The
  script's shared logic was exercised on Linux; its macOS-specific parts are
  written from documentation.

Do not describe macOS support as proven. It is unverified, not assumed working.

**The interpreter floor is verified.** The full suite and
an end-to-end CLI run both pass on **CPython 3.9.23** — single run, a loop that
stops early on `TASK_STATUS: COMPLETE`, a failing `claude` call leaving the
runner alive at exit 1, quota detection, argument validation, and two concurrent
runs where the second is refused with exit 3. This matters because one real bug
was found exactly here: `Path.write_text(..., newline=...)` needs Python 3.10, so
before it was fixed every run died at the first iteration on 3.9. A syntax-level
check cannot catch a parameter added in a later version — only running the older
interpreter can.

So: the **3.9 floor** is tested. **Linux** and **Windows** are tested. **macOS**
is not.

### The two verification gates before run-claude.bat can be retired

Both of these must pass before `run-claude.bat` is removed from this
repository or described as deprecated. Gate 1 is **half done**; gate 2 has not
been attempted.

1. **A real end-to-end run on Linux against the actual `claude` CLI**: one
   single iteration, then a loop that reaches `TASK_STATUS: COMPLETE`. This
   matters because the two most expensive bugs in this project's history —
   landmines 13 and 14 in `CLAUDE.md`, a blocked state-file write and a false
   completion match — were both silent successes that a fake CLI reported as
   healthy. Only a real run caught either one. The pytest suite above cannot
   substitute for this.

   **The single-iteration half now passes.** A real run against
   `~/.local/bin/claude` (v2.1.221) completed in 25 seconds: exit 0, the
   requested file created, the state file rewritten by Claude to
   `TASK_STATUS: COMPLETE` on line 1, and the loop stopping early on it. That
   specifically clears landmine 13 — the state file was genuinely written, not
   left as the untouched template — and landmine 14, since the completion was
   detected from line 1 rather than from prose.

   **Still outstanding: a real multi-iteration loop**, which is what proves
   state carries forward across iterations. Use `runner-test-task.md`, the
   deliberately five-step task file in this repository, with `-i 1 -c 5`.
2. **A Windows Task Scheduler run with "run whether user is logged on or
   not."** Not attempted. The install route now targets a real `lmi.exe` with the
   interpreter path built in, which removes two of the three things that could
   fail in that context — no `python` lookup on PATH, and no `cmd.exe` shim — but
   that is reasoning, not a measurement. The remaining unknown is whether the
   task's own environment resolves the `.exe` and its interpreter; the
   development machine's Python is a Microsoft Store install reached through an
   App Execution Alias, with no `py.exe` launcher. If it fails, that is a finding
   about **installation**, not about the design of `lmi schedule` — and
   `run-claude.bat` stays in the repository until it is resolved, regardless.

---

## License

MIT — see [LICENSE](LICENSE). Use it, adapt it, redistribute it; just keep the
copyright notice. No warranty.
