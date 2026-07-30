# run-claude.sh — design

**Date:** 2026-07-30
**Status:** approved, not yet implemented

A Linux and macOS bash port of `run-claude.bat`. Same principle: run the Claude
Code CLI unattended, on a schedule, carrying progress between iterations through
a state file, without dying because one `claude` call failed.

---

## 1. Goal and non-goals

**Goal.** A single-file bash script, `run-claude.sh`, that is a *strict clone* of
`run-claude.bat`: the same flags, the same semantics, the same exit codes, the
same state-file protocol, and the same log format. A state file written by one
runner can be resumed by the other.

**Non-goals.**

- No new features. Anything absent from the `.bat` — per-iteration timeout,
  quota retry with backoff, log rotation — stays absent here too. If one is
  wanted later it is added to *both* runners, per section 7.
- No Windows support. The `.bat` covers Windows natively; Git Bash is out of
  scope.
- No shared implementation between the two scripts. Batch and bash have no
  common subset worth generating from; they are independent twins.

---

## 2. Platforms

Linux and macOS, bash 4.0 or newer.

All platform-specific code lives in **one helper**, `to_epoch`, plus the probe
that selects its branch. Everything else runs identically on both. Two decisions
produce that:

**Locking uses `mkdir`, not `flock`.** `flock` is absent on macOS. `mkdir` is
atomic on every POSIX filesystem, so it gives one mechanism for both platforms
with no branching. See section 5.

**Date parsing branches once.** GNU `date -d` and BSD `date -j -f` genuinely
differ and there is no portable third option. The flavour is probed once at
startup and cached:

```bash
if date -d @0 +%s >/dev/null 2>&1; then DATE_FLAVOUR=gnu; else DATE_FLAVOUR=bsd; fi

to_epoch() {                       # "YYYY-MM-DD HH:MM" -> epoch seconds
  if [[ $DATE_FLAVOUR == gnu ]]; then
    date -d "$1" +%s
  else
    date -j -f "%Y-%m-%d %H:%M" "$1" +%s
  fi
}
```

Computing the epoch arithmetically in pure bash was considered and rejected: it
is roughly twenty lines of civil-calendar arithmetic that no reviewer can verify
by reading, versus four obvious lines here.

---

## 3. Interface

Identical to the `.bat`. The README documents it once for both runners.

```
run-claude.sh "<prompt or prompt-file>" [-t "YYYY-MM-DD HH:MM"] [-i minutes]
              [-c count] [-d workdir] [-f "flags"] [-l logfolder]
              [-s statefile] [-r] [-h]
```

| Param | Meaning |
|---|---|
| positional | **Mandatory.** Prompt text, or the path of a file containing the prompt. |
| `-t` | Target start time, `YYYY-MM-DD HH:MM`. Omitted = start immediately. Accepted unquoted as two tokens, matching the `.bat`. |
| `-i` | Minutes between iterations. **Requires `-c`.** `-i 0` runs them back to back. |
| `-c` | Total iterations. **Requires `-i`.** Must be > 0. |
| `-d` | Working directory. Omitted = the invocation directory. |
| `-f` | Extra claude flags, appended after the defaults. |
| `-l` | Log folder or full log file path. Omitted = `<workdir>/run-claude-<timestamp>.log`. |
| `-s` | State file. Omitted = `<workdir>/run-claude-state.md`. |
| `-r` | Resume: keep the existing state file instead of backing it up. |
| `-h` | Usage, exit 0. |

Defaults: `--allowed-tools=Edit,Write` is always passed first, then `-f` flags.

**Exit codes**, identical to the `.bat`: `0` all iterations fine, `1` at least
one claude call failed, `2` bad parameters, `3` another run holds the lock.

`-i` and `-c` are mutually required; either alone exits 2.

---

## 4. Structure

One file at the repository root. Sections in the **same order as the `.bat`**, so
the two can be read side by side and a "change both" edit lands in the
corresponding place in each:

```
1 defaults        2 parse args      3 validate        4 resolve paths
5 lock            6 header + state  7 wait for start  8 main loop
9 functions
```

Functions keep the `.bat`'s label names: `run_once`, `build_prompt`,
`prepare_state`, `wait_target`, `log`, `check_complete`, `resolve_log`,
`flush_stderr`, `cleanup_tmp`, `warn_prompt_encoding`, `next_run_time`.

**`set -e` must not be used.** It would abort the runner on the first failing
`claude` call, violating invariant 2 in section 6. The script uses `set -uo
pipefail` and captures `$?` explicitly around the claude invocation. This is the
bash counterpart of the `.bat`'s `cmd /c` isolation and is commented as such in
the source, so it is not "hardened" away later.

