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

None of these are scheduled work. If you want one, say so before building it.

---

## License

MIT — see [LICENSE](LICENSE). Use it, adapt it, redistribute it; just keep the
copyright notice. No warranty.
