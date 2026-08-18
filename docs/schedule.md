# `lmi schedule`

Runs the Claude Code CLI **unattended**: start now or at a set time, repeat on an
interval, carry progress between iterations through a state file, and keep going
when a single `claude` call fails.

[← README](../README.md) · [`lmi install claude`](install-claude.md) ·
[`lmi config`](config.md) · [`lmi upgrade`](upgrade.md) · [Status](status.md)

---

## Before the first run

- The **Claude Code CLI on `PATH`**, resolvable as `claude`. If the machine does
  not have it yet, [`lmi install claude`](install-claude.md) installs it from an
  internal npm registry and configures it.
- **Authentication already done**, interactively, once: `claude auth login`. An
  unattended run has nobody to complete a sign-in prompt. Credentials live in
  `~/.claude/.credentials.json` (`%USERPROFILE%\.claude\` on Windows) and are
  per-user — WSL credentials do not carry over to a Windows install, and a
  scheduled task must run as the user who signed in.

`lmi schedule` validates its arguments and prerequisites up front and exits with
a clear message rather than failing halfway through a scheduled overnight run.

## Usage

```
lmi schedule "<prompt or prompt-file>" [-t "YYYY-MM-DD HH:MM"] [-i minutes]
             [-c count] [-d workdir] [-f "flags"] [-l logfolder]
             [-s statefile] [-r] [-v]
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
| `-f "<flags>"` | Extra claude flags, in **both** backends. `cli` appends them to the argv; `sdk` forwards them to the `claude` it spawns. Long options only. |
| `-l <folder or file>` | Log destination. A folder receives `run-claude-<timestamp>.log`; a path with an extension is used as the log file itself. Omitted = `<workdir>/run-claude-<timestamp>.log`. |
| `-s <file>` | State file. Omitted = `<workdir>/run-claude-state.md`. |
| `-r` | Resume: keep the existing state file instead of backing it up and starting clean. |
| `-v`, `--verbose` | Watch the run while it runs: log the prompt lmi sends, and render claude's activity live instead of after the iteration ends. See [Verbose mode](#verbose-mode). |

`-i` and `-c` are **mutually required** — either both or neither. Each alone exits
2, with a message explaining why. On its own, `-i` says how long to wait but never
when to stop; `-c` says how many iterations but never how long to wait between
them. There is deliberately no unlimited-loop mode: an unattended runner with no
stop condition is a liability.

Every invocation always grants exactly `Edit,Write` and the state file's
directory, in both backends. Under the `cli` backend that is
`--allowed-tools=Edit,Write` and `--add-dir <state file directory>` on the
command line, and anything you give with `-f` is appended after those.

So a flag lmi does not already pass **composes** — `-f "--model opus"` adds to
what is there. A flag lmi *does* already pass **replaces** it, because claude
takes the last occurrence of a repeated option and `-f` is last. That matters
for exactly one flag in practice, `--allowed-tools`: see [granting more
tools](#granting-more-tools-bash-and-python) below.

**`-f` works in both backends**, and means the same thing in both: your flags end
up on a `claude` command line. Under `cli` lmi appends them to the argv it builds.
Under `sdk` they are handed to the SDK as `extra_args`, which the SDK renders onto
the argv of the `claude` it spawns — so `-f "--model claude-haiku-4-5"` changes the
model in either mode, and the log header records what was forwarded:

```
Flags     : --model claude-haiku-4-5 --max-turns 2
```

lmi does not interpret your flags in either mode. Under `sdk` it converts token
shape into the name/value mapping the SDK wants — `--flag value`, `--flag=value`
and a bare `--flag` all work — and knows only two things beyond that:

- **Long options only.** The SDK forwards flags as a mapping, which cannot spell
  a single-dash option, so `-f "-p"` is exit 2 rather than a mangled `---p`.
  Write `--flag=-value` when a *value* begins with a dash.
- **Four flags are refused**, with exit 2 naming the reason:
  `--output-format` and `--input-format` (the SDK and the CLI speak stream-json
  to each other, and `extra_args` is appended *after* the SDK's own flags, so a
  duplicate overrides rather than adds), `--print` (the SDK owns the
  non-interactive mode), and `--permission-mode` (lmi sets a non-interactive one
  — see [Guarantees](#guarantees)). Refused, never dropped: `-f` is where a site
  puts what it cannot say any other way, so silently ignoring one would be the
  worst outcome available.

### Backends

`lmi schedule` can reach Claude two ways, and the choice is configuration
rather than a flag:

| Mode | What it does | Needs |
|---|---|---|
| `sdk` | **The default.** Calls the Claude Agent SDK as a Python library and consumes typed messages. | `claude-agent-sdk`, Python 3.10+ |
| `cli` | Runs `claude -p`, feeds the prompt on stdin and parses stdout. | nothing beyond the `claude` command |

**SDK mode still runs a Claude Code binary.** The SDK is Claude Code as a
library, not a replacement for it — the wheels bundle a binary and spawn it,
and where pip installs the source distribution instead, the SDK looks for
`claude` on `PATH`. So `lmi install claude`'s npm half is necessary either way.

`cli` mode needs no pip install at all and keeps lmi on its Python 3.9 floor,
standard library only. The SDK is an optional extra (`pip install "lmi[sdk]"`),
which is what lets every bootstrap script install lmi with `--no-index`.

Read or change the mode with:

```bash
lmi config schedule                    # show it, and say which file chose it
lmi config schedule --mode cli         # set it
```

and see it in every run's log header:

```
Backend   : sdk (from /home/you/.lmi/config.json)
```

That line matters more than it looks. **Both backends exit 0 on success**, so
nothing in the result of a run tells you which one produced it — the header is
the only record.

There is deliberately **no fallback between them at run time**. If the mode
says `sdk` and the SDK cannot be imported, the run stops with exit 2 naming
every way to fix it, rather than quietly running the other backend. Choosing a
backend is the installer's job, done once and written into a file you can read.

#### Smoke-testing SDK mode without any credential

You do not need an API key, a token or a login to check that SDK mode is wired
up. Point it at a throwaway home and working directory, with every
`ANTHROPIC_*` variable unset:

```bash
mkdir -p /tmp/nokey/home /tmp/nokey/work
printf '{ "schedule": { "mode": "sdk" } }\n' > /tmp/nokey/lmi.json

env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u ANTHROPIC_BASE_URL \
    HOME=/tmp/nokey/home \
    lmi schedule 'say hello and stop' -d /tmp/nokey/work \
        -i 0 -c 2 -v --config /tmp/nokey/lmi.json
```

Every call fails, which is the point: what you are checking is everything
*around* the call. Expect exit 1, and in the log

```
Backend   : sdk (from /tmp/nokey/lmi.json)
SDK       : claude_agent_sdk 0.2.136
Tools     : Edit,Write
Permission: acceptEdits
Settings  : user,project,local
[claude] text    Not logged in · Please run /login
[claude] done    error - 1 turns - 0.1s - Not logged in · Please run /login
[ERROR] the SDK reported the call failed - Exception: ...
[ERROR] === Iteration 1 of 2 FAILED at ... - claude exit code 91 - 0s ===
2 run/s, 0 succeeded, 2 failed.
```

That confirms the mode resolved and was logged, the options carry the tools,
permission mode and settings sources, the prompt was composed, the state file
was created, the renderer works, a failed call is recorded as **exit code 91 —
a failed call, not a skipped iteration** — and the loop survives to iteration 2
rather than the run ending. `-c 2` is not incidental: one iteration cannot show
that the loop survives.

Costs nothing and spends no quota, because there is no credential to spend it
with. `CLAUDE.md` item 45 is three separate silent bugs this run found and a
green test suite did not — run it before trusting any change to this backend.

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
lmi schedule task.md -t "2026-09-01 22:00" -i 60 -c 12 -f "--model opus"

# continue yesterday's task instead of starting clean
lmi schedule task.md -i 20 -c 5 -r

# start on 15 September at 21:30, then every 45 minutes, six times, watching it
# live - on opus, and allowed to run bash and python in the working directory
lmi schedule task.md \
    -t "2026-09-15 21:30" -i 45 -c 6 -v \
    -d ~/work/myrepo \
    -f "--model opus --allowed-tools=Edit,Write,Bash"
```

#### Granting more tools: bash and python

That last example is worth taking apart, because one detail in it is the
difference between a working loop and a run that reports success having done
nothing.

`-t` is a future start — a time already past starts immediately instead. `-i`
and `-c` are [mutually required](#options). `-v` logs the composed prompt and
renders claude's activity as it arrives. `-f` carries **both** claude flags in
one quoted string, and reaches the same `claude` command line under either
backend.

**`Edit,Write` has to be re-listed.** lmi passes `--allowed-tools=Edit,Write`
itself and appends `-f` after it, so the two occurrences are resolved by claude
taking the last one. Writing `-f "--allowed-tools=Bash"` therefore does not add
Bash to the grant — it *replaces* the grant, and the iteration can no longer
write the state file. That failure is silent in the expensive way: every
iteration exits 0, the state file stays the untouched template, so the loop
repeats iteration 1 for as many iterations as you asked for and the run reports
success. Name all three and it composes correctly.

There is **no separate tool for Python.** `python3 build.py` is a `Bash` tool
call, so `Bash` is the whole of what "run bash and python" needs. The commands
run in claude's working directory, which is `-d` — `~/work/myrepo` here — and
the state file's directory is granted alongside it with `--add-dir`.

The exact command line that example produces, in `cli` mode:

```
claude -p --allowed-tools=Edit,Write --output-format stream-json --verbose \
       --add-dir /home/you/work/myrepo \
       --model opus --allowed-tools=Edit,Write,Bash
```

Under `sdk` mode the same two flags arrive as `extra_args` —
`{'model': 'opus', 'allowed-tools': 'Edit,Write,Bash'}` — which the SDK renders
onto the argv of the `claude` it spawns, after the flags it builds for itself.
Same last-occurrence rule, same result.

One thing to weigh before granting it: a tool named in `--allowed-tools` is
**pre-approved**, and nobody is watching an unattended run. Whatever the task
talks claude into running, it runs. Point `-d` at a checkout you would not mind
losing, rather than at a machine you care about.

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

**Nothing in `lmi schedule` ever waits for a keypress.** The prompt arrives on
stdin and every wait is a `time.sleep`. This is a property of the unattended
runner rather than of `lmi` as a whole:
[`lmi install claude`](install-claude.md) is interactive by design, and guards
only against *hanging*.

### Logging

Everything claude prints, plus every runner action, goes to both the console and
the log file: the resolved configuration, each iteration's start, end, exit code
and duration, state file handling, and a final summary of how many iterations ran,
succeeded and failed. A crash inside the runner itself is logged with its full
traceback, not merely printed to a terminal nobody may be watching.

A log file that cannot be written **degrades to console output** with one `[WARN]`
— it never decides the exit code.

### Verbose mode

Without `-v`, a run is opaque while it works. `claude -p` prints nothing until it
finishes, so the log stays silent for the whole of a twenty-minute iteration and
then receives the final text in one block — and the prompt `lmi` composed is
never recorded at all.

`-v` fixes both halves:

```
lmi schedule task.md -i 30 -c 10 -v -l ~/lmi-logs
```

**It logs the prompt.** The first iteration writes the complete composed
document — the header, the state protocol, the inlined state file and your task.
Every iteration after it writes only the state file portion, because the other
three parts are byte-identical every time: the task is read once before the loop
and the protocol is a constant.

**It renders claude's activity live.** `-v` passes
`--output-format stream-json --verbose` to claude and turns each event into a
line as it arrives:

```
--- claude activity ---
[claude] init    model=claude-opus-5 session=a3f2b1c8 cwd=/home/you/repo
[claude] text    I'll start by reading the runner, then annotate it.
[claude] tool    Read   lmi/commands/schedule/runner.py
[claude] result  292 lines
[claude] tool    Bash   python3 -m pytest tests/ -q
[claude] result  453 passed, 1 skipped in 2.39s
[claude] tool    Write  run-claude-state.md
[claude] done    success - 6 turns - 31.2s
--- end of claude activity ---
```

Four things worth knowing:

- **`-v` is one switch.** It passes `--verbose` to claude for you; you never
  additionally need `-f "--verbose"`.
- **It costs no tokens.** The log is written by `lmi` and read back by nothing.
  It is not in the prompt, not referenced by the prompt, and no iteration is
  told it exists. What claude receives under `-v` is byte-identical to what it
  receives without it.
- **Pair it with `-l`.** By default the log lands in the working directory,
  where claude operates. It is never *fed* to claude, but a verbose log
  contains claude's own earlier output, which is confusing material to stumble
  across. `-l ~/lmi-logs` puts it out of reach.
- **`-v` sets the output format**, so it cannot be combined with an
  `--output-format` of your own in `-f` — that combination exits 2 rather than
  silently blanking the activity block. Everything else in `-f` composes as
  usual; `-f "--include-partial-messages"` streams claude's text token by
  token if you want maximum liveness at the cost of readability afterwards.

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
- **No log rotation.** Each run writes a new timestamped log file. `-v` makes
  each one considerably larger.
- **Two things about `-v` no test can settle**, both needing a real claude:
  whether `--verbose` adds anything on top of `--output-format stream-json`
  (it is passed because stream-json in `-p` mode has historically required it,
  and a duplicate boolean costs nothing if it turns out not to); and whether
  claude block-buffers its stdout when it is a pipe, which would make the
  rendered lines arrive in bursts rather than smoothly. Neither changes what
  `lmi` does — the non-verbose path writes to a file, equally not a terminal,
  so streaming is never *worse* than before.
- **`-v` couples `lmi` to claude's event schema.** A future version could
  change it. That failure is visible rather than silent: an unrecognised event
  renders as one dull line, and output that is not stream-json at all warns
  once and is then passed through verbatim.
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
- **Do not upgrade while `lmi schedule` is looping.** The upgrade replaces
  files underneath that process. Modules it has already imported stay in
  memory, but one it has not yet imported would come from the new version. The
  locks are per state file in arbitrary directories, so there is nothing for
  `lmi upgrade` to enumerate and no honest way for it to detect this. Upgrade
  between runs.

None of these are scheduled work. If you want one, say so before building it.

---