The claude invocation:

```bash
pushd "$WORK_DIR" >/dev/null
claude -p --allowed-tools=Edit,Write --add-dir "$STATE_DIR" "${user_flags[@]}" \
       < "$PROMPT_BUILD" > "$OUT_FILE" 2>&1
rc=$?
popd >/dev/null
```

`-f` flags are split into the `user_flags` array with `read -ra`, never `eval`.
Bash quoting is sane, so the `.bat`'s landmines 2, 3, 4, 5, 9 and 10 have no
counterpart here — the prompt still arrives on redirected stdin, which keeps
`$?` as claude's own exit code.

---

## 5. Locking

One mechanism on both platforms. The lock is a *directory* next to the state
file, `run-claude.lock.d/`, containing the owner's PID.

**The name deliberately differs from the `.bat`'s `run-claude.lock`.** If the two
runners ever share a state directory — a WSL setup, or a synced folder — the bash
runner would find the `.bat`'s lock *file* where it expects its own directory,
fail to read `pid` from inside it, conclude the lock is stale, and `rm -rf` a
live Windows runner's lock. Separate names make that impossible. The two runners
then do not exclude each other across platforms, which is acceptable: they cannot
run on the same machine anyway.

```bash
if mkdir "$LOCK_DIR" 2>/dev/null; then
  echo $$ > "$LOCK_DIR/pid"
  trap cleanup EXIT INT TERM
else
  if kill -0 "$(cat "$LOCK_DIR/pid" 2>/dev/null)" 2>/dev/null; then
    exit 3                                  # a live run owns it
  fi
  rm -rf "$LOCK_DIR"                        # stale, retry once
  mkdir "$LOCK_DIR" || exit 3
  echo $$ > "$LOCK_DIR/pid"
  trap cleanup EXIT INT TERM
fi
```

`cleanup` removes the lock directory and the temp workspace, so Ctrl+C leaves
nothing behind. The `.bat` relies on the OS to drop its file handle; the mkdir
lock cannot, hence the trap and the staleness check.

**`.bat` landmine 7 does not carry over, and this is not a regression.** That
landmine forbids PID-based locks because cmd could not determine its own PID —
the lookup returned a transient child that was already dead, so every lock
looked stale. In bash `$$` is exactly this process, so `kill -0` is a sound
liveness test. Recorded here because the code looks like a known-bad pattern and
will otherwise be "fixed" back.

Residual, accepted: a `kill -9` leaves the directory behind until the next run's
staleness check removes it. Self-healing and invisible in practice. Worth one
code path instead of two.

---

## 6. Behaviour to preserve

The three invariants carry over unchanged:

1. **Iterations never overlap.** The script is sequential; the interval is
   measured from the end of the previous iteration. A second instance is refused
   by the lock.
2. **A failing claude call never fails the runner.** Exit code and output are
   logged, quota and rate-limit wording is flagged `[QUOTA]`, the loop continues.
3. **Nothing waits for a keypress.** The prompt is fed on redirected stdin; waits
   use `sleep`.

**State protocol.** Byte-identical to the `.bat`, so state files are portable
between platforms. Each iteration's prompt carries the unattended header, the
iteration number, the state-file path, the numbered protocol, the current state
file inline under `## CURRENT STATE`, then the task under `## TASK`.

**Completion check.** `check_complete` reads **line 1 only** and matches
`^[[:space:]]*TASK_STATUS:[[:space:]]*COMPLETE\b`, stripping a leading UTF-8 BOM
first. This is `.bat` landmine 14 and it applies identically: claude restates the
protocol sentence inside the state file, so a whole-file search stops the loop
after one iteration while reporting success. Do not widen it to the whole file.

**Encoding.** UTF-8 is native here, so landmine 15 largely evaporates — no
codepage conversion happens when the prompt file is concatenated. The UTF-16 BOM
warning is kept anyway, for behavioural parity and because a prompt file may well
have come from Windows. ANSI remains undetectable by construction.

**Logging.** Same format, same `[WARN]` / `[ERROR]` / `[QUOTA]` tags, same
`run-claude-<timestamp>.log` naming, console and file both.

---

## 7. Keeping the two runners in sync

Parity is held by discipline plus three artifacts, not by machinery:

1. **One documented CLI contract** — the option table in the README covers both
   runners.
