# run-claude.sh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `run-claude.sh`, a Linux and macOS bash runner that is a strict behavioural clone of `run-claude.bat`, with a bats-core test suite mirroring the existing 43 batch cases.

**Architecture:** One self-contained bash script at the repository root, laid out in the same nine sections as the `.bat` so the two can be read side by side. All platform variation is confined to a single `to_epoch` helper. Locking uses an atomic `mkdir` with a PID staleness check, so Linux and macOS share one code path. Tests drive a bash stub CLI that honours the same `STUB_*` contract as the existing batch stub.

**Tech Stack:** bash 4.0+, POSIX coreutils, bats-core (vendored as git submodules), no other dependencies.

**Spec:** `docs/superpowers/specs/2026-07-30-run-claude-sh-design.md`

## Global Constraints

- **bash 4.0 or newer.** No bash-5-only syntax.
- **Linux and macOS only.** Windows is covered by the `.bat`.
- **`set -e` is banned.** Use `set -uo pipefail`. `set -e` would abort the runner on the first failing `claude` call, violating invariant 2.
- **`run-claude.sh` and all `.sh` files use LF line endings** and mode `755`. The `.bat` and `.cmd` files keep CRLF — never convert them.
- **Exit codes:** `0` all iterations fine, `1` at least one claude call failed, `2` bad parameters, `3` another run holds the lock.
- **Three invariants:** iterations never overlap; a failing claude call never fails the runner; nothing ever waits for a keypress.
- **No new features.** Anything absent from the `.bat` stays absent. No per-iteration timeout, no quota retry, no log rotation.
- **The lock directory is `run-claude.lock.d`** — deliberately different from the `.bat`'s `run-claude.lock` file.
- **Default flags** are always `--allowed-tools=Edit,Write`, then `--add-dir "$STATE_DIR"`, then the user's `-f` flags.
- **Default state file** is `<workdir>/run-claude-state.md`. Never inside a `.claude` directory.
- **macOS is unverified** during implementation. Write the BSD branch from documentation; do not claim it is tested.

---

## File Structure

| File | Responsibility |
|---|---|
| `run-claude.sh` | Create. The entire runner. Nine sections mirroring the `.bat`. |
| `test/bin/claude` | Create. Bash stub CLI honouring the `STUB_*` contract. |
| `test/run-claude.bats` | Create. The 43-case suite. |
| `test/run-tests.sh` | Create. Wrapper: init submodules, rebuild PATH, exec bats. |
| `test/bats/`, `test/test_helper/bats-support`, `test/test_helper/bats-assert` | Create. Git submodules. |
| `.gitignore` | Modify. Add `run-claude.lock.d/`. |
| `.gitattributes` | Create. Pin `*.bat`/`*.cmd` to CRLF and `*.sh` to LF. |
| `README.md` | Modify. Linux/macOS section, layout block. |
| `CLAUDE.md` | Modify. Sync rule, case list, stub contract, bash notes. |

---

## Task 1: Test harness

Nothing can be built test-first until bats runs. This task delivers a working `./test/run-tests.sh` with one passing smoke test.

**Files:**
- Create: `test/run-tests.sh`, `test/bin/claude`, `test/run-claude.bats`
- Create (submodules): `test/bats`, `test/test_helper/bats-support`, `test/test_helper/bats-assert`

**Interfaces:**
- Consumes: nothing.
- Produces: `test/bin/claude` honouring `STUB_RC`, `STUB_OUT`, `STUB_SLEEP`, `STUB_STATE`, `STUB_STATE_FILE`, `STUB_COMPLETE`, `STUB_COMPLETE_AT`, `STUB_PROSE`, `STUB_DIR`, `STUB_COUNT_FILE`. Writes `args-N.txt`, `cmdline-N.txt`, `prompt-N.txt` into `$STUB_DIR`. `test/run-tests.sh [--full]` runs the suite.

- [ ] **Step 1: Add the bats submodules**

```bash
cd /home/shaharz/repo/claude_installer
git submodule add https://github.com/bats-core/bats-core.git test/bats
git submodule add https://github.com/bats-core/bats-support.git test/test_helper/bats-support
git submodule add https://github.com/bats-core/bats-assert.git test/test_helper/bats-assert
```

- [ ] **Step 2: Write the stub CLI**

Create `test/bin/claude`, mode 755:

```bash
#!/usr/bin/env bash
# Fake claude CLI for the test suite. Costs nothing, spends no quota, and can
# be told to misbehave through STUB_* variables. Mirrors test/bin/claude.cmd.
set -uo pipefail

: "${STUB_DIR:=}"
: "${STUB_RC:=0}"
: "${STUB_OUT:=stub claude ran}"
: "${STUB_SLEEP:=0}"
: "${STUB_STATE:=}"
: "${STUB_STATE_FILE:=}"
: "${STUB_COMPLETE:=}"
: "${STUB_COMPLETE_AT:=}"
: "${STUB_PROSE:=}"
: "${STUB_COUNT_FILE:=${STUB_DIR:-/tmp}/count.txt}"

# --- call counter --------------------------------------------------------
n=0
[[ -f $STUB_COUNT_FILE ]] && n=$(<"$STUB_COUNT_FILE")
n=$((n + 1))
printf '%s\n' "$n" > "$STUB_COUNT_FILE"

# --- record how we were called -------------------------------------------
if [[ -n $STUB_DIR ]]; then
  mkdir -p "$STUB_DIR"
  : > "$STUB_DIR/args-$n.txt"
  for a in "$@"; do printf '[%s]\n' "$a" >> "$STUB_DIR/args-$n.txt"; done
  printf '%s\n' "$0 $*" > "$STUB_DIR/cmdline-$n.txt"
  cat > "$STUB_DIR/prompt-$n.txt"        # the composed prompt on stdin
else
  cat > /dev/null
fi

printf '%s\n' "$STUB_OUT"
[[ $STUB_SLEEP != 0 ]] && sleep "$STUB_SLEEP"

# --- optionally rewrite the state file -----------------------------------
write_state() {                          # $1 = first line
  [[ -z $STUB_STATE_FILE ]] && return 0
  {
    printf '%s\n\n' "$1"
    printf '## Goal\n\nstub goal\n\n'
    printf '## Completed\n\n- stub call %s recorded some progress\n\n' "$n"
    printf '## In progress\n\n- nothing\n\n'
    printf '## Next steps\n\n- nothing\n\n'
    printf '## Notes and blockers\n\n'
    [[ -n $STUB_PROSE ]] && printf -- '- remember to write TASK_STATUS: COMPLETE when the whole task is done\n'
    [[ -n $STUB_STATE ]] && printf -- '- %s\n' "$STUB_STATE"
  } > "$STUB_STATE_FILE"
}

if [[ -n $STUB_PROSE ]]; then
  write_state "TASK_STATUS: IN_PROGRESS"
elif [[ -n $STUB_COMPLETE_AT ]]; then
  if (( n >= STUB_COMPLETE_AT )); then write_state "TASK_STATUS: COMPLETE"
  else write_state "TASK_STATUS: IN_PROGRESS"; fi
elif [[ -n $STUB_COMPLETE ]]; then
  write_state "TASK_STATUS: COMPLETE"
elif [[ -n $STUB_STATE_FILE ]]; then
  write_state "TASK_STATUS: IN_PROGRESS"
fi

exit "$STUB_RC"
```

