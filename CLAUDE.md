# lmi — project context and handoff

`lmi` is a Python CLI that runs the Claude Code CLI unattended. `lmi schedule`
loops `claude -p` in the foreground, carrying progress between iterations through
a state file; `lmi install claude` installs and configures that CLI in the first
place, from an internal npm registry on an air-gapped machine; `lmi config
switch` applies a `settings.json` fragment over that configuration afterwards,
and can put the machine's original settings back. `README.md` is the user-facing
documentation and is accurate; this file is what you need before *editing* the
code.

Read section 3 before changing any behaviour. Every item there is a bug that was
already paid for once, and most of them fail **silently** — a run that reports
exit 0 while doing nothing useful.

---

## 1. Requirements that are not negotiable

These come from the user and are invariants, not preferences:

1. **Iterations never overlap.** Guaranteed structurally: the loop is sequential
   and the interval wait starts only after `claude` exits. A second *instance* is
   blocked by the lock in `core/lock.py`.
2. **A failing claude call must never fail the runner.** A non-zero exit is
   logged with `[ERROR]`, the iteration is counted as failed, and the loop
   continues. Quota and rate-limit wording is additionally flagged `[QUOTA]`.
   The same holds for exceptions on the way to claude: they are logged and the
   iteration is recorded as skipped (`ITERATION_ERROR_RC`).
3. **`lmi schedule` may never wait for a keypress.**
   Nothing may ever wait for a keypress in the unattended runner: the prompt is
   fed on stdin, and every wait is a `time.sleep`. This is a property of that
   runner, not of `lmi` as a whole — `lmi install` is interactive by design and
   asks before it changes anything. It has no `--yes`, and guards only against
   *hanging*: with no terminal it exits 2 rather than waiting forever.
4. **Python 3.9 floor, standard library only at runtime.** No `match`, no
   `X | Y` runtime unions, no builtin generics in evaluated annotations. `pytest`
   is a dev extra and must never be imported by `lmi/`.
5. **`-i` and `-c` are mutually required.** Either both or neither; each alone
   exits 2. There is deliberately no unlimited-loop mode — an unattended runner
   with no stop condition was judged not worth having.

Do not add features that were not asked for.

---

## 2. Architecture

```
lmi/cli.py                  parse and dispatch, nothing else
lmi/commands/__init__.py    the command registry: one import, one list entry
lmi/commands/schedule/      the command, as a self-contained package
  config.py                 arguments, validation, the frozen Config
  paths.py                  where the log, state file and lock go
  prompt.py                 composing one iteration's prompt
  state.py                  template, backup-or-resume, completion check
  runner.py                 the loop and the claude invocation
  exit_codes.py             this command's own codes (1, 3, 4)
lmi/commands/install/       `lmi install claude`, as a self-contained package
  config.py                 arguments, config-file discovery, the frozen Config
  prompts.py                every question, and the no-terminal guard
  npm.py                    locating npm, one npm command, the --global fallback
  settings.py               what goes into ~/.claude/settings.json
  claude_json.py            what goes into ~/.claude.json
  gitbash.py                Windows Git Bash discovery and the env var
  runner.py                 the flow
  exit_codes.py             this command's codes (1, 3, 4)
lmi/commands/config/        `lmi config switch`, as a self-contained package
  args.py                   the nested subparser
  fragment.py               finding, reading and validating the switch file
  merge.py                  the recursive merge
  origin.py                 the write-once snapshot
  runner.py                 the flow
  exit_codes.py             this command's codes (3, 4)
lmi/core/                   only genuinely command-agnostic code
  errors.py                 LmiError and the global codes (0, 2)
  fs.py                     path classification that never raises
  text.py                   BOM-aware decoding
  lock.py                   single-instance lock (fcntl / msvcrt)
  log.py                    one line to console and log file
  jsonfile.py               read / back up / atomically write a JSON document
  claude.py                 where Claude Code keeps its files
```

Three rules hold this shape together:

- **`cli.py` never learns about a command.** A command is a module exposing four
  names — `NAME`, `HELP`, `add_arguments`, `run` — and is registered by one line
  in `commands/__init__.py`. Adding a command must not require editing `cli.py`.
  Registration is explicit rather than `pkgutil` discovery on purpose: discovery
  makes `--help` ordering non-deterministic, imports every command on every
  startup, and turns a typo into a silently missing command.