2. **A shared case list** — a table in `CLAUDE.md` naming all 43 test cases and
   what each asserts. Adding a case means adding the row, then implementing it in
   both suites.
3. **A shared stub contract** — both stubs honour the same variables (below).

Before finishing any change to either runner, classify it: platform-specific
(cmd quoting, PowerShell, `date` flavour, locking) or shared (flags, validation,
state protocol, exit codes, logging). Shared changes go into both scripts and
both suites in the same piece of work.

An automated cross-check was considered and rejected: a Linux machine cannot
execute the `.bat`, so nothing can compare the two runners directly on one host.

---

## 8. Testing

**Framework.** bats-core, vendored at `test/bats/` as a git submodule, with
`bats-support` and `bats-assert`. No root, no package manager, version pinned.
`test/run-tests.sh` is a thin wrapper: it initialises the submodule if needed and
execs bats.

**Layout.**

```
test/run-claude.bats   the bash suite, cases named after the .bat cases
test/bin/claude        the bash stub
test/run-tests.sh      wrapper: submodule init, then exec bats
test/bats/             bats-core submodule
```

**The stub contract is the real coupling point** between the two suites — more
than the case names. `test/bin/claude` honours exactly the variables
`test/bin/claude.cmd` does, with the same meanings:

| Variable | Meaning |
|---|---|
| `STUB_RC` | Exit code to return |
| `STUB_OUT` | Text to print on stdout |
| `STUB_SLEEP` | Seconds to sleep before returning |
| `STUB_STATE` | Text to write into the state file |
| `STUB_STATE_FILE` | Which state file to write |
| `STUB_COMPLETE` | Write `TASK_STATUS: COMPLETE` on line 1 |
| `STUB_COMPLETE_AT` | Only complete on the Nth call |
| `STUB_PROSE` | Line 1 `IN_PROGRESS`, but `COMPLETE` mentioned in prose — the landmine 14 fixture |
| `STUB_DIR` | Where to record calls |
| `STUB_COUNT_FILE` | Call counter |

It records each call as `args-N.txt`, `cmdline-N.txt` and `prompt-N.txt`, the
last being the fully composed prompt, which is otherwise deleted by cleanup.
Unlike the batch stub, `args-N.txt` is accurate here: bash does not split
arguments on `=` or `,`, so the batch suite's caveat about asserting
`--allowed-tools=Edit,Write` against the raw command line does not apply.

**Safety.** The suite rebuilds `PATH` so only the stub is reachable, and aborts
with exit 9 if a real `claude` can still be found. It must never spend real quota.

**Cases.** All 43 from `run-tests.bat`, same names, same assertions. Three need a
note:

- *"working directory containing (x86)"* — meaningless on Linux but harmless, and
  kept so the case lists stay aligned.
- *"inline prompt containing & | < > ( )"* — trivially safe in bash, since the
  caller quotes it. Kept for parity.
- *"-t given unquoted as two tokens"* — the `.bat` tolerates this; the bash parser
  must too.

Two cases are slow (`-t` a minute ahead; `-i 1 -c 2` interval timing) and run only
under `--full`, matching the batch suite.

**Not covered, and no stub can cover it:** how the real CLI behaves. `.bat`
landmines 13 and 14 were both found by real runs. A real single-iteration run and
a real multi-iteration loop must still be done by hand on Linux.

**macOS is unverified.** Development happens on Linux, so the BSD branch of
`to_epoch` is written from the documented `date -j -f` behaviour but never
executed. The user will run the suite on a Mac separately. Until that happens,
treat macOS support as intended rather than tested, and say so in any status
report.

---

## 9. Documentation changes

- **README.md** — a section on the Linux/macOS runner: requirements, install, and
  a note that the option table above applies to both. The project layout block
  gains `run-claude.sh`, `test/run-claude.bats`, `test/bin/claude`,
  `test/run-tests.sh`, `test/bats/`.
- **CLAUDE.md** — the sync rule from section 7, the shared case-list table, the
  shared stub contract, and a short bash-specific notes section recording which
  `.bat` landmines do *not* carry over (2, 3, 4, 5, 9, 10, 11 vanish; 7 is
  explicitly reversed; 13, 14, 15 still apply).
- **.gitignore** — one addition: `run-claude.lock.d/`. The existing
  `run-claude.lock` pattern does not cover the new name. The log, state and
  `*.bak` patterns already apply to the bash runner unchanged.

---

## 10. Open questions

None. The three decisions that were genuinely open — parity level, platform set,
and test framework — were settled during brainstorming: strict clone, Linux plus
macOS, bats-core as a submodule.
