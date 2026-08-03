# lmi — design (scoped to `lmi schedule`)

**Date:** 2026-08-03
**Status:** approved, not yet implemented

`lmi` is a Python CLI tool with subcommands. This spec covers the tool's skeleton
and its first command, `lmi schedule`, which runs the Claude Code CLI unattended
in a foreground loop — the job `run-claude.bat` does today.

Further commands (`lmi install`, `lmi replace-config`) are explicitly **out of
scope** here. The skeleton is specified so they can be added later without
redesign, but nothing about them is designed now.

---

## 1. Goal and non-goals

**Goal.** One cross-platform implementation, installed as a `lmi` console script,
that replaces both `run-claude.bat` and the paused bash port. `lmi schedule`
reproduces the `.bat`'s command line, exit codes and state-file protocol.

**Non-goals.**

- No plugin system. Commands are in-tree; there is no third-party extension
  mechanism. The registry (section 3) is where one would go if ever wanted.
- No design for `install` or `replace-config`.
- No new runner features. Per-iteration timeout, quota retry with backoff and log
  rotation stay absent, exactly as in the `.bat`.
- No third-party runtime dependencies.

**Replacement, and the gate on it.** `lmi` is intended to replace
`run-claude.bat`. It does not replace it *on merge*: the `.bat` stays in the
repository until the verification in section 10 passes, because `lmi` trades the
`.bat`'s zero-dependency property for a Python dependency, and the risk lands
precisely on unattended scheduled runs.

The half-finished bash port (branch `worktree-run-claude-sh`, Tasks 1–4 of
`docs/superpowers/plans/2026-08-03-run-claude-sh.md`, 23 tests green) is
abandoned. Its findings are carried into section 7.

---

## 2. Platforms and prerequisites

- **Python 3.9 or newer**, stdlib only at runtime. 3.9 costs nothing here and
  keeps a stock macOS `python3` usable.
- **Linux, macOS, Windows** — cmd, PowerShell, bash and zsh. The console script
  makes `lmi` a real command on all of them.
- `pytest` is a development extra, never a runtime requirement.

---

## 3. Package structure

Each command is a self-contained package. Adding a command means adding a sibling
directory and one registry line; no shared file is edited.

```
pyproject.toml                  console script: lmi = "lmi.cli:main"
lmi/
  __init__.py                   __version__
  __main__.py                   `python -m lmi`
  cli.py                        top-level parser + dispatch, nothing else
  core/                         shared and command-agnostic ONLY
    __init__.py
    errors.py                   LmiError, exit-code constants
    log.py                      Logger: one line to console and to the log file
    lock.py                      cross-platform single-instance lock
  commands/
    __init__.py                 COMMANDS registry, one line per command
    schedule/
      __init__.py               NAME, HELP, add_arguments(), run()
      config.py                 Config dataclass + validation
      paths.py                  log and state path resolution
      state.py                  template, backup/resume, check_complete
      prompt.py                 per-iteration prompt composition
      runner.py                 the loop and the claude invocation
tests/
  test_cli.py
  commands/schedule/test_*.py   tests live with their command
```

**The command contract.** Four names per command, and `cli.py` knows nothing
else:

```python
NAME = "schedule"
HELP = "Run Claude Code unattended, looping in the foreground"

def add_arguments(parser: argparse.ArgumentParser) -> None: ...
def run(args: argparse.Namespace) -> int: ...
```

`cli.py` walks `COMMANDS`, creates one subparser per command by calling
`add_arguments`, dispatches to `run`, and converts an uncaught `LmiError` into its
exit code. Adding a command requires no change to `cli.py`.

**Explicit registry, not auto-discovery.** `commands/__init__.py` imports each
command into a list. `pkgutil` discovery would make `--help` ordering
non-deterministic, import every command on every startup, and turn a typo into a
silently missing command. One line per command is cheaper than any of that.

**`core/` discipline rule.** A module moves into `core/` when it has a *second*
consumer, never in anticipation of one. This is the known failure mode of
feature-folder layouts. Concretely: `paths.py` stays inside `schedule/` because
the four log-resolution rules are schedule's semantics, not general path handling;
`lock.py` and `log.py` start in `core/` only because a future `install` plausibly
needs both.

**Validation belongs to the command, not to `cli.py`.** Each command validates its
own arguments in its own `config.py`. `cli.py` stays pure parsing and dispatch,
which is what keeps it stable as commands accumulate.

---

## 4. Exit codes

