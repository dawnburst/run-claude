# lmi

A Python CLI that runs the [Claude Code](https://claude.com/claude-code) CLI
**unattended**: start now or at a scheduled time, repeat on an interval, carry
progress across iterations through a state file, log everything, and never die
because a single `claude` call failed.

It exists because a long task usually does not fit in one session. Instead of one
huge prompt, you give `lmi schedule` a task and an iteration count; each
iteration is a fresh `claude -p` invocation that reads the state file the previous
iteration wrote, continues from there, and updates it. The loop stops early the
moment the state file reports the task is done.

Pure Python, standard library only. Requires Python 3.9 or newer and the Claude
Code CLI.

---

## Requirements

- **Python 3.9 or newer.** No runtime dependencies beyond the standard library.
- The **Claude Code CLI on `PATH`**, resolvable as `claude`.
- **Authentication already done**, interactively, once: `claude auth login`. An
  unattended run has nobody to complete a sign-in prompt. Credentials live in
  `~/.claude/.credentials.json` (`%USERPROFILE%\.claude\` on Windows) and are
  per-user — WSL credentials do not carry over to a Windows install.

`lmi schedule` validates its arguments and prerequisites up front and exits with
a clear message rather than failing halfway through a scheduled overnight run.

---

## Installing

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

### One wheel, every platform

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
git clone https://github.com/dawnburst/run-claude.git ~/lmi
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
- **Running from a UNC path on Windows.** Windows cannot lock a file on a share,
  so `lmi schedule` **refuses** a UNC working directory with exit 2 and points at
  the fix — `-s` on a local drive, which lets the working directory stay on the
  share. See [Known limitations](#known-limitations).

For development in a repo-local environment:

```bash
python3 -m venv .venv          # or: virtualenv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

You do not need to install anything to run the test suite — see
[Testing](#testing).

---

## Usage

```
lmi schedule "<prompt or prompt-file>" [-t "YYYY-MM-DD HH:MM"] [-i minutes]
             [-c count] [-d workdir] [-f "flags"] [-l logfolder]
             [-s statefile] [-r]
```

Run `lmi --help` for the list of commands, and `lmi schedule --help` for the
authoritative flag list.

### Options

| Option | Meaning |
|---|---|
| `<prompt>` | **Mandatory, and the only mandatory parameter.** Either the prompt text itself, quoted, or the path of a file containing the prompt. If the argument names an existing file it is treated as a file; otherwise as literal text. |
| `-t "YYYY-MM-DD HH:MM"` | Wait until this time before the first iteration. Omitted = start immediately. A time already in the past starts immediately. **Quote it.** |
| `-i <minutes>` | Minutes to wait between iterations. **Requires `-c`.** `-i 0` runs them back to back. The wait starts only after an iteration has *ended*. |
| `-c <count>` | Total number of iterations, must be > 0. **Requires `-i`.** Omit both for a single run. |
| `-d <dir>` | Working directory for claude. Omitted = the current directory. |
| `-f "<flags>"` | Extra claude CLI flags, appended after the always-on defaults. |
| `-l <folder or file>` | Log destination. A folder receives `run-claude-<timestamp>.log`; a path with an extension is used as the log file itself. Omitted = `<workdir>/run-claude-<timestamp>.log`. |
| `-s <file>` | State file. Omitted = `<workdir>/run-claude-state.md`. |
| `-r` | Resume: keep the existing state file instead of backing it up and starting clean. |

`-i` and `-c` are **mutually required** — either both or neither. Each alone exits
2, with a message explaining why. On its own, `-i` says how long to wait but never
when to stop; `-c` says how many iterations but never how long to wait between
them. There is deliberately no unlimited-loop mode: an unattended runner with no
stop condition is a liability.

Every invocation always passes `--allowed-tools=Edit,Write` and
`--add-dir <state file directory>`. Anything you give with `-f` is appended after
those, so `-f "--model opus"` composes rather than replaces.

`-l` and `-s` expand a leading `~` themselves, so a quoted `-s "~/notes/state.md"`
— which the shell leaves untouched — still lands in your home directory instead of
creating a directory literally named `~`.

### Examples

```bash
# one run, inline prompt
lmi schedule "Add unit tests for the parser module"

# 8 iterations, half an hour apart, against another repo, logging to /var/log/lmi
lmi schedule task.md -i 30 -c 8 -d ~/work/myrepo -l /var/log/lmi

# start tonight at 22:00, then hourly for 12 iterations
lmi schedule task.md -t "2026-08-01 22:00" -i 60 -c 12 -f "--model opus"

# continue yesterday's task instead of starting clean
lmi schedule task.md -i 20 -c 5 -r
```

---

## How the iteration loop works

Each iteration composes a prompt file containing, in order:

1. A header stating the run is unattended, and that claude must never ask a
   question or wait for confirmation.
2. The iteration number, start time, working directory and state file path.
3. A numbered **state protocol** (see below).
4. `## CURRENT STATE` — the full current contents of the state file, inline,
   inside a fence long enough that the state file's own code fences cannot close
   it early.
5. `## TASK` — your prompt, or the contents of your prompt file.

That file is fed to claude on stdin, as a list argv with no shell involved:

```
claude -p --allowed-tools=Edit,Write --add-dir <stateDir> <yourFlags>  < promptfile
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
> is nobody to approve, so the write fails. This is why the default is
> `<workdir>/run-claude-state.md`. `lmi` raises an error if the state file cannot
> be written, rather than logging success and looping on an untouched template.

---

## Guarantees

These are treated as invariants, not aspirations, and each is covered by the test
suite.

**Iterations never overlap.** The loop is sequential and the interval wait begins
only after `claude` exits. A second *instance* is blocked by a lock file next to
the state file — `fcntl.flock` on Unix, `msvcrt.locking` on Windows — held open
for the whole run. A second run on the same state file refuses to start and exits
3. The lock cannot go stale: the kernel releases it when the process dies,
however it dies. The lock file itself staying on disk between runs is normal. To
run two tasks in parallel, give them different `-s` state files.

**A failing claude call never fails the runner.** `subprocess.run` is called with
`check=False`, so a non-zero exit is returned rather than raised. The exit code,
the output and the failure are printed and logged with `[ERROR]`, the iteration is
counted as failed, and the loop continues to the next one. Output matching quota,
rate-limit or overload wording is additionally flagged `[QUOTA]`, since hitting a
plan limit mid-loop is the common case and needs to be noticeable in a log you
read the next morning. An exception on the way to claude — an unwritable temp
workspace, a transient `OSError` from `subprocess.run` — is logged with its
traceback and the iteration is recorded as skipped; the loop still continues.

**Nothing ever waits for a keypress.** The prompt arrives on stdin and every wait
is a `time.sleep`.

### Logging

Everything claude prints, plus every runner action, goes to both the console and
the log file: the resolved configuration, each iteration's start, end, exit code
and duration, state file handling, and a final summary of how many iterations ran,
succeeded and failed. A crash inside the runner itself is logged with its full
traceback, not merely printed to a terminal nobody may be watching.

A log file that cannot be written **degrades to console output** with one `[WARN]`
— it never decides the exit code.

### Exit codes

`0` and `2` are **global to every `lmi` command**, not just `schedule`: no future
command may redefine what they mean. The rest are specific to `schedule`.

| Code | Meaning | Scope |
|---|---|---|
| 0 | All iterations completed fine | global |
| 1 | At least one claude call failed (the runner still ran to the end) | `schedule` |
| 2 | Bad parameters, or a missing prerequisite | global |
| 3 | Another run holds the lock on this state file | `schedule` |
| 4 | The runner itself crashed — a bug in `lmi`, not in your task | `schedule` |

---

## Encoding

**Save prompt files as UTF-8.** A UTF-16 file is detected from its byte order mark
and decoded correctly. A file that is neither is refused with exit 2 rather than
being silently mangled. **ANSI** text carries no mark and cannot be distinguished
from UTF-8 at all, so it is not detectable by construction — if your task file
contains Hebrew or any accented character, save it as UTF-8.

The same BOM logic reads the state file, so a state file hand-edited in a Windows
editor is inlined into the next prompt correctly rather than as mojibake.

---

## Known limitations

- **No per-iteration timeout.** A hung `claude` call stalls the loop
  indefinitely. No test can surface this as a failure; it is a missing feature.
- **A quota failure consumes an iteration.** There is no retry with backoff — the
  failure is flagged `[QUOTA]` and the loop moves on to the next iteration.
- **No log rotation.** Each run writes a new timestamped log file.
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

## Project layout

```
lmi/                  the package
  cli.py              top-level argparse parser and command dispatch
  core/               errors and global exit codes, path classification,
                      BOM-aware decoding, the single-instance lock
                      (fcntl / msvcrt), logging
  commands/
    schedule/         the lmi schedule command: config/validation, paths,
                      prompt composition, the state file, the iteration loop
tests/                pytest suite, mirrors the lmi/ tree
docs/install/         per-platform install guides, one file each
docs/superpowers/     the lmi schedule design spec
scripts/              install scripts, all four installing the same wheel:
                      install-linux.sh, install-macos.sh,
                      install-windows.cmd, install-windows.ps1
runner-test-task.md   a deliberately five-step task file, for exercising a
                      real multi-iteration loop end to end
pyproject.toml        packaging: name, entry point, Python >=3.9, pytest
CLAUDE.md             developer handoff: architecture and the behaviours that
                      must not regress
README.md             this file
LICENSE               MIT
```

`runner-test-task.md` is CRLF, as a file that came from Windows. The two Windows
installers (`install-windows.cmd`, `install-windows.ps1`) are currently **LF**,
and the verified Windows install ran that way — worth knowing before anyone
"fixes" them in either direction, since cmd.exe can misparse an LF batch file.

---

## Testing

```bash
python3 -m pytest tests/ -v
```

No install is required first — pytest puts the repository root on `sys.path`,
so the suite runs against a clean checkout. A virtual environment is only
needed to exercise the installed `lmi` console script itself, not to run the
tests. Currently **135 tests, all passing**, in under a second.

The suite never reaches a real `claude`: the `fake_claude` fixture replaces
`PATH` entirely with a temporary directory holding a fake CLI, so no test can
spend quota. That fake is a real subprocess, deliberately, because the argv, the
stdin redirection and the exit code are the parts most worth covering.

What a fake can **never** cover is how the real CLI behaves. The two most
expensive bugs in this project's history — a state file the CLI refused to write
because it sat in `.claude/`, and a false `TASK_STATUS: COMPLETE` match on prose
inside the state file — were both *silent successes* that a fake reported as
healthy. Only a real run caught either. So also run one:

```bash
lmi schedule "Create a file named hello.txt containing the single word OK"
```

Expect exit 0, a `hello.txt`, a `run-claude-<timestamp>.log`, and a
`run-claude-state.md` that Claude has actually rewritten. If it still reads like
the blank template, the state write was blocked.

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

**The interpreter floor is verified.** The full suite and an end-to-end CLI run
both pass on **CPython 3.9.23** — single run, a loop that stops early on
`TASK_STATUS: COMPLETE`, a failing `claude` call leaving the runner alive at exit
1, quota detection, argument validation, and two concurrent runs where the second
is refused with exit 3. This matters because one real bug was found exactly here:
`Path.write_text(..., newline=...)` needs Python 3.10, so before it was fixed
every run died at the first iteration on 3.9. A syntax-level check cannot catch a
parameter added in a later version — only running the older interpreter can.

So: the **3.9 floor** is tested. **Linux** and **Windows** are tested. **macOS**
is not.

### Still to verify

Two measurements have not been taken. Neither blocks use of `lmi schedule`; both
are named so nobody mistakes reasoning for evidence.

1. **A real multi-iteration loop against the actual `claude` CLI.** The
   single-iteration half passes: a real run against `~/.local/bin/claude`
   (v2.1.221) completed in 25 seconds with exit 0, the requested file created,
   the state file rewritten by Claude to `TASK_STATUS: COMPLETE` on line 1, and
   the loop stopping early on it. What is still outstanding is the multi-iteration
   case, which is what proves state carries forward. Use `runner-test-task.md`,
   the deliberately five-step task file in this repository, with `-i 1 -c 5`.
2. **A Windows Task Scheduler run with "run whether user is logged on or not."**
   The install route targets a real `lmi.exe` with the interpreter path built in,
   which removes two of the three things that could fail there — no `python`
   lookup on PATH, and no `cmd.exe` shim — but that is reasoning, not a
   measurement. The remaining unknown is whether the task's own environment
   resolves the `.exe` and its interpreter. Note credentials are per-user: the
   scheduled task must run as the user who did `claude auth login`.

---

## License

MIT — see [LICENSE](LICENSE). Use it, adapt it, redistribute it; just keep the
copyright notice.