- [ ] **Step 3: Write the runner wrapper**

Create `test/run-tests.sh`, mode 755:

```bash
#!/usr/bin/env bash
# Runs the bash suite.  ./run-tests.sh [--full]
set -uo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

if [[ ! -x $HERE/bats/bin/bats ]]; then
  echo "bats-core is missing. Run:  git submodule update --init --recursive" >&2
  exit 9
fi

# Only the stub may be reachable as `claude`. A real CLI here would spend
# real quota, so refuse to run rather than risk it.
export PATH="$HERE/bin:/usr/bin:/bin"
real=$(command -v claude || true)
if [[ $real != "$HERE/bin/claude" ]]; then
  echo "refusing to run: 'claude' resolves to $real, not the stub" >&2
  exit 9
fi

export RC_FULL=""
[[ ${1:-} == --full ]] && export RC_FULL=1
exec "$HERE/bats/bin/bats" "$HERE/run-claude.bats"
```

- [ ] **Step 4: Write the smoke test**

Create `test/run-claude.bats`:

```bash
#!/usr/bin/env bats

setup() {
  load 'test_helper/bats-support/load'
  load 'test_helper/bats-assert/load'
  REPO="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  RC="$REPO/run-claude.sh"
  WORK="$BATS_TEST_TMPDIR/work"
  export STUB_DIR="$BATS_TEST_TMPDIR/stub"
  export STUB_COUNT_FILE="$STUB_DIR/count.txt"
  mkdir -p "$WORK" "$STUB_DIR"
}

@test "harness: the stub is reachable and records its call" {
  run claude -p --hello
  assert_success
  assert_output --partial "stub claude ran"
  assert [ -f "$STUB_DIR/args-1.txt" ]
}
```

- [ ] **Step 5: Run it and watch it pass**

```bash
git submodule update --init --recursive
chmod 755 test/run-tests.sh test/bin/claude
./test/run-tests.sh
```

Expected: `1 test, 0 failures`.

- [ ] **Step 6: Commit**

```bash
git add .gitmodules test/
git commit -s -m "test: add bats harness and the bash stub CLI"
```

---

## Task 2: Argument parsing and validation

Delivers a script that parses every flag and rejects every bad combination with exit 2. It cannot run claude yet.

**Files:**
- Create: `run-claude.sh`
- Modify: `test/run-claude.bats`

**Interfaces:**
- Consumes: the harness from Task 1.
- Produces: variables `PROMPT_ARG TARGET_TIME INTERVAL_MIN INTERVAL_GIVEN MAX_RUNS WORK_DIR USER_FLAGS LOG_ARG STATE_ARG RESUME_STATE`; functions `die(msg, code)`, `usage()`, `is_number(s)`, `is_dir(path)`.

- [ ] **Step 1: Write the failing tests**

Append to `test/run-claude.bats`:

```bash
@test "no arguments at all" {
  run "$RC"
  assert_failure 2
  assert_output --partial "prompt"
}

@test "-i without -c" {
  run "$RC" "do a thing" -i 5
  assert_failure 2
  assert_output --partial "-i requires -c"
}

@test "-c without -i" {
  run "$RC" "do a thing" -c 3
  assert_failure 2
  assert_output --partial "-c requires -i"
}

@test "-i 0 without -c - the value must not look like 'not given'" {
  run "$RC" "do a thing" -i 0
  assert_failure 2
  assert_output --partial "-i requires -c"
}

@test "-i not a number" {
  run "$RC" "do a thing" -i abc -c 2
  assert_failure 2
}

@test "-c zero" {
  run "$RC" "do a thing" -i 1 -c 0
  assert_failure 2
}

@test "-c not a number" {
  run "$RC" "do a thing" -i 1 -c xyz
  assert_failure 2
}

@test "-t malformed" {
  run "$RC" "do a thing" -t "01/08/2026 22:00"
  assert_failure 2
  assert_output --partial "YYYY-MM-DD HH:MM"
}

@test "-t with no value" {
  run "$RC" "do a thing" -t
  assert_failure 2
}

@test "-d that does not exist" {
  run "$RC" "do a thing" -d "$BATS_TEST_TMPDIR/nope"
  assert_failure 2
}

@test "prompt argument is a directory - landmine 6" {
  run "$RC" "$WORK"
  assert_failure 2
  assert_output --partial "directory"
}

@test "two positional arguments" {
  run "$RC" "first" "second"
  assert_failure 2
}

@test "-h exits 0 and prints usage" {
  run "$RC" -h
  assert_success
  assert_output --partial "run-claude.sh"
}
```

- [ ] **Step 2: Run and verify they fail**

Run: `./test/run-tests.sh`
Expected: 13 failures, all "no such file or directory" — `run-claude.sh` does not exist yet.

- [ ] **Step 3: Write sections 1-3 of the script**

Create `run-claude.sh`, mode 755:

```bash
#!/usr/bin/env bash
# ===========================================================================
#  run-claude.sh - unattended runner for the Claude Code CLI (claude -p)
#
#    run-claude.sh "<prompt or prompt-file>" [-t "YYYY-MM-DD HH:MM"]
#                  [-i minutes] [-c count] [-d workdir] [-f "flags"]
#                  [-l logfolder] [-s statefile] [-r]
#
#  Linux and macOS counterpart of run-claude.bat. Keep the two in step: a
#  change to shared behaviour belongs in both scripts and both test suites.
#
#  NOTE: `set -e` is deliberately NOT used. A failing claude call must never
#  stop the runner - that is the whole point of the tool. Exit codes are
#  captured explicitly instead.
# ===========================================================================
set -uo pipefail

SCRIPT_NAME=run-claude.sh
INVOKE_DIR=$PWD

# --- defaults -------------------------------------------------------------
PROMPT_ARG=""
TARGET_TIME=""
INTERVAL_MIN=0
INTERVAL_GIVEN=""
MAX_RUNS=""
WORK_DIR=""
USER_FLAGS=""
LOG_ARG=""
STATE_ARG=""
RESUME_STATE=0
EXIT_CODE=0
LOG=""

usage() {
  cat <<'EOF'
run-claude.sh - run the Claude Code CLI unattended.

  run-claude.sh "<prompt or prompt-file>" [-t "YYYY-MM-DD HH:MM"]
                [-i minutes] [-c count] [-d workdir] [-f "flags"]
                [-l logfolder] [-s statefile] [-r] [-h]

  <prompt>      Mandatory. The prompt text, or the path of a UTF-8 file
                holding it.
  -t <time>     Start at this time, format YYYY-MM-DD HH:MM. Default: now.
  -i <minutes>  Minutes between iterations. Requires -c. 0 = back to back.
  -c <count>    Number of iterations. Requires -i. Must be > 0.
  -d <dir>      Working directory. Default: the current directory.
  -f "<flags>"  Extra claude flags, appended after --allowed-tools=Edit,Write.
  -l <path>     Log folder, or a full log file path.
                Default: <workdir>/run-claude-<timestamp>.log
  -s <file>     State file. Default: <workdir>/run-claude-state.md
                Must not sit inside a .claude directory: the CLI refuses to
                write there and the loop would silently repeat iteration 1.
  -r            Resume: keep the existing state file instead of backing it up.
  -h            This help.

  The loop stops early when line 1 of the state file says
  TASK_STATUS: COMPLETE. A failing claude call never stops the runner; its
  exit code and output are logged and marked [ERROR], and quota wording is
  marked [QUOTA]. Nothing ever waits for a keypress.

  Exit code: 0 all iterations fine, 1 at least one claude call failed,
  2 wrong parameters, 3 another run holds the lock.
EOF
}

# `say` is console-only, for errors raised before the log file exists.
say() { printf '%s\n' "$*"; }
die() { say "[ERROR] $1"; say "Run $SCRIPT_NAME -h for help."; exit "${2:-2}"; }

is_number()   { [[ $1 =~ ^[0-9]+$ ]]; }
is_date_only(){ [[ $1 =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; }
is_hhmm()     { [[ $1 =~ ^[0-9]{2}:[0-9]{2}$ ]]; }

# ===========================================================================
#  1. Parse arguments
# ===========================================================================
while (( $# )); do
  case $1 in
    -h|--help) usage; exit 0 ;;
    -t) [[ $# -ge 2 ]] || die "-t needs a value in the format YYYY-MM-DD HH:MM"
        TARGET_TIME=$2; shift 2
        # The .bat tolerates an unquoted -t as two tokens. Match that.
        if is_date_only "$TARGET_TIME" && [[ $# -ge 1 ]] && is_hhmm "$1"; then
          TARGET_TIME="$TARGET_TIME $1"; shift
        fi ;;
    -i) [[ $# -ge 2 ]] || die "-i needs a value in minutes"
        INTERVAL_MIN=$2; INTERVAL_GIVEN=1; shift 2 ;;
    -c) [[ $# -ge 2 ]] || die "-c needs a value"
        MAX_RUNS=$2; shift 2 ;;
    -d) [[ $# -ge 2 ]] || die "-d needs a directory"
        WORK_DIR=$2; shift 2 ;;
    -f) [[ $# -ge 2 ]] || die "-f needs a quoted flag string"
        USER_FLAGS=$2; shift 2 ;;
    -l) [[ $# -ge 2 ]] || die "-l needs a folder or a file path"
        LOG_ARG=$2; shift 2 ;;
    -s) [[ $# -ge 2 ]] || die "-s needs a file path"
        STATE_ARG=$2; shift 2 ;;
    -r) RESUME_STATE=1; shift ;;
    -*) die "unknown option: $1" ;;
    *)  [[ -z $PROMPT_ARG ]] || die "unexpected extra argument: $1"
        PROMPT_ARG=$1; shift ;;
  esac
done

# ===========================================================================
#  2. Validate
# ===========================================================================
[[ -n $PROMPT_ARG ]] || die "a prompt, or the path of a file holding it, is required"

if [[ -n $INTERVAL_GIVEN && -z $MAX_RUNS ]]; then
  die "-i requires -c: an unattended loop must have a stop condition"
fi
if [[ -z $INTERVAL_GIVEN && -n $MAX_RUNS ]]; then
  die "-c requires -i: give the interval between iterations too"
fi
if [[ -n $INTERVAL_GIVEN ]]; then
  is_number "$INTERVAL_MIN" || die "-i must be a whole number of minutes, got: $INTERVAL_MIN"
  is_number "$MAX_RUNS"     || die "-c must be a whole number, got: $MAX_RUNS"
  (( MAX_RUNS > 0 ))        || die "-c must be greater than 0"
else
  MAX_RUNS=1
  INTERVAL_MIN=0
fi

if [[ -n $TARGET_TIME ]]; then
  [[ $TARGET_TIME =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9]{2}:[0-9]{2}$ ]] \
    || die "-t must look like YYYY-MM-DD HH:MM, got: $TARGET_TIME"
fi

if [[ -n $WORK_DIR ]]; then
  [[ -d $WORK_DIR ]] || die "working directory does not exist: $WORK_DIR"
  WORK_DIR=$(cd -- "$WORK_DIR" && pwd)
else
  WORK_DIR=$INVOKE_DIR
fi

# Is the prompt a file or literal text? A directory is neither - landmine 6.
[[ -d $PROMPT_ARG ]] && die "the prompt argument is a directory: $PROMPT_ARG"
PROMPT_IS_FILE=0
[[ -f $PROMPT_ARG ]] && PROMPT_IS_FILE=1

command -v claude >/dev/null 2>&1 || die "claude is not on PATH"
```