- **Exit codes have owners.** `0` (success) and `2` (usage) are global and live in
  `core/errors.py`; no command may redefine them. Everything else belongs to the
  command that defines it, which is why `exit_codes.py` exists as its own module
  despite holding three constants.
- **`core/` is for code with no command flavour.** `paths.py` stays inside
  `commands/schedule/` because its rules are that command's. If a second command
  ever needs the path helpers in it, promote them then, not in advance.
  `jsonfile.py` is that rule having fired rather than an exception to it: it
  lived in `commands/install/` until `lmi config switch` became its second
  caller, and moved to `core/` at that moment — with `settings_path()` lifted
  out beside it as `core/claude.py`, because two commands disagreeing about
  where `settings.json` lives would leave one of them silently configuring a
  file nothing reads. What made the move honest is that neither module knows
  what Claude Code is; the exit code to raise with is a parameter, since `core/`
  cannot know a command's codes.

The claude invocation, in `runner.py`, is the delicate part:

```python
subprocess.run(argv, stdin=prompt_fh, stdout=out_fh,
               stderr=subprocess.STDOUT, cwd=str(cfg.work_dir))
```

A list argv, never `shell=True`, and `check=False` (the default) so a non-zero
exit returns instead of raising. `argv` is built once per run, not per iteration.

**State protocol.** Each iteration's prompt carries a header forbidding
questions, the iteration number, the state file path, a numbered protocol, the
**current contents of the state file** inline under `## CURRENT STATE`, then the
user's task under `## TASK`. Claude is told to keep this layout in the state file:

```
TASK_STATUS: IN_PROGRESS
## Goal
## Completed
## In progress
## Next steps
## Notes and blockers
```

After each iteration `state.check_complete` tests **the first line only** for
`TASK_STATUS: COMPLETE` and stops the loop early if it matches.

---

## 3. Behaviours that must not regress

Each of these was a real bug. The symptom is given so you can recognise a
regression, and the ones marked **silent** are the expensive ones: the run
reports success.

1. **The state file must not live under `.claude/`.** The CLI treats everything
   there as sensitive and refuses to Write or Edit it, and a `-p` run has nobody
   to approve. **Silent:** the runner exits 0 with the iteration counted as a
   success, but the state file is still the untouched template, so a loop repeats
   iteration 1 forever and can never see `TASK_STATUS: COMPLETE`. Hence the
   default `<workdir>/run-claude-state.md`. `state.write_template` now raises when
   the write fails, rather than logging success. A `-s` path inside a `.claude`
   folder still hits the underlying refusal — do not do it.
2. **The completion check reads line 1 only.** Claude reliably restates the
   protocol sentence *"write TASK_STATUS: COMPLETE on the first line only when
   ..."* inside the state file, so a whole-file search matches that prose.
   **Silent:** a `-c 5` run does iteration 1, stops, and reports `1 run, 1
   succeeded, 0 failed` with exit 0 while line 1 still says `IN_PROGRESS` and
   four fifths of the task is abandoned. `COMPLETE_RE` is `^`-anchored without
   `re.MULTILINE`, and the read is a fixed 4096-byte head decoded through the BOM
   logic, then `splitlines()[0]`. Do not widen it. It is case-insensitive
   deliberately, which cannot reopen this: the read is still line-1-only.
3. **A prompt file must be UTF-8, or carry a BOM.** UTF-16 is detected from its
   BOM and decoded; anything else is refused with exit 2. **ANSI is undetectable
   by construction** — it carries no mark and cannot be told apart from UTF-8. Do
   not try to guess it. The state file goes through the same decoder, so what
   `check_complete` reads and what gets inlined into the next prompt always
   agree.
4. **`Path.write_text(..., newline=...)` needs Python 3.10.** Use
   `open(..., "w", encoding="utf-8", newline="\n")`. On the 3.9.6 that macOS
   ships, the `write_text` form killed every run at iteration 1 with a
   `TypeError`. A syntax check cannot catch a parameter added in a later version.