Fixed now, before a second command exists to disagree:

| Code | Meaning | Scope |
|---|---|---|
| `0` | success | **global** — every command |
| `2` | usage error (bad arguments) | **global** — every command |
| other | command-specific, documented per command | per command |

`lmi schedule` therefore defines:

| Code | Meaning |
|---|---|
| `0` | every iteration succeeded |
| `1` | at least one `claude` call failed |
| `2` | bad parameters |
| `3` | another run holds the lock |
| `4` | the runner itself failed — a bug in `lmi` |

A future command may define its own `1`, `3`, `4`; only `0` and `2` are reserved.

`4` is distinct from `1` on purpose: "claude reported a problem" and "the runner
crashed" call for different responses, and collapsing them would hide the second
behind the first.

---

## 5. `lmi schedule` command line

Identical letters and meanings to `run-claude.bat`, so the existing README and
habits transfer, and a state file written by either tool works in the other.

```
lmi schedule "<prompt or prompt-file>" [-t "YYYY-MM-DD HH:MM"] [-i minutes]
             [-c count] [-d workdir] [-f "flags"] [-l logfolder]
             [-s statefile] [-r]
```

| Param | Meaning |
|---|---|
| positional | **Mandatory.** Prompt text, or the path of a file containing it. |
| `-t` | Start time, `YYYY-MM-DD HH:MM`. Omitted = start now. |
| `-i` | Minutes between iterations. **Requires `-c`.** `0` = back to back. |
| `-c` | Total iterations. **Requires `-i`.** Must be > 0. |
| `-d` | Working directory for claude. Omitted = the invocation directory. |
| `-f` | Extra claude flags, appended after the defaults. |
| `-l` | Log folder, or a full log file path. |
| `-s` | State file. |
| `-r` | Resume: keep the existing state file instead of backing it up. |

Defaults: state file `<workdir>/run-claude-state.md`; log
`<workdir>/run-claude-<timestamp>.log`; flags `--allowed-tools=Edit,Write` first,
then `--add-dir <stateDir>`, then the user's `-f` flags.

`-i` and `-c` are mutually required — either alone exits 2.

**A prompt beginning with `-`** is disambiguated with the standard `--`
separator: `lmi schedule -- "-starts with a dash"`.

**`-t` must be quoted. This is a deliberate, documented deviation.** The `.bat`
tolerates `-t 2026-08-05 22:00` as two unquoted tokens. `lmi` requires
`-t "2026-08-05 22:00"` and rejects the two-token form with a clear usage error.
Supporting it would mean `nargs="+"` on `-t`, which is greedy: in
`lmi schedule -t "2026-08-05 22:00" "my prompt"` it would swallow the prompt into
the time value. A confusing silent mis-parse is worse than requiring a quote, so
the greedy form is rejected outright.

**File names keep the `run-claude-` prefix during the transition** — state file
`run-claude-state.md`, log `run-claude-<timestamp>.log`, lock `run-claude.lock`.
This is what makes a state file interchangeable with the `.bat`'s while both
exist. Once the `.bat` is retired under section 10 these names become a fossil;
renaming them to an `lmi-` prefix is a deliberate follow-up, not part of this
spec, and it would be a breaking change for anyone with a state file in flight.

**Two `.bat` hazards that argparse removes for free**, worth recording so nobody
reintroduces a workaround for them:

- `-i 0` versus "`-i` not given" needs no sentinel. `default=None` distinguishes
  them, so the `.bat`'s `INTERVAL_GIVEN` flag has no counterpart.
- `-c 008` needs no base-10 normalisation. `int("008")` is 8 in Python; there is
  no octal interpretation to defend against.

---

## 6. Behaviour

**The three invariants carry over unchanged.**

1. **Iterations never overlap.** The loop is sequential and the interval is
   measured from the end of the previous iteration. A second instance is refused
   by the lock.
2. **A failing claude call never fails the runner.** `subprocess.run(...)` with
   the default `check=False` returns a non-zero code rather than raising, so this
   holds by construction — there is no `set -e` equivalent to get wrong. The exit
   code and output are logged, quota wording is flagged `[QUOTA]`, the loop
   continues.
3. **Nothing waits for a keypress.** The prompt arrives on redirected stdin;
   waits use `time.sleep`.

**Invoking claude.**

```python
subprocess.run(
    [claude, "-p", "--allowed-tools=Edit,Write", "--add-dir", str(state_dir),
     *shlex.split(user_flags)],
    stdin=prompt_fh, stdout=out_fh, stderr=subprocess.STDOUT,
    cwd=str(work_dir),
)
```