- [ ] **Step 4: Run and verify they pass**

Run: `chmod 755 run-claude.sh && ./test/run-tests.sh`
Expected: 14 tests, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add run-claude.sh test/run-claude.bats
git commit -s -m "feat: parse and validate run-claude.sh arguments"
```

---

## Task 3: Paths, logging and the temp workspace

**Files:**
- Modify: `run-claude.sh`, `test/run-claude.bats`

**Interfaces:**
- Consumes: Task 2's variables.
- Produces: `STATE_FILE STATE_DIR LOG TMP_DIR`; functions `now()` (sets `NOW_STR`, `NOW_EPOCH`), `timestamp()` (echoes `yyyymmdd-HHMMSS`), `log(msg)`, `resolve_log()`.

- [ ] **Step 1: Write the failing tests**

```bash
@test "-l pointing at a folder" {
  mkdir -p "$WORK/logs"
  run "$RC" "hello" -d "$WORK" -l "$WORK/logs"
  assert_success
  run bash -c "ls '$WORK/logs' | grep -c '^run-claude-.*\.log$'"
  assert_output "1"
}

@test "-l pointing at a file" {
  run "$RC" "hello" -d "$WORK" -l "$WORK/my.log"
  assert_success
  assert [ -f "$WORK/my.log" ]
}

@test "-s a custom state file" {
  # The state file is not written until Task 4. Assert the path resolves.
  run "$RC" "hello" -d "$WORK" -s "$WORK/custom-state.md"
  assert_success
  assert_output --partial "$WORK/custom-state.md"
  refute_output --partial "$WORK/run-claude-state.md"
}

@test "state file and log in a path containing an ampersand" {
  mkdir -p "$WORK/a&b"
  run "$RC" "hello" -d "$WORK/a&b"
  assert_success
  run bash -c "ls '$WORK/a&b'/run-claude-*.log | wc -l"
  assert_output "1"
}

@test "working directory containing a space" {
  mkdir -p "$WORK/two words"
  run "$RC" "hello" -d "$WORK/two words"
  assert_success
}

@test "working directory containing an ampersand" {
  mkdir -p "$WORK/x&y"
  run "$RC" "hello" -d "$WORK/x&y"
  assert_success
}

@test "working directory containing (x86)" {
  # Meaningless on Linux - parentheses are ordinary here. Kept so the two
  # suites stay at 43 matching case names.
  mkdir -p "$WORK/Program Files (x86)"
  run "$RC" "hello" -d "$WORK/Program Files (x86)"
  assert_success
}
```

- [ ] **Step 2: Run and verify they fail**

Run: `./test/run-tests.sh`
Expected: 7 new failures — no log or state file is produced yet.

- [ ] **Step 3: Add sections 3-4 to the script**

Append after validation:

```bash
# ===========================================================================
#  3. Time helpers - the only platform-specific code in this script
# ===========================================================================
if date -d @0 +%s >/dev/null 2>&1; then DATE_FLAVOUR=gnu; else DATE_FLAVOUR=bsd; fi

to_epoch() {                      # "YYYY-MM-DD HH:MM" -> epoch seconds
  if [[ $DATE_FLAVOUR == gnu ]]; then
    date -d "$1" +%s 2>/dev/null
  else
    date -j -f "%Y-%m-%d %H:%M" "$1" +%s 2>/dev/null
  fi
}

now()       { NOW_STR=$(date '+%Y-%m-%d %H:%M:%S'); NOW_EPOCH=$(date +%s); }
timestamp() { date '+%Y%m%d-%H%M%S'; }

# ===========================================================================
#  4. Resolve the state file, the log file and the temp workspace
# ===========================================================================
RUN_TS=$(timestamp)

STATE_FILE=${STATE_ARG:-$WORK_DIR/run-claude-state.md}
STATE_DIR=$(cd -- "$(dirname -- "$STATE_FILE")" 2>/dev/null && pwd) \
  || die "the folder for the state file does not exist: $STATE_FILE"
STATE_FILE="$STATE_DIR/$(basename -- "$STATE_FILE")"

resolve_log() {
  if [[ -z $LOG_ARG ]]; then
    LOG="$WORK_DIR/run-claude-$RUN_TS.log"
  elif [[ -d $LOG_ARG ]]; then
    LOG="${LOG_ARG%/}/run-claude-$RUN_TS.log"
  else
    local d; d=$(dirname -- "$LOG_ARG")
    [[ -d $d ]] || die "the folder for the log file does not exist: $LOG_ARG"
    LOG=$LOG_ARG
  fi
}
resolve_log
: > "$LOG" || die "cannot write the log file: $LOG"

# One line to the console and to the log.
log() { printf '%s\n' "$*"; printf '%s\n' "$*" >> "$LOG"; }

TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/run-claude-$RUN_TS.XXXXXX") \
  || die "cannot create a temp workspace"
cleanup_tmp() { [[ -n ${TMP_DIR:-} && -d $TMP_DIR ]] && rm -rf "$TMP_DIR"; }

# Provisional header. Task 6 replaces these two lines with the full one.
log "State file: $STATE_FILE"
log "Log file  : $LOG"
```

- [ ] **Step 4: Run and verify they pass**

Run: `./test/run-tests.sh`
Expected: 21 tests, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add run-claude.sh test/run-claude.bats
git commit -s -m "feat: resolve paths, logging and the temp workspace"
```

---

## Task 4: State file lifecycle

**Files:**
- Modify: `run-claude.sh`, `test/run-claude.bats`

**Interfaces:**
- Consumes: `STATE_FILE`, `log()`, `now()`.
- Produces: `prepare_state()`, `write_state_template()`, `check_complete()` — exit 0 when line 1 of the state file says COMPLETE.