5. **`pathlib`'s `is_dir()`/`is_file()` only look like predicates.** They swallow
   ENOENT, ENOTDIR, EBADF and ELOOP and let everything else through —
   **ENAMETOOLONG** in particular, which an inline prompt of 256 bytes without a
   slash reaches (a 143-character Hebrew sentence does it). That surfaced as a
   bare traceback and exit 1, the code that means a claude call failed. Use
   `core.fs.classify`/`kind`, which return a verdict instead of raising, and turn
   `UNKNOWN` into exit 2 where a path was given by the user.
6. **`Path.expanduser()` raises `RuntimeError`** for a `~someuser` whose home it
   cannot resolve — a typo in `-s "~claude/state.md"` is enough. Wrapped in
   `paths._expand`. The tilde expansion itself must stay: it is what makes a
   quoted `-s "~/x"` work, since the shell never sees the tilde.
7. **The logger must never raise.** An unwritable log file made `Logger.line`
   raise, which reached the runner's error handler, which called `log.error`,
   which raised the same error again — a two-level traceback and exit 1,
   indistinguishable from a failed claude call, with exit 4 unreachable exactly
   when logging is what broke. It now warns once and degrades to console output.
   The console print is itself guarded, for a codepage that cannot represent the
   text.
8. **`msvcrt.locking` locks one byte at the current position**, and `"a+"`
   positions at end of file, so two runs whose lock files differ in size would
   lock different offsets and both proceed. `seek(0)` first. Windows also cannot
   byte-range-lock a file on a share: on a WSL 9p mount the call fails with
   `EINVAL`, which `core/lock.py` cannot tell apart from contention, so the
   symptom was exit 3 — "another run is working on this state file" — with
   nothing running. `paths._reject_unc` refuses a UNC state file up front and
   offers the escape hatch (`-s` on a local drive; the working directory may stay
   on the share).
9. **An unwritable state directory is the user's error, not a bug.** The lock
   lives beside the state file, so it fails there first. That reported exit 4, "a
   bug in lmi". It is exit 2, and `paths._ensure_writable` now says so once,
   naming `-d`, instead of failing three times in a row for the lock, the log and
   the state file.
10. **`-l` rule order is load-bearing.** An extension-less path that does not
    exist yet is a **folder**, not a log file. Getting it wrong makes
    `-l some/new/logdir` create a *file* called `logdir`. `has_extension` is
    hand-rolled rather than `Path.suffix` on purpose: pathlib reports no suffix
    for a trailing dot, so `logs.` would flip from folder to file.
11. **The CURRENT STATE fence length is computed, not fixed at three backticks.**
    The state file is written by claude and may contain its own fenced block,
    which would close a fixed fence early and leak the rest of the document —
    including a second literal `## TASK` — out of the block. `prompt._fence_for`
    uses one more backtick than the longest run in the body.
12. **An exception mid-iteration must not abort the loop.** Invariant 2's
    exception half, in `runner._iteration_rc`. Before the guard, a vanished temp
    workspace ended the run at iteration 2 with exit 4 and iterations 3 and 4
    never happened. The `except LmiError: raise` clause must stay *first*: a
    deterministic usage error (a prompt file that is not UTF-8) would fail
    identically on every remaining iteration, so it ends the run instead of
    burning the loop.

Items 13 to 21 belong to `lmi install`, and every one of them is silent — the
run reports success. Two of them now reach further than that command: 19 and 20
are about `jsonfile.py`, which moved to `core/`, and `lmi config switch` reads
and writes `settings.json` through the same two functions.

13. **The onboarding key is `hasCompletedOnboarding`, lowercase `b`.**
    Verified in the 2.1.222 binary. **Silent:** the natural spelling
    `hasCompletedOnBoarding` writes cleanly, parses cleanly and does nothing —
    the user meets the onboarding flow the command promised to skip, and the
    run reports success.
14. **`npm install -g` is never retried without `-g`.** `npm config set`
    retrying without `--global` is a correct fallback to `~/.npmrc`. The same
    move on the install is not. **Silent:** it installs into `./node_modules`
    of the current directory, creates no `claude`, and exits 0. Hence the
    comment in `npm.install` telling you not to give it `config_set`'s shape.
15. **A failing npm step must touch no Claude config file.** The order in
    `install/runner._run` is load-bearing: npm first, config documents after.
    **Silent:** the machine ends up with the 256K profile, the marketplaces and
    onboarding skipped, but no binary — it looks provisioned and is not.