A list argv with no shell. `.bat` landmines 2, 3, 4, 9 and 10 are structurally
impossible: there is no second parser to confuse, so no quoting to get wrong.
`-f` splits with `shlex.split`, which respects quotes.

**Locking.** OS-level file locks — `fcntl.flock` on Unix, `msvcrt.locking` on
Windows — behind one function in `core/lock.py`. This reproduces the `.bat`'s
handle-9 semantics: the OS releases the lock when the process dies, so **there is
no stale-lock problem and no PID logic at all.** `.bat` landmine 7 has no
counterpart and the bash port's mkdir-plus-PID scheme is not needed.

The lock file is `<stateDir>/run-claude.lock` — deliberately the same path the
`.bat` uses, so that during the transition period a `.bat` run and an `lmi` run
contend for the same state file rather than silently both proceeding. This
exclusion is **best-effort across the two tools**: the `.bat` holds an exclusive
open while `lmi` takes a byte-range lock, and those two mechanisms do not reliably
block each other in both directions. Within `lmi` it is exact. The asymmetry is
acceptable because the transition is short and ends when the `.bat` is retired.

**State protocol.** Identical to the `.bat` apart from the tool's own name: the
unattended header, iteration number, state-file path, the numbered protocol, the
current state file inline under `## CURRENT STATE`, then the task under `## TASK`.
The state-file template is likewise identical. `run-claude.bat`'s
`:write_prompt_head`, `:write_prompt_tail` and `:write_state_template` are the
authoritative source for the literal text.

**The one substitution.** That text names the tool in three places — "You were
started by the script run-claude.bat with the -p flag", "See the TASK section of
the prompt supplied by run-claude.bat", and "state file created by run-claude.bat
on <time>". `lmi` says `lmi schedule` in all three. Claiming otherwise would tell
claude something false about its own invocation. This does not affect state-file
interoperability, which depends only on the `TASK_STATUS` first line and the
section headings.

**Completion check.** Read **line 1 only**, strip a leading BOM, and match
`^\s*TASK_STATUS:\s*COMPLETE\b`. Python's `re` supports `\b`, so this is exactly
the `.bat`'s PowerShell regex — no boundary approximation. This is landmine 14:
claude routinely restates the protocol sentence inside the state file, so a
whole-file search stops the loop after one iteration while reporting success. Do
not widen it.

**The state file must not sit inside a `.claude` directory.** Landmine 13: the CLI
treats that directory as sensitive and refuses to write there unattended, and the
failure is silent — the runner exits 0 while the state file stays the untouched
template, so the loop repeats iteration 1 forever. The default path is outside
`.claude/`; a `-s` path inside one is the user's problem, as with the `.bat`.

**Encoding.** The prompt file is read as bytes and its BOM sniffed: a UTF-8 BOM
decodes as `utf-8-sig`; a UTF-16 BOM **decodes correctly**; anything else is
decoded as UTF-8, and a `UnicodeDecodeError` becomes a clear usage error naming
the file. This genuinely fixes landmine 15 rather than warning about it — the
`.bat` could only detect UTF-16 and mangle it. ANSI text remains undetectable by
construction, as it carries no BOM; that limit is unchanged and unfixable. All
files are written `encoding="utf-8", newline="\n"`.

**Logging.** Same format as the `.bat`: plain lines, no per-line timestamps, the
same `[WARN]` / `[ERROR]` / `[QUOTA]` tags, written to both console and the log
file. `core/log.py` owns this.

**Time.** `datetime.strptime` for `-t` and `time.sleep` for waits. `.bat` landmine
11 — PowerShell for all date arithmetic — has no counterpart, and neither does the
bash port's GNU/BSD `date` branch. There is no platform-specific time code.

---

## 7. Requirements inherited from the bash port's reviews

Four behaviours the `.bat` has that its prose documentation omits. Each was found
by code review during the abandoned bash port, and each would otherwise be a
latent divergence here.

1. **Missing parent directories are created, not rejected.** The `.bat` does
   `mkdir "%STATE_DIR%."` and fails only if the directory is still absent
   afterwards. The same applies to the log file's parent.
2. **`resolve_log` has four rules, in order:** an existing directory → folder; a
   trailing path separator → folder not yet created; a basename with an extension
   → the log file itself; **otherwise → folder.** An extension-less path that does
   not exist yet is a directory, not a log file. "Has an extension" means a dot
   after the first character, so `.hidden` does not count.