- [ ] **Step 1: Write the failing tests**

```bash
@test "a second run without -r backs the state up and starts clean" {
  printf 'TASK_STATUS: IN_PROGRESS\nold content\n' > "$WORK/run-claude-state.md"
  run "$RC" "hello" -d "$WORK"
  assert_success
  run bash -c "ls '$WORK'/run-claude-state.md.*.bak | wc -l"
  assert_output "1"
}

@test "-r keeps the existing state file" {
  printf 'TASK_STATUS: IN_PROGRESS\nkeep me\n' > "$WORK/run-claude-state.md"
  run "$RC" "hello" -d "$WORK" -r
  assert_success
  run bash -c "ls '$WORK'/run-claude-state.md.*.bak 2>/dev/null | wc -l"
  assert_output "0"
  run grep -c "keep me" "$WORK/run-claude-state.md"
  assert_output "1"
}
```

- [ ] **Step 2: Run and verify they fail**

Run: `./test/run-tests.sh`
Expected: 2 failures — no backup is made, and `-r` is not honoured.

- [ ] **Step 3: Implement**

```bash
# ===========================================================================
#  5. State file preparation
# ===========================================================================
write_state_template() {
  now
  cat > "$STATE_FILE" <<EOF
TASK_STATUS: IN_PROGRESS

## Goal

See the TASK section of the prompt supplied by $SCRIPT_NAME.
Restate it here in your own words during the first iteration.

## Completed

- nothing yet

## In progress

- nothing yet

## Next steps

- read the task and plan the first chunk of work

## Notes and blockers

- state file created by $SCRIPT_NAME on $NOW_STR
EOF
}

prepare_state() {
  if [[ -f $STATE_FILE ]]; then
    if (( RESUME_STATE )); then
      log "Resuming the existing state file (-r)."
      return 0
    fi
    local bak="$STATE_FILE.$RUN_TS.bak"
    mv -- "$STATE_FILE" "$bak"
    log "Existing state file backed up to: $bak"
  fi
  write_state_template
  log "Fresh state file created: $STATE_FILE"
}

# Is the task finished? FIRST LINE of the state file only.
#
# A whole-file search is wrong here, and the failure is silent. The protocol
# sent to claude says "write TASK_STATUS: COMPLETE on the first line only
# when ...", and claude routinely restates that sentence inside the state
# file - under ## Goal, or as a note to its future self. A file-wide search
# matches that prose and stops the loop after one iteration while line 1
# still says IN_PROGRESS. This is landmine 14 in CLAUDE.md. Do not widen it.
check_complete() {
  [[ -f $STATE_FILE ]] || return 1
  local first
  first=$(head -n 1 -- "$STATE_FILE")
  first=${first#$'\xef\xbb\xbf'}            # strip a UTF-8 BOM
  [[ $first =~ ^[[:space:]]*TASK_STATUS:[[:space:]]*COMPLETE([[:space:]]|$) ]]
}

# Provisional driver. Task 6 replaces this with the loop.
prepare_state
```

Then strengthen the assertion Task 3 had to defer. **Replace** the existing
`"-s a custom state file"` test with its final form — do not add a new case, or
the two suites stop matching at 43:

```bash
@test "-s a custom state file" {
  run "$RC" "hello" -d "$WORK" -s "$WORK/custom-state.md"
  assert_success
  assert [ -f "$WORK/custom-state.md" ]
  assert [ ! -f "$WORK/run-claude-state.md" ]
  run head -n 1 "$WORK/custom-state.md"
  assert_output "TASK_STATUS: IN_PROGRESS"
}
```

- [ ] **Step 4: Run and verify they pass**

Run: `./test/run-tests.sh`
Expected: 23 tests, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add run-claude.sh test/run-claude.bats
git commit -s -m "feat: state file template, backup and resume"
```

---

## Task 5: Prompt composition and the claude invocation

**Files:**
- Modify: `run-claude.sh`, `test/run-claude.bats`

**Interfaces:**
- Consumes: everything above.
- Produces: `build_prompt(outfile)`, `warn_prompt_encoding()`, `run_once()` setting `CLAUDE_RC`.

- [ ] **Step 1: Write the failing tests**

```bash
@test "single run, inline prompt" {
  run "$RC" "write a haiku" -d "$WORK"
  assert_success
  assert_output --partial "stub claude ran"
  assert [ -f "$STUB_DIR/prompt-1.txt" ]
}

@test "the composed prompt carries the protocol and the task" {
  run "$RC" "write a haiku" -d "$WORK"
  assert_success
  run cat "$STUB_DIR/prompt-1.txt"
  assert_output --partial "Unattended automated run"
  assert_output --partial "## State protocol - read this first"
  assert_output --partial "## CURRENT STATE"
  assert_output --partial "## TASK"
  assert_output --partial "write a haiku"
}

@test "prompt read from a file" {
  printf 'do the thing from a file\n' > "$WORK/p.md"
  run "$RC" "$WORK/p.md" -d "$WORK"
  assert_success
  run cat "$STUB_DIR/prompt-1.txt"
  assert_output --partial "do the thing from a file"
}

@test "inline prompt containing & | < > ( )" {
  run "$RC" 'a & b | c < d > e ( f )' -d "$WORK"
  assert_success
  run cat "$STUB_DIR/prompt-1.txt"
  assert_output --partial 'a & b | c < d > e ( f )'
}

@test "-f flags reach the CLI" {
  run "$RC" "hello" -d "$WORK" -f "--verbose --model sonnet"
  assert_success
  run cat "$STUB_DIR/args-1.txt"
  assert_output --partial "[--verbose]"
  assert_output --partial "[--model]"
  assert_output --partial "[sonnet]"
}

@test "the default flags and --add-dir reach the CLI" {
  run "$RC" "hello" -d "$WORK"
  assert_success
  run cat "$STUB_DIR/args-1.txt"
  assert_output --partial "[-p]"
  assert_output --partial "[--allowed-tools=Edit,Write]"
  assert_output --partial "[--add-dir]"
}

@test "a UTF-8 prompt file is carried through byte for byte" {
  printf 'שלום עולם\n' > "$WORK/heb.md"
  run "$RC" "$WORK/heb.md" -d "$WORK"
  assert_success
  run cat "$STUB_DIR/prompt-1.txt"
  assert_output --partial "שלום עולם"
}