16. **Declining the repair question changes nothing at all.** No npm command,
    no backup, no write. Exit 0, because the user answered rather than erred.
17. **Git Bash work is Windows-only.** `CLAUDE_CODE_GIT_BASH_PATH` is resolved
    through `path/win32` and is never read elsewhere, so off Windows nothing is
    probed, `setx` never runs and the key never reaches `settings.json`.
    Candidates are validated the way Claude Code validates — basename in
    `bash.exe`/`sh.exe`/`bash`/`sh`, and the file exists — because a path it
    rejects looks configured and is not.
18. **`settings.json` `env` values are strings.** A JSON number is silently the
    wrong type, so the 256K profile does not apply. `config._env` refuses one
    with exit 2 rather than passing it through.
19. **An unparseable `settings.json` or `.claude.json` is refused, not
    overwritten.** Treating it as `{}` would discard everything the user had.
    `jsonfile.read` raises exit 3 and names the file; nothing is written.
20. **`core/jsonfile.write`'s temp file is born 0600, not chmod-ed to it later.**
    `os.open(..., 0o600)` plus `os.fdopen`, never plain `open()`. `~/.claude/`
    is 0755, so writing the auth token first and fixing the mode afterwards
    leaves it in a world-readable file for the length of the write.
    **Silent:** the finished `settings.json` is 0600 either way, so the end
    state is identical and nothing afterwards shows the window existed. The
    `os.chmod` before `os.replace` is still needed and is not the same guard —
    it exists to *widen* to a preserved 0644, and widening after the content is
    written is safe where narrowing after is not. Which is why
    `test_the_mode_is_set_before_the_file_becomes_visible` forces **0644**: at
    0600 it asserts the birth mode and passes with the chmod deleted entirely.
    The `O_BINARY` in the same `os.open` is a separate guard again — section 4,
    rule 4.
21. **A config file at the pre-move `./lmi.json` is refused, not skipped.** The
    working-directory default is `./config/lmi.json`; `config._refuse_legacy`
    turns a file left at the old path into exit 2 naming both paths. **Silent:**
    skipping it lets the next candidate win — `~/.lmi/config.json`, a different
    registry, quite possibly a different site — so npm succeeds, the run reports
    success, and the machine is provisioned from the wrong source while an
    `lmi.json` sits in plain view in the working directory. It is the mirror of
    the `--config`-does-not-fall-through rule, and is checked at the point in
    the search order the old path used to occupy, so `--config` and
    `$LMI_CONFIG` still win and never trip over it — including `--config
    ./lmi.json`, the escape hatch the message offers.

And one for `lmi config switch`, which is the whole of what `origin` means:

22. **The origin snapshot is written only if it does not already exist.**
    `config/origin.capture` takes `~/.claude/settings.json.lmi-origin` on the
    first switch and never again, which is what makes `switch origin` mean the
    settings the machine had before *any* switch rather than before the last
    one. **Silent:** written unconditionally it becomes undo-one-step while
    still being spelled `origin` — every single switch behaves identically, the
    snapshot file is there either way, and nothing at all afterwards
    distinguishes the two, except that the user's real settings stopped being
    recoverable at the second switch. The `if not exists()` is the entire
    mechanism; do not simplify it into an unconditional write.

---

## 4. Rules for editing

1. **Run the suite after every change** and say in your report that you did:
   `python3 -m pytest tests/ -q`. It is 336 tests in under two seconds and it
   costs nothing — several bugs above only appear with awkward paths, or only
   when a claude call fails.
2. **Preserve the five invariants in section 1** and everything in section 3.
   Where a comment in the code says "do not simplify this back to X", X is the
   bug.
3. **Do not let a test reach a real `claude`.** The `fake_claude` fixture
   replaces `PATH` entirely rather than prepending, precisely so that a real
   `claude` on this machine cannot win and quietly spend quota.