3. **A failed state-file backup does not clobber the file.** If the backup cannot
   be made, log `[WARN]` and reuse the existing state file as is, rather than
   overwriting it with a fresh template.
4. **The completion check's trailing boundary is `\b`, not "whitespace or end of
   line".** `TASK_STATUS: COMPLETE.` counts as complete; `TASK_STATUS: COMPLETED`
   does not.

---

## 8. Two `.bat` gaps that are fixed rather than cloned

`lmi` replaces the `.bat`, so there is no second implementation to stay
bug-compatible with, and both of these are silent failures of the kind this
project has already paid for once.

1. **A failed state-file write is reported.** The `.bat`'s
   `:write_state_template` uses bare redirects with no error check, so a state
   file that cannot be written still logs "created new" and the run proceeds to
   loop forever. `lmi` raises a clear error instead. This is landmine 13's failure
   shape, and leaving it in place would be knowingly shipping it.
2. **Runner-level diagnostics reach the log.** The `.bat` captures its own stderr
   to a file and appends it under `[WARN] The runner itself reported these
   messages on stderr:`. In Python the equivalent is simpler and better: the
   command wraps its work, and an unexpected exception is logged with its
   traceback tagged `[ERROR]` before exiting non-zero. Nothing the runner reports
   is lost from the log.

---

## 9. Testing

`pytest`, as a development extra. Tests live beside the command they cover, under
`tests/commands/schedule/`.

**Scope: lean.** Smoke coverage of the happy path plus every argument-validation
error, rather than a port of the `.bat` suite's 43 cases. Roughly 18 of those
cases only exercised cmd.exe quoting quirks that cannot fail in Python, so
mirroring them would produce tests incapable of failing.

**Two tests are mandatory even in a lean suite**, because each maps to a bug that
actually happened and cost real time, and each failed silently:

1. **The landmine-14 prose fixture.** A state file whose line 1 says
   `TASK_STATUS: IN_PROGRESS` while `TASK_STATUS: COMPLETE` appears further down
   must **not** stop the loop. Re-introducing a whole-file search must turn this
   test red.
2. **A failed state-file write.** An unwritable state path must produce a clear
   error, not a logged success followed by an endless loop.

Also covered at smoke level: `-i` without `-c` and vice versa, a non-numeric or
zero `-c`, a malformed `-t`, a non-existent `-d`, a prompt argument that is a
directory, the loop running `-c` times with `-i 0`, early stop on a line-1
`COMPLETE`, a non-zero claude exit leaving the runner alive with exit 1, quota
wording producing `[QUOTA]`, `-l` as both folder and file, `-r` versus the backup
path, and lock contention giving exit 3.

**No real `claude` may be invoked.** Tests point `lmi` at a fake executable on a
temporary `PATH`, and the suite must fail loudly rather than fall through to a
real CLI — a real `claude` exists on the development machine and would spend real
quota.

---

## 10. Verification before the `.bat` is retired

Two things no unit test can settle.

1. **A real end-to-end run on Linux** against the actual `claude` CLI: one single
   iteration, then a multi-iteration loop that reaches `TASK_STATUS: COMPLETE`.
   Landmines 13 and 14 were both found this way and neither would have been caught
   by a fake CLI.
2. **A scheduled-task run on Windows.** `lmi` is installed as a `pip`-generated
   console script, and the development machine's Python is a Microsoft Store
   install — per-user, reached through an App Execution Alias, with no `py.exe`
   launcher. Whether that shim resolves under Task Scheduler with "run whether
   user is logged on or not" is unverified. **If it does not, that is a finding
   about installation, not about this design, and `run-claude.bat` stays until it
   is resolved.**

**macOS is unverified** during implementation, as development happens on Linux.
Unlike the bash port there is no platform-specific code to worry about — no
`date` branch, and locking is one stdlib call per platform — but the `msvcrt`
branch and the console-script installation are both untested outside Linux. Treat
macOS and Windows support as intended rather than tested, and say so in any status
report. The user will exercise both separately.

---

## 11. Open questions

None. The decisions that were open — CLI surface, packaging, the fate of the two
existing runners, test depth, and package structure — were settled during
brainstorming: the `.bat`'s flags verbatim, a `pyproject.toml` console script,
`lmi` replaces both runners subject to section 10, a lean suite with two mandatory
tests, and the vertical-slice command layout of section 3.