@test "a UTF-16 prompt file is reported with [WARN]" {
  printf '\xff\xfeh\x00i\x00' > "$WORK/utf16.md"
  run "$RC" "$WORK/utf16.md" -d "$WORK"
  assert_output --partial "[WARN]"
  assert_output --partial "UTF-16"
}

@test "an inline prompt never triggers the encoding warning" {
  run "$RC" "plain inline text" -d "$WORK"
  assert_success
  refute_output --partial "[WARN]"
}
```

- [ ] **Step 2: Run and verify they fail**

Run: `./test/run-tests.sh`
Expected: 9 failures — claude is never invoked.

- [ ] **Step 3: Implement**

```bash
# ===========================================================================
#  6. Composing the prompt and running claude
# ===========================================================================
warn_prompt_encoding() {
  (( PROMPT_IS_FILE )) || return 0
  local bom; bom=$(head -c 2 -- "$PROMPT_ARG" | od -An -tx1 | tr -d ' \n')
  if [[ $bom == fffe || $bom == feff ]]; then
    log "[WARN] The prompt file looks like UTF-16. Save it as UTF-8:"
    log "[WARN]   $PROMPT_ARG"
  fi
}

build_prompt() {
  local cp=$1
  cat > "$cp" <<EOF
# Unattended automated run

You were started by the script $SCRIPT_NAME with the -p flag.
Nobody is watching the terminal: never ask a question and never wait for
confirmation. Decide on your own and write down what you decided.

Iteration: $ITER_LABEL
Started: $ITER_START_STR
Working directory: $WORK_DIR
State file: $STATE_FILE

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

## CURRENT STATE - $STATE_FILE

\`\`\`markdown
EOF
  [[ -f $STATE_FILE ]] && cat -- "$STATE_FILE" >> "$cp"
  cat >> "$cp" <<'EOF'
```

## TASK

EOF
  if (( PROMPT_IS_FILE )); then
    cat -- "$PROMPT_ARG" >> "$cp"
  else
    printf '%s\n' "$PROMPT_ARG" >> "$cp"
  fi
}

run_once() {
  CLAUDE_RC=0
  local prompt_build="$TMP_DIR/rc-prompt-$ITER.txt"
  local out_file="$TMP_DIR/rc-out-$ITER.txt"

  if ! build_prompt "$prompt_build"; then
    log "[ERROR] Could not build the prompt for this iteration - it was skipped."
    CLAUDE_RC=90
    return 0
  fi

  local user_flags=()
  [[ -n $USER_FLAGS ]] && read -ra user_flags <<< "$USER_FLAGS"

  log "--- claude output ---"
  # The prompt arrives on redirected stdin, which keeps $? as claude's own
  # exit code. No `set -e` here on purpose: a nonzero rc must not end the run.
  (
    cd -- "$WORK_DIR" || exit 91
    claude -p --allowed-tools=Edit,Write --add-dir "$STATE_DIR" \
           "${user_flags[@]}" < "$prompt_build" > "$out_file" 2>&1
  )
  CLAUDE_RC=$?

  if [[ -f $out_file ]]; then
    cat -- "$out_file"
    cat -- "$out_file" >> "$LOG"
  fi
  log "--- end of claude output ---"

  # Make quota, rate limit and overload trouble impossible to miss.
  [[ -f $out_file ]] || return 0
  if grep -qiE 'usage limit|rate.?limit|quota|credit balance|insufficient credit|too many requests|overloaded|exceeded your' -- "$out_file"; then
    log "[QUOTA] *** Possible quota, rate limit or overload problem in the claude output above."
    log "[QUOTA] *** Check your usage before trusting the result of this iteration."
  fi
}

# Provisional driver: one iteration. Task 6 replaces this with the loop, and
# removes the bare `prepare_state` line added in Task 4.
ITER=1
ITER_LABEL="1 of 1"
now; ITER_START_STR=$NOW_STR
warn_prompt_encoding
run_once
```

- [ ] **Step 4: Run and verify they pass**

Run: `./test/run-tests.sh`
Expected: 32 tests, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add run-claude.sh test/run-claude.bats
git commit -s -m "feat: compose the per-iteration prompt and invoke claude"
```

---

## Task 6: The main loop

**Files:**
- Modify: `run-claude.sh`, `test/run-claude.bats`

**Interfaces:**
- Consumes: `run_once()`, `check_complete()`, `prepare_state()`.
- Produces: the run header, the loop, `RUN_COUNT`/`FAIL_COUNT`, the summary, `EXIT_CODE`.

- [ ] **Step 1: Write the failing tests**

```bash
@test "-i 0 -c 3 runs three times" {
  run "$RC" "hello" -d "$WORK" -i 0 -c 3
  assert_success
  run cat "$STUB_COUNT_FILE"
  assert_output "3"
}

@test "early stop when line 1 becomes COMPLETE" {
  export STUB_STATE_FILE="$WORK/run-claude-state.md"
  export STUB_COMPLETE_AT=2
  run "$RC" "hello" -d "$WORK" -i 0 -c 5
  assert_success
  run cat "$STUB_COUNT_FILE"
  assert_output "2"
}

@test "landmine 14 - COMPLETE in prose must NOT stop the loop" {
  export STUB_STATE_FILE="$WORK/run-claude-state.md"
  export STUB_PROSE=1
  run "$RC" "hello" -d "$WORK" -i 0 -c 3
  assert_success
  run cat "$STUB_COUNT_FILE"
  assert_output "3"
}

@test "claude exits 7 - runner survives, keeps looping, exits 1" {
  export STUB_RC=7
  run "$RC" "hello" -d "$WORK" -i 0 -c 2
  assert_failure 1
  assert_output --partial "[ERROR]"
  run cat "$STUB_COUNT_FILE"
  assert_output "2"
}

@test "quota wording is flagged [QUOTA]" {
  export STUB_OUT="Error: you have exceeded your usage limit for today"
  run "$RC" "hello" -d "$WORK"
  assert_output --partial "[QUOTA]"
}

@test "-c 1 with -i 5 must not wait after the only iteration" {
  start=$(date +%s)
  run "$RC" "hello" -d "$WORK" -i 5 -c 1
  assert_success
  (( $(date +%s) - start < 30 ))
}
```