4. **Do not change line endings as a side effect.** `runner-test-task.md` is
   CRLF; `scripts/install-windows.cmd` and `install-windows.ps1` are LF, and the
   verified Windows install ran that way. Leave both as they are unless changing
   them is the point — cmd.exe can misparse an LF batch file, so this is worth a
   deliberate decision rather than an accident.

   The same rule reaches into the code, in one place this suite **cannot see**:
   `jsonfile.write` opens its temp file with
   `os.O_BINARY` (via `getattr(os, "O_BINARY", 0)`, absent and therefore 0 on
   POSIX). Without it `os.open` on Windows hands back a descriptor in the CRT's
   *text* mode, which rewrites `\n` to `\r\n` underneath the io layer and
   defeats the `newline="\n"` passed to `os.fdopen`. Dropping the flag stays
   green on Linux — `test_write_uses_lf_even_on_windows` can only ever assert
   the POSIX case from here — while writing CRLF `settings.json` on the site's
   Windows machines. The flag is load-bearing; only a real Windows run can catch
   its absence.
5. Tests that mark themselves `MANDATORY` in their docstring pin one of the
   silent failures above. If one goes red, that failure is back — do not adjust
   the test to match new behaviour.
6. `os.geteuid` is Unix-only and a `skipif` argument is evaluated at import time,
   so permission tests use the shared `skip_as_root` marker in `tests/conftest.py`
   rather than a bare call, which would lose a whole module to an
   `AttributeError` during collection on Windows.

---

## 5. Testing

```bash
python3 -m pytest tests/ -q          # 336 tests, <2s, no install needed
```

Fixtures worth knowing, in `tests/conftest.py` and the three per-command
`conftest.py` files under `tests/commands/`:

| Fixture | What it gives you |
|---|---|
| `fake_claude` | A fake CLI on an exclusive PATH; records argv and the composed prompt per call, and can be told to misbehave through `FAKE_RC`, `FAKE_OUT`, `FAKE_STATE_FILE`, `FAKE_COMPLETE_AT`, `FAKE_PROSE`, `FAKE_BLANK_FIRST_LINE`, `FAKE_WRECK_TMP` |
| `fake_npm` | The same trick for npm — an exclusive PATH, argv recorded per call, `FAKE_NPM_RC` and `FAKE_NPM_FAIL_GLOBAL` (fail only when a global flag is present, which is how the `--global` fallback is exercised without root) |
| `home` | A throwaway `HOME`/`USERPROFILE`, so no test can touch the developer's real `~/.claude`. Defined separately in the `install` and `config` conftests rather than shared. Every `config` test reaching `settings_path()` or the snapshot must take it, or it writes to the real home |
| `answers` | In `tests/commands/install/test_runner.py`: a scripted queue behind `prompts.confirm/secret/text`, so no test reaches a real stdin |
| `make_cfg` | A `Config` factory, so its ten fields are built in one place |
| `readonly_dir` | A 0o500 directory, restored on teardown |
| `on_windows` | Takes the Windows branch of `paths.py` (patches `_on_windows`, never `os.name`, which pathlib reads at instantiation). The install suite patches `gitbash.on_windows` for the same reason |
| `deny_touch` | Makes the writability probe fail the way `C:\Windows` does |
| `skip_as_root` | The root-skip marker described in section 4 |

`FAKE_PROSE` and `FAKE_BLANK_FIRST_LINE` are the fixtures for regression 2 — they
write a state file that says `IN_PROGRESS` on line 1 while mentioning
`TASK_STATUS: COMPLETE` elsewhere, which is what real claude does. Widening the
completion check must turn those tests red.

What a fake CLI can **never** cover is how the real one behaves: regressions 1 and
2 were both found by real runs, not by tests. `README.md` has the two real-run
checks worth doing, names the two measurements still outstanding, and carries the
four `lmi install claude` checks that only a real Artifactory and a real Windows
box can settle.

`tests/test_docs.py` is the one module that tests documentation rather than code:
that `examples/lmi.json` still passes `config.build_config` and
`examples/settings_switch.json` still passes `fragment.load`, that the README
still spells the three silent keys and still documents `lmi config switch`, that
invariant 3 above stays scoped to `schedule`, and that item 22 above is still in
this file. Both examples are what a new site copies, so one going stale is a
usage error on somebody's first day. The item-22 check is the odd one: it guards
a paragraph rather than a file a user touches, because that rule exists nowhere
else — one line of code, no symptom when inverted, and this file the only place
that says why.