- [ ] **Step 2: Run and verify they fail**

Run: `./test/run-tests.sh`
Expected: 6 failures — the script runs claude once and stops.

- [ ] **Step 3: Implement**

First **delete the provisional drivers**: the bare `prepare_state` line from
Task 4, the `ITER=1 … run_once` block from Task 5, and the two provisional
`log "State file: …"` / `log "Log file  : …"` lines from Task 3. The block below
replaces all three.

```bash
# ===========================================================================
#  7. Run header, then the main loop
# ===========================================================================
now
log "==========================================================================="
log "$SCRIPT_NAME starting at $NOW_STR"
log "Working directory: $WORK_DIR"
log "State file: $STATE_FILE"
log "Log file  : $LOG"
if (( PROMPT_IS_FILE )); then log "Prompt file: $PROMPT_ARG"; else log "Prompt: $PROMPT_ARG"; fi
log "Iterations: $MAX_RUNS"
log "Interval  : $INTERVAL_MIN minute/s"
[[ -n $TARGET_TIME ]] && log "Start time: $TARGET_TIME"
[[ -n $USER_FLAGS ]] && log "Extra flags: $USER_FLAGS"
log "==========================================================================="

warn_prompt_encoding
prepare_state

RUN_COUNT=0
FAIL_COUNT=0
ITER=0

while :; do
  ITER=$((ITER + 1))
  ITER_LABEL="$ITER of $MAX_RUNS"
  now; ITER_START_STR=$NOW_STR

  log ""
  log "--- iteration $ITER_LABEL started $ITER_START_STR ---"

  run_once
  RUN_COUNT=$((RUN_COUNT + 1))

  if (( CLAUDE_RC != 0 )); then
    FAIL_COUNT=$((FAIL_COUNT + 1))
    EXIT_CODE=1
    log "[ERROR] claude exited with code $CLAUDE_RC. The runner continues."
  fi

  if check_complete; then
    log "State file line 1 says TASK_STATUS: COMPLETE - stopping early."
    break
  fi

  (( ITER >= MAX_RUNS )) && break

  if (( INTERVAL_MIN > 0 )); then
    local_secs=$((INTERVAL_MIN * 60))
    now
    log "Next iteration at $(date -d "@$((NOW_EPOCH + local_secs))" '+%Y-%m-%d %H:%M:%S' 2>/dev/null \
        || date -r "$((NOW_EPOCH + local_secs))" '+%Y-%m-%d %H:%M:%S')"
    sleep "$local_secs"
  fi
done

now
log ""
log "==========================================================================="
log "$SCRIPT_NAME finished at $NOW_STR"
log "$RUN_COUNT run/s, $((RUN_COUNT - FAIL_COUNT)) succeeded, $FAIL_COUNT failed."
log "State file: $STATE_FILE"
log "Log file  : $LOG"
log "==========================================================================="
(( FAIL_COUNT != 0 )) && log "[ERROR] $FAIL_COUNT iteration/s failed - search the log for [ERROR] and [QUOTA]."

cleanup_tmp
exit "$EXIT_CODE"
```

- [ ] **Step 4: Run and verify they pass**

Run: `./test/run-tests.sh`
Expected: 38 tests, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add run-claude.sh test/run-claude.bats
git commit -s -m "feat: the iteration loop, early completion and failure counting"
```

---

## Task 7: Locking

**Files:**
- Modify: `run-claude.sh`, `test/run-claude.bats`

**Interfaces:**
- Consumes: `STATE_DIR`, `die()`.
- Produces: `LOCK_DIR`, `acquire_lock()`, `cleanup()` (trapped on `EXIT INT TERM`).

- [ ] **Step 1: Write the failing tests**

```bash
@test "a second run on the same state file is refused with exit 3" {
  export STUB_SLEEP=3
  "$RC" "hello" -d "$WORK" &
  first=$!
  sleep 1
  run "$RC" "hello" -d "$WORK"
  assert_failure 3
  wait "$first"
}

@test "the lock is free again once the holder has finished" {
  run "$RC" "hello" -d "$WORK"
  assert_success
  assert [ ! -d "$WORK/run-claude.lock.d" ]
  run "$RC" "hello" -d "$WORK"
  assert_success
}
```

- [ ] **Step 2: Run and verify they fail**

Run: `./test/run-tests.sh`
Expected: the contention test fails — the second run succeeds instead of exiting 3.

- [ ] **Step 3: Implement**

Insert immediately after `TMP_DIR` is created in Task 3's block:

```bash
# ===========================================================================
#  Single-instance lock
# ===========================================================================
# mkdir is atomic on every POSIX filesystem, so it works the same on Linux
# and macOS. flock is not used: macOS does not ship it, and one code path
# beats two.
#
# CLAUDE.md landmine 7 forbids PID-based locks. That ban does NOT apply here
# and this is not a regression. It exists because cmd cannot determine its
# own PID - the lookup returns a transient child that is already dead, so
# every lock looks stale. In bash, $$ is exactly this process, so `kill -0`
# is a sound liveness test.
#
# The name differs from the .bat's `run-claude.lock` on purpose. If the two
# runners ever share a state directory, this one must not mistake the .bat's
# lock FILE for its own stale directory and delete a live Windows lock.
LOCK_DIR="$STATE_DIR/run-claude.lock.d"

cleanup() {
  [[ -n ${LOCK_DIR:-} && -f $LOCK_DIR/pid && $(cat "$LOCK_DIR/pid" 2>/dev/null) == "$$" ]] \
    && rm -rf -- "$LOCK_DIR"
  cleanup_tmp
}

acquire_lock() {
  if mkdir -- "$LOCK_DIR" 2>/dev/null; then
    printf '%s\n' "$$" > "$LOCK_DIR/pid"
    trap cleanup EXIT INT TERM
    return 0
  fi
  local owner; owner=$(cat "$LOCK_DIR/pid" 2>/dev/null || true)
  if [[ -n $owner ]] && kill -0 "$owner" 2>/dev/null; then
    say "[ERROR] another run (pid $owner) is working on this state file."
    say "        state file: $STATE_FILE"
    exit 3
  fi
  rm -rf -- "$LOCK_DIR"
  mkdir -- "$LOCK_DIR" 2>/dev/null || { say "[ERROR] cannot take the lock: $LOCK_DIR"; exit 3; }
  printf '%s\n' "$$" > "$LOCK_DIR/pid"
  trap cleanup EXIT INT TERM
}
acquire_lock
```

- [ ] **Step 4: Run and verify they pass**

Run: `./test/run-tests.sh`
Expected: 40 tests, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add run-claude.sh test/run-claude.bats
git commit -s -m "feat: single-instance lock via an atomic mkdir"
```

---

## Task 8: Waiting for the target start time

**Files:**
- Modify: `run-claude.sh`, `test/run-claude.bats`

**Interfaces:**
- Consumes: `to_epoch()`, `log()`.
- Produces: `wait_target()`.

- [ ] **Step 1: Write the failing tests**

The last two are slow and run only under `--full`, matching the batch suite.

```bash
@test "-t in the past starts immediately" {
  run "$RC" "hello" -d "$WORK" -t "2020-01-01 00:00"
  assert_success
  run cat "$STUB_COUNT_FILE"
  assert_output "1"
}

@test "-t given unquoted as two tokens" {
  run "$RC" "hello" -d "$WORK" -t 2020-01-01 00:00
  assert_success
  run cat "$STUB_COUNT_FILE"
  assert_output "1"
}

@test "-t about one minute ahead really waits" {
  [[ -n ${RC_FULL:-} ]] || skip "slow: run with --full"
  target=$(date -d '+70 seconds' '+%Y-%m-%d %H:%M' 2>/dev/null \
           || date -v+70S '+%Y-%m-%d %H:%M')
  start=$(date +%s)
  run "$RC" "hello" -d "$WORK" -t "$target"
  assert_success
  (( $(date +%s) - start >= 55 ))
}

@test "-i 1 -c 2 waits a minute measured from the end of iteration 1" {
  [[ -n ${RC_FULL:-} ]] || skip "slow: run with --full"
  start=$(date +%s)
  run "$RC" "hello" -d "$WORK" -i 1 -c 2
  assert_success
  elapsed=$(( $(date +%s) - start ))
  (( elapsed >= 55 && elapsed < 120 ))
}
```

- [ ] **Step 2: Run and verify they fail**

Run: `./test/run-tests.sh --full`
Expected: the unquoted `-t` case fails (two tokens are not joined), and the wait cases fail because no waiting happens.

- [ ] **Step 3: Implement**

Insert just before the main loop:

```bash
wait_target() {
  [[ -n $TARGET_TIME ]] || return 0
  local target_epoch; target_epoch=$(to_epoch "$TARGET_TIME")
  [[ -n $target_epoch ]] || die "could not understand -t: $TARGET_TIME"
  now
  local wait_secs=$(( target_epoch - NOW_EPOCH ))
  if (( wait_secs <= 0 )); then
    log "Start time $TARGET_TIME has already passed - starting now."
    return 0
  fi
  log "Waiting until $TARGET_TIME ($wait_secs seconds)."
  sleep "$wait_secs"
}
wait_target
```

- [ ] **Step 4: Run and verify they pass**

Run: `./test/run-tests.sh` then `./test/run-tests.sh --full`
Expected: 44 tests (43 mirrored cases + the harness smoke test), 0 failures. Without `--full`, 2 are skipped.

- [ ] **Step 5: Commit**

```bash
git add run-claude.sh test/run-claude.bats
git commit -s -m "feat: wait for the -t target start time"
```

---

## Task 9: Documentation and repository housekeeping

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `.gitignore`
- Create: `.gitattributes`

- [ ] **Step 1: Add .gitattributes**

The repository now holds both CRLF and LF files. A `.sh` checked out with CRLF fails with `bad interpreter`, so pin both:

```
*.bat text eol=crlf
*.cmd text eol=crlf
*.sh  text eol=lf
```

> Not in the spec. It is included because mixing line endings in one repository is exactly how the `.sh` breaks on a Windows checkout. Flag it when reporting.

- [ ] **Step 2: Add the lock directory to .gitignore**

Append `run-claude.lock.d/`.

- [ ] **Step 3: Update README.md**

- In **Requirements**, note bash 4+ for the `.sh` and that macOS needs no extra packages.
- Add a short **Linux and macOS** section: `chmod 755 run-claude.sh`, the same option table applies, `./run-claude.sh "prompt" -i 30 -c 5`.
- In **Project layout**, add `run-claude.sh`, `test/run-claude.bats`, `test/bin/claude`, `test/run-tests.sh`, `test/bats/`, `.gitattributes`.
- In **Testing**, add `git submodule update --init --recursive` then `./test/run-tests.sh [--full]`.
- State plainly that macOS is untested so far.

- [ ] **Step 4: Update CLAUDE.md**

- A **Keeping the two runners in sync** section: classify every change as platform-specific or shared; shared changes go into both scripts and both suites.
- The **43-case list** as a table, so a new case can be added to both suites.
- The **stub contract** table from the spec.
- A **bash notes** section: landmines 2, 3, 4, 5, 9, 10 and 11 have no counterpart; landmine 7 is explicitly reversed and why; landmines 13, 14 and 15 still apply.
- Correct the two stale figures while in the file: the script is 866 lines, not 797, and the batch suite has 43 cases, not 40.

- [ ] **Step 5: Verify the whole suite once more**

```bash
./test/run-tests.sh --full
```
Expected: 44 tests, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add README.md CLAUDE.md .gitignore .gitattributes
git commit -s -m "docs: document the bash runner and the sync rule"
```

---

## After the plan

Two things remain that no automated test can settle, and both must be reported as outstanding rather than assumed:

1. **A real end-to-end run on Linux** against the actual `claude` CLI — one single iteration, then a multi-iteration loop against `runner-test-task.md`. `.bat` landmines 13 and 14 were both found this way and neither would have been caught by a stub.
2. **macOS.** The BSD `date` branch is written from documentation and never executed during implementation. The user will run the suite on a Mac separately.
