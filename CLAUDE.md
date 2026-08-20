# lmi — project context and handoff

`lmi` is a Python CLI that runs the Claude Code CLI unattended. `lmi schedule`
loops `claude -p` in the foreground, carrying progress between iterations through
a state file; `lmi install claude` installs and configures that CLI in the first
place, from an internal npm registry on an air-gapped machine; `lmi config
switch` applies a `settings.json` fragment over that configuration afterwards,
and can put the machine's original settings back. The user-facing documentation
is `README.md` — a front page — plus one reference per command under `docs/`
(`schedule.md`, `install-claude.md`, `config.md`, `upgrade.md`) and `docs/status.md`
for what has actually been run on a real machine. It is accurate; this file is
what you need before *editing* the code.

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
   runner, not of `lmi` as a whole — `lmi install` and `lmi upgrade` are
   interactive by design and ask before they change anything. Neither has a
   `--yes`, and both guard only against *hanging*: with no terminal each exits
   2 rather than waiting forever. `lmi upgrade` is the more dangerous of the
   two, since it replaces the binary currently running it.
4. **Python 3.9 floor, standard library only at runtime — with one bounded
   exception.** No `match`, no `X | Y` runtime unions, no builtin generics in
   evaluated annotations. `pytest` is a dev extra and must never be imported by
   `lmi/`.

   The exception is the `lmi schedule` SDK backend. `lmi/core/`, `lmi/cli.py`,
   `lmi/commands/__init__.py` and the `install`, `config` and `upgrade`
   commands are standard-library only and must stay importable on 3.9 with no
   extra installed; **`lmi/commands/schedule/` may import `claude_agent_sdk`,
   lazily, in one module** (`schedule/sdk.py`), and nowhere else. The package
   is an optional extra, so `dependencies = []` stays true and every bootstrap
   script keeps its `--no-index`. `tests/test_packaging.py` enforces both
   halves — the extra exists, and no module outside `commands/schedule/`
   imports it. The import is lazy because `commands/__init__.py` imports every
   command at startup, and a missing or broken SDK must not break
   `lmi install claude` and `lmi upgrade`, the two commands whose job is fixing
   a machine in that state.
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
  backend.py                the mode vocabulary, and everything both backends
                            must agree on. Imported by `config` and `install`
  config.py                 arguments, validation, the frozen Config
  paths.py                  where the log, state file and lock go
  prompt.py                 composing one iteration's prompt
  state.py                  template, backup-or-resume, completion check
  session.py                the claude session carried across the intervals:
                            the handle, and the sidecar that remembers it
  stream.py                 `-v` only: two front ends onto one set of rows
  sdk.py                    the SDK backend; the ONLY importer of the SDK
  runner.py                 the loop, the seam, and the CLI backend
  exit_codes.py             this command's own codes (1, 3, 4)
lmi/commands/install/       `lmi install claude`, as a self-contained package
  config.py                 arguments, config-file discovery, the frozen Config
  defaults.py               the packaged config folder and every way it lands
                            in ~/.lmi: `adopt` (back up, then replace) for this
                            command, `fill` (keep what is there) for
                            `lmi config init`, and the one spelling of where
                            that folder is and what lmi.json is renamed to
  default-config/           that folder, and the ONLY one that ships: lmi.json,
                            settings.json, the statusline.js it declares and the
                            gateway/direct switch pair
  template.py               finding and validating the settings.json template
  statusline.py             finding and copying the statusline.js beside it
  prompts.py                every question, and the no-terminal guard
  npm.py                    locating npm, one npm command, the --global fallback
  sdk.py                    the SDK's pip install, and the import that decides
                            the mode. The only file naming the SDK package
  settings.py               what goes into ~/.claude/settings.json
  claude_json.py            what goes into ~/.claude.json
  gitbash.py                Windows Git Bash discovery and the env var
  runner.py                 the flow
  exit_codes.py             this command's codes (1, 3, 4)
lmi/commands/config/        `lmi config`, as a self-contained package
  subcommands.py            the nested registry: one import, one list entry
  args.py                   the nested subparser, built from that registry
  runner.py                 the dispatcher, and nothing else
  output.py                 `say`, so the dispatcher can import subcommands
  init.py                   `lmi config init`: fill ~/.lmi from the wheel
  switch.py                 `lmi config switch`: the flow
  catalog.py                where named switch files live, and their names
  fragment.py               finding, reading and validating one switch file
  merge.py                  the recursive merge
  origin.py                 the write-once snapshot
  schedule.py               `lmi config schedule`: show and set the backend
  exit_codes.py             this command's codes (3, 4), shared by all three
lmi/commands/upgrade/       `lmi upgrade`, as a self-contained package
  config.py                 arguments, the "lmi" config section, the frozen Config
  repo.py                   the repo as a source of versions: its newest tag,
                            and how two versions compare
  notice.py                 the once-a-day "a newer lmi exists" line. The one
                            thing cli.py imports from a command
  installation.py           detects the venv/--user install and refuses the rest
  pip.py                    the one pip command, and the version-probe read
  prompts.py                the one question, wrapping core/prompts.py
  verify.py                 confirms the upgrade by running the new script
  runner.py                 the flow
  exit_codes.py             this command's codes (1, 3, 4)
lmi/core/                   only genuinely command-agnostic code
  errors.py                 LmiError and the global codes (0, 2)
  fs.py                     path classification that never raises
  text.py                   BOM-aware decoding
  lock.py                   single-instance lock (fcntl / msvcrt)
  log.py                    one line to console and log file
  config.py                 config file discovery, decoding and parsing
  prompts.py                asking a question, and the no-terminal guard
  jsonfile.py               read / back up / atomically write a JSON document
  claude.py                 where Claude Code keeps its files
  pip.py                    `<interpreter> -m pip`: build an argv, run it
```

Three rules hold this shape together:

- **`cli.py` never learns about a command.** A command is a module exposing four
  names — `NAME`, `HELP`, `add_arguments`, `run` — and is registered by one line
  in `commands/__init__.py`. Adding a command must not require editing `cli.py`.
  It has exactly one import from a command package, and it is not a command:
  `upgrade/notice.py`, whose line belongs to no command at all. See item 62 for
  why that is the narrower of two evils; the registry half of this rule is
  untouched, and adding a command still requires no edit there.
  Registration is explicit rather than `pkgutil` discovery on purpose: discovery
  makes `--help` ordering non-deterministic, imports every command on every
  startup, and turns a typo into a silently missing command.
- **Exit codes have owners.** `0` (success) and `2` (usage) are global and live in
  `core/errors.py`; no command may redefine them. Everything else belongs to the
  command that defines it, which is why each command carries an `exit_codes.py`
  of its own for the two or three constants it defines.
- **`core/` is for code with no command flavour.** `paths.py` stays inside
  `commands/schedule/` because its rules are that command's. If a second command
  ever needs the path helpers in it, promote them then, not in advance.
  Everything now in `core/` beyond the original five is that rule having fired,
  not an exception to it. Each moved the moment a second caller appeared, and
  not before, on the guess that one might.

  `jsonfile.py` lived in `commands/install/` until `lmi config switch` became
  its second caller — with `settings_path()` lifted out beside it as
  `core/claude.py`, because two commands disagreeing about where
  `settings.json` lives would leave one of them silently configuring a file
  nothing reads. What made the move honest is that neither module knows what
  Claude Code is; the exit code to raise with is a parameter, since `core/`
  cannot know a command's codes.

  `config.py` and `prompts.py` went the same way, when `lmi upgrade` became the
  second command to need config-file discovery and a yes/no question. Same
  shape: what a section *means* stays with the command that owns it, and the
  no-terminal message is the caller's, so neither command's error text
  mentions the other.

Three commands now import `commands/schedule/backend.py`, which is the first of
two exceptions to "commands import only from `core/`". It is deliberate, and it is
the same reasoning that moved `settings_path()` into `core/claude.py`: three
copies of the valid-mode list is three chances for one command to write a value
another refuses. It stays in `schedule/` rather than moving to `core/` because
`schedule` owns what the value *means*, and `core/` has no opinion about
backends. It must never import the SDK — `lmi config` and `lmi install` both
import it, and both have to work on a machine whose SDK is missing.

The second exception is `commands/config/init.py` importing
`commands/install/defaults.py`, and it is the same reasoning again: `lmi config
init` and `lmi install claude` copy the same packaged folder to the same `~/.lmi`,
so where that folder is, which files in it are required, and the `lmi.json` →
`config.json` rename must have one spelling. Two would be one command creating a
folder the next search walks straight past — item 39 with no command to blame.
It stays in `install/` because that command owns what the folder is *for*; only
the copying is shared, and the exit code to raise with is a parameter, since
`defaults.py` cannot know `config`'s codes any more than `core/` can.

`lmi schedule` has two backends behind one seam, chosen by `schedule.mode` in
the resolved `lmi.json` and defaulting to `sdk`. `runner._select_backend` is
the only place the mode decides anything; `_CliBackend` and `_SdkBackend` each
expose `prepare` / `describe` / `call`, and `call` takes the session handle and
returns the same `backend.Outcome` - `(rc, quota, unresumable)` - whichever one
it is. That third field was a bare pair until sessions arrived; it exists
because only a backend can see claude saying the conversation it was asked to
resume does not exist, and the runner must not treat that like any other
failure (items 54 and 55). **There is deliberately no
fallback between them at run time** — see item 34.

The claude invocation, in `runner.py`, is the **CLI backend's** and is the
delicate part. It survives unchanged; it is now one of two paths rather than
the only one:

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
run reports success. Three of them now reach further than that command: 19 and
20 are about `jsonfile.py`, which moved to `core/`, and `lmi config switch`
reads and writes `settings.json` through the same two functions; and 18 is one
rule with three homes, because three different files are each a settings
document somebody hands to lmi. It is `template._validate` for the install
template, `fragment._validate` for a switch fragment, and it was
`config._env` for the `claude.env` block in `lmi.json` until that key was
removed. All of them test for the key with a sentinel rather than
`doc.get("env") is None`, which cannot tell an absent key from `"env": null` —
and `null` is a value everywhere else in these documents, so a merge would set
`env` to null and discard the whole block, auth token included, at exit 0.

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
    wrong type, so the 256K profile does not apply. `template._validate`
    refuses one with exit 2 rather than passing it through. The rule used to
    live in `config._env`, guarding a `claude.env` block in `lmi.json`; that
    key is gone and the rule moved one file over with the thing it guards, to
    the settings template. Same words, same `_MISSING` sentinel for the
    `"env": null` case, for the same reasons as in `fragment._validate`.
19. **An unparseable `.claude.json` is refused, not overwritten.** Treating it
    as `{}` would discard everything the user had. `jsonfile.read` raises exit
    3 and names the file; nothing is written. This used to cover
    `settings.json` too, and no longer does: `lmi install` backs it up byte for
    byte and replaces it whole, so an unparseable one would only block an
    install that was about to overwrite it regardless. The rule stands
    unchanged for `.claude.json`, which is still read, and for `lmi config
    switch`, which still merges into what it finds.

    `runner._existing_token` reads `settings.json` again — it is the only
    thing that does — and is the shape this exemption requires: it catches the
    `LmiError`, warns, and offers no token to keep. A reader added here that
    lets the raise through re-imposes the block on the one command the
    exemption was carved out for. See item 30.
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
Three belong to `lmi upgrade`, and all three are silent in the same way — the
command reports an upgrade:

22. **`lmi upgrade` never reports its own `__version__` as proof.** That
    value was imported before pip ran, so it is the *old* version whatever is
    now on disk. Success is confirmed by running the installed console script
    in a subprocess and comparing. **Silent:** the command announces
    "upgraded 0.1.0 → 0.2.0" while 0.1.0 is still installed, which is the
    stale-wheel failure with a new front end.
23. **An installation shape that cannot be upgraded is refused, not guessed
    at.** An editable checkout, a pipx install, a system-wide install:
    `installation.detect` raises exit 2 for each, before pip is invoked.
    **Silent** in three different ways — a released wheel over a developer's
    working tree; pipx's record describing a version that is gone; a `--user`
    copy that the `PATH` entry never reaches. The order of the checks is
    load-bearing: editable is tested first because a dev checkout is usually
    also inside a venv.
24. **The version probe's failure must never fail the command.** `pip index
    versions` is experimental and absent from older pips. Every failure is
    `None`, which degrades the question the user is asked and nothing else. A
    diagnostic that blocks the thing it diagnoses is worse than no
    diagnostic.

And one for `lmi config switch`, which is the whole of what `origin` means:

25. **The origin snapshot is written only if it does not already exist.**
    `config/origin.capture` takes `~/.claude/settings.json.lmi-origin` on the
    first switch and never again, which is what makes `switch origin` mean the
    settings the machine had before *any* switch rather than before the last
    one. **Silent:** written unconditionally it becomes undo-one-step while
    still being spelled `origin` — every single switch behaves identically, the
    snapshot file is there either way, and nothing at all afterwards
    distinguishes the two, except that the user's real settings stopped being
    recoverable at the second switch. The `if not exists()` is the entire
    mechanism; do not simplify it into an unconditional write.

And four for `lmi schedule -v`. They are numbered after the rest rather than
beside item 12 on purpose: these numbers are referenced by name elsewhere —
`tests/test_docs.py` pins item 22 — so the list is appended to, never
renumbered.

26. **`-v` must not be combinable with an `--output-format` in `-f`, and the
    renderer must degrade out loud.** `-f` is appended last and claude takes
    the last occurrence of a repeated option, so `-f "--output-format json"`
    overrides the `stream-json` the renderer depends on.
    `config._reject_output_format` refuses the pair with exit 2; independently
    `stream.Renderer` warns once and passes everything through verbatim when a
    line is not a JSON object, which is the half that covers a future claude
    version changing the format on its own. **Silent** without both: the
    activity block goes quiet, the iteration still exits 0, and nothing
    distinguishes "claude did nothing worth showing" from "lmi could not read
    what claude said". A duplicate `--verbose` is deliberately still allowed —
    it is a boolean and idempotent, where `--output-format` is last-wins.
    Generalising the check into flag deduplication would mean lmi learning
    claude's flag grammar, and risk dropping a user's flag silently.
27. **`PromptLog.full_done` means "has the full prompt been logged yet", not
    "is this iteration 1".** An iteration can die before `prompt.compose` — a
    vanished temp workspace — and item 12 means the loop deliberately survives
    that. Keyed off the iteration number instead, iteration 2 logs only the
    state under a header claiming the rest is "unchanged from the first logged
    prompt" when no prompt was ever logged. **Silent:** the log looks complete
    and the run exits 0, and the forty missing lines are only noticeable to
    someone who already knows what they should have said.
28. **`_pump` scans the raw line for quota wording, never the rendered one.**
    Under stream-json the usage-limit text lives inside a JSON result or error
    event. Scanning after rendering means any future renderer change that
    summarises such an event without carrying its message through silently
    disables `[QUOTA]` — the one tag that tells an unattended run its result
    is not to be trusted. Scanning first makes that impossible however
    `stream.py` evolves.
29. **The renderer never emits a tool input's `content` field.** `ARG_KEYS` is
    an allowlist for exactly this reason: `content` carries the whole new file
    on a `Write`, so rendering it puts the state file into the log on every
    save and buries the tool calls either side of it. Not silent, but it
    destroys the readability the feature exists for.

And two for the settings template, which is how `lmi install claude` now
configures Claude Code: a `settings.json` beside the `lmi.json` that discovery
resolved, installed as `~/.claude/settings.json` verbatim but for the token.

30. **A blank auth token is refused unless there is a real token to keep, and
    the placeholder is never one.** The shipped and example templates carry
    `"ANTHROPIC_AUTH_TOKEN": "<Token from the user input>"`, and the template
    is installed whole — so a blank answer cannot mean "sign in later", and the
    only document it could otherwise produce is one carrying that placeholder
    verbatim. **Silent:** the install reports success, `~/.claude/settings.json`
    looks fully configured, the token key is present and roughly the right
    shape at a glance — and the 401 the user eventually hits points at the
    gateway rather than at lmi.

    A blank has exactly one meaning, and `runner._existing_token` is what earns
    it: the token `lmi install claude` has just read out of the
    `~/.claude/settings.json` it is about to replace. On that one branch
    `_ask_for_token` returns it and says so; on every other path it still asks
    three times and then raises exit 2 with nothing changed. The four paths
    that must keep leading to the refusal are no file, no token key (or a blank
    one), a file that no longer parses, and the placeholder — miss any of them
    and the blank-is-allowed branch is reachable with nothing behind it, which
    is this item's failure with a friendlier prompt.

    The **placeholder comparison is the load-bearing half**, and it is against
    `settings.token_of(cfg.settings)` — this run's template — not a constant.
    lmi cannot tell a credential from a string, so "is this the placeholder"
    has no answer except "is it what the operator's own template puts there".
    Do not teach `settings.compose` to recognise a placeholder instead: that
    would mean lmi learning the shape of Anthropic's credentials, and it is
    still true that compose has no way to tell one from the other — which is
    why the check lives at the point the token is *read*, before the question
    is even phrased.

    Two smaller rules ride along. Reading that file must **never fail the
    install** — `jsonfile.read` raising is a `[WARN]` and no offer, because
    item 19 is that an unparseable `settings.json` must not block an install
    that backs it up and replaces it wholesale; the read added here is not
    allowed to reintroduce the block it documents the absence of. And the hint
    printed above the question is `settings.mask`, four characters each end and
    only above a 16-character floor: the answer itself is read with `getpass`
    and never echoed, so a hint that reconstructs the token would put into
    scrollback exactly what the prompt is careful to keep out of it. The offer
    exists so the operator knows *which* token they are keeping — a machine
    re-pointed at a new gateway is where keeping a stale one silently is the
    expensive mistake — and a hint that cannot be told apart from another
    token does not serve that.
31. **The backup is now the only copy of the machine's previous settings.**
    `jsonfile.backup` must stay *before* the write in
    `runner._write_settings`, and must stay fatal when the copy fails.
    Under the old merge the user's own keys survived inside the merged
    document, so a skipped backup cost little; replacing wholesale makes that
    `.bk_<stamp>` file the entire safety net. Downgrading the failure to a
    `[WARN]` and carrying on, or moving the copy to after the write, turns an
    unwritable `~/.claude/` into silent, permanent loss of whatever the
    operator had hand-edited.

And one for the statusline, which is a settings key and a script, written by
hand in two different files in the same folder:

32. **The two halves of a statusline are checked against each other, out
    loud.** A `settings.json` `statusLine` block runs a command; the shipped
    one runs `node ~/.claude/statusline.js`, and the file that puts a script
    there is a `statusline.js` beside the `lmi.json` that discovery resolved —
    optional, unlike the template, so that a config folder written before the
    feature existed still installs cleanly. That optionality is the whole
    danger. **Silent** in both directions: a template declaring `statusLine`
    with no script beside it installs a command pointing at nothing, and a
    script with no `statusLine` in the template lands in `~/.claude` and is
    never run — each reporting success, each showing up only as a statusline
    that is not there, with nothing tying it back to the install.
    `runner._write_statusline` prints a `[WARN]` for each case and
    `tests/test_docs.py` pins the shipped pair — now the one in
    `install/default-config/`, since the checkout's `config/` folder is gone —
    because neither is an error: only the operator knows what their command actually runs, and
    refusing would break a site whose `statusLine` runs something else
    entirely. `statusline.declares` deliberately lives outside
    `template._validate`, whose contract is that every key but `env` passes
    through unexamined — a warning is not validation, and nothing here can
    reject a template.

    Two smaller rules ride along. The copy is **bytes**, through the same
    `O_BINARY` temp-file dance as `jsonfile.write` and preserving the source's
    mode: it is somebody's script, and normalising its line endings or dropping
    its executable bit is lmi editing a file it was only asked to move. And it
    is written **before** `_write_settings`, so `~/.claude` never holds a
    settings document naming a script that is not there yet, and a failed copy
    stops the command with the machine's previous settings still in place.

And ten for the two backends. Appended, never renumbered: `tests/test_docs.py`
pins item 22 by name.

33. **The `schedule` log header must name the backend and what chose it.**
    Both backends exit 0 on success and neither marks the state file, so
    without `Backend   : <mode> (from <source>)` **nothing** in an unattended
    run's only record distinguishes a run that used the intended backend from
    one that did not. **Silent** by construction: the entire point of a switch
    is that you cannot tell from the outcome — the difference shows up only in
    cost, latency and which settings file was read. The source is half the
    line; `sdk` alone does not say whether a config file chose it or nothing
    did.
34. **Neither backend ever falls back to the other at run time.** An
    unimportable SDK under `sdk` mode is exit 2 naming all three fixes
    (`lmi install claude`, `pip install "lmi[sdk]"`,
    `lmi config schedule --mode cli`), raised before the lock and before the
    header. The fallback is the *installer's*, once, out loud, written into a
    file a human can read. **Silent** the other way: a runner that quietly
    changed backend produces a log that looks exactly like a correct run.
35. **`lmi install` decides the mode by importing, never from pip's exit
    code.** `install/sdk.importable()` runs `sys.executable -c "import
    claude_agent_sdk"` in a **subprocess**. pip's `rc` answers "did a package
    get installed somewhere", which is not the question — it can exit 0 having
    installed into a different interpreter from the one that will run
    `lmi schedule`, which is why the install is `core/pip.prefix(sys.executable)`
    and never a `pip` from `PATH`. An in-process import inside the process that
    just ran pip can be misled by a populated `sys.path` cache, so a check that
    looks stricter than `rc` while sharing this process is not. **Silent:** the
    machine is written `sdk`, reports success, and every scheduled run
    afterwards exits 2.
36. **A failing pip warns and writes `cli`; it must not fail the install, and
    must not be quiet.** This inverts `npm.install`'s rule deliberately: npm
    failing means there is no Claude Code and the command has failed, whereas
    pip failing means one of two supported backends is unavailable and the
    other one — the one driving the binary npm just installed — works. So
    `[WARN]`, mode `cli`, carry on, exit 0, and the settings, statusline and
    onboarding documents are still written. **Silent** if the warning is
    dropped: a degradation nobody is told about is indistinguishable from
    success.
37. **The mode is written last, after every Claude config write has
    succeeded.** `schedule.mode` then only ever appears on a machine that got
    all the way through. An earlier failure leaves `lmi.json` untouched, which
    means the default — `sdk` — on a machine where pip may never have run;
    that is item 34's loud exit 2 rather than a silent wrong backend, and it is
    the right side to fail on.
38. **An absent `claude.index` means "do not install the SDK", never "use
    public PyPI".** It writes `cli` and says so, and is not an error: a site
    that only wants the CLI backend should not have to configure a mirror it
    will never use. **Silent** if defaulted to pypi.org: on an air-gapped
    machine that is a timeout, and on one with egress it installs an unvetted
    package from a different source than every other package on the box, at
    exit 0 — defeating the only reason this command exists.
39. **A mode write must land in the file discovery then resolves.**
    `config/schedule._confirm_it_wins` re-runs discovery after creating a
    config file from nothing and exits 2 if something else now wins. **Silent:**
    writing `~/.lmi/config.json` while a higher-priority `./config/lmi.json`
    exists reports success, leaves a file with exactly the right contents in
    it, and `lmi schedule` keeps the old backend for ever. Only item 33's
    header line would ever reveal it.
40. **`setting_sources` must include the user source.** The sharpest asymmetry
    between the backends: the CLI read `~/.claude/settings.json` by virtue of
    *being* the CLI, while the SDK loads settings only from the sources it is
    told to. **Silent:** omit it and SDK mode runs against the wrong endpoint
    with no credentials — while `lmi config switch`, whose entire purpose is
    changing that file, quietly stops affecting `lmi schedule` at all. Do not
    simplify `SETTING_SOURCES` back to omitting the argument, and do not trim
    it to `["user"]`: project and local are what the CLI reads too.
41. **A message stream that ends with no `ResultMessage` is a failure, not a
    zero.** `sdk._Sink.rc` therefore *starts* at a non-zero code and only a
    `subtype == "success"` result lowers it to 0. **Silent** if mapped to 0:
    that is regression 1 with a new front end — the iteration is counted as a
    success, the run exits 0, and nothing was done. The failure code is
    deliberately not `ITERATION_ERROR_RC` (90), which means "never reached
    Claude at all"; a call that came back wrong is a different fact.
42. **`permission_mode` must be a non-interactive one, and `can_use_tool` must
    never be set.** Invariant 3 is that nothing in the unattended runner may
    ever wait for a keypress, and the SDK's default permission mode is not
    that — it asks. `acceptEdits` is the narrowest mode that still lets the
    state file be written. Not silent but worse: the run **hangs** instead of
    failing, and a `can_use_tool` callback that awaits anything is a keypress
    wait wearing a library's clothes.

    Two smaller facts ride along, both established rather than guessed:
    `lmi upgrade` **cannot** remove or shadow the `sdk` extra — `upgrade/pip.py`
    always passes `--no-deps` and never `--force-reinstall` or a fresh venv, so
    it installs `lmi` and touches nothing else. Establish it again with
    `python3 -m pip show claude-agent-sdk` either side of an `lmi upgrade`. And
    the SDK front end in `stream.py` matches messages by **class name and
    `getattr`**, never `isinstance`, which is what keeps `claude_agent_sdk`
    imported in exactly one module and lets the renderer be tested with fakes.

And two found by running the suite for the first time, against a real installed
SDK, after the two-backend work was written. Both were written *because* the
code was correct in the obvious places and wrong in one that is not obvious.

43. **The quota scan must read `rate_limit_info`, which is the whole payload of
    the SDK's `RateLimitEvent`.** `sdk._TEXT_ATTRS` is an allowlist of the
    attributes scanned before anything renders them, and it began as
    `result`/`content`/`data` — the three obvious ones. `RateLimitEvent` carries
    its wording in none of them, so **the SDK's own name for the thing
    `[QUOTA]` exists to catch was the one event that could not raise the tag**,
    while the CLI backend caught the equivalent for free by scanning whole raw
    lines. **Silent, and asymmetric between the backends** in the one signal
    that says "do not trust this iteration": the iteration exits 0, the log
    reads clean, and the two modes disagree about a rate limit neither operator
    nor test would think to check. `RateLimitEvent` is also matched explicitly
    in `stream.py` rather than left to `_give_up`, so it does not spend the one
    degrade warning an iteration gets on a type lmi does know — which would let
    a genuinely unknown type arriving later pass in silence.

    The lesson generalises past this field: a scan whose input is an allowlist
    of attribute names is only as complete as the last time somebody compared it
    against the installed package. `tests/test_sdk_fake_shapes.py` is where that
    comparison happens, and it must keep skipping rather than passing when the
    extra is absent.
44. **The `sdk` extra's version floor and the floor `lmi install claude` asks
    pip for must be one string.** The extra's constraint governs only
    `pip install "lmi[sdk]"`; `install/sdk.py` names the distribution to pip
    directly, so a bare `claude-agent-sdk` there accepted whatever the index
    offered. **Silent:** an index mirroring a version too old for
    `ClaudeAgentOptions.setting_sources` installs cleanly, imports cleanly, is
    written `sdk` — and then raises a `TypeError` on every iteration
    afterwards. `install/sdk.importable()` cannot see it, because importing the
    package is not the same as being able to build its options. Hence
    `install/sdk.REQUIREMENT`, and `tests/test_packaging.py` pinning it equal to
    the extra's. Keeping the floor high is safe on an air-gapped site: a pip
    that cannot satisfy it fails, and item 36 then writes `cli` and exits 0.

And one more, from the first `lmi schedule` run that ever reached a real SDK.
Both halves are about the same three seconds of output and neither was
guessable: **a failed SDK call does not look like anything the design expected.**
With no valid credential, `claude_agent_sdk` 0.2.136 emits an
`AssistantMessage` saying "Not logged in", then a `ResultMessage` carrying
**`subtype == "success"` and `is_error == True` at the same time**, and *then*
raises `Exception("Claude Code returned an error result: success")` on the error
envelope behind it.

45. **`sdk._rc_of` consults `is_error` AND `subtype`, and `sdk.call` keeps what
    the sink already computed when the SDK raises after a result.** Three
    versions of this were wrong in three different ways, each silent:
    - **`subtype` alone** counts a failed call as a success, because the subtype
      of a real failure is `"success"`. Exit 0, "1 succeeded", nothing done —
      regression 1 with a new front end. A zero now requires both fields to
      agree, and either one may fail the call.
    - **letting the exception propagate** discards `rc` and `quota`, both
      already correct on the sink. The iteration is then recorded as *skipped*
      (`ITERATION_ERROR_RC`, "never reached Claude at all") for a call Claude
      answered — item 41's distinction collapsed — and, worse, **`[QUOTA]` can
      never fire**, because `_one_iteration` reads the flag from `call`'s return
      value and never gets one. An exhausted quota is reported this way, so this
      made the tag unreachable in SDK mode in exactly the case it exists for.
    - **catching the exception unconditionally** loses item 12: a stream that
      dies before any result must still be a skipped iteration with a traceback,
      because nothing is known about it. Hence the split on
      `_Sink.saw_result` — which cannot be derived from `rc`, since
      `NO_RESULT_RC` and `CALL_FAILED_RC` are the same number by design.

    The general lesson is worth more than the fix: **every one of these was
    invisible to a green suite and to a code review, and all three fell out of a
    single two-iteration run with no credential at all.** That run costs
    nothing, needs no API key, and is written up as "Smoke-testing SDK mode
    without any credential" in `docs/schedule.md` — do it before trusting any
    change to this backend.
46. **`-f` is forwarded in both backends, and exactly four flags are refused.**
    The operator asked for parity with CLI mode, and the SDK's own
    `extra_args` gives it without lmi learning claude's flag grammar: the SDK
    renders `{"model": "opus"}` onto the argv of the `claude` it spawns, so `-f`
    reaches the same command line either way. `sdk.parse_flags` therefore
    converts *token shape* only, and knows four names — and only to refuse them:
    `output-format` and `input-format` (the SDK and the CLI speak stream-json to
    each other), `print` (the SDK owns the non-interactive mode), and
    `permission-mode` (invariant 3).

    The reason refusal is mandatory rather than fastidious: **`extra_args` is
    appended *after* the flags the SDK builds for itself, and the CLI takes the
    last occurrence of a repeated option.** So forwarding one of those four does
    not add a flag, it overrides the SDK's own — and an overridden
    `--output-format` breaks the protocol the SDK uses to parse its own child
    process, which surfaces as a run that produces no activity and no result.
    That is item 26's failure with the roles reversed. Refused, never dropped:
    `-f` is where a site puts what it cannot say any other way, so silently
    ignoring one is worse than either. Long options only — the mapping cannot
    spell a single-dash option, and mangling `-p` into `---p` is not an
    improvement on saying so.

And one from reading a real `-v` log, which is the only place it could have been
found: every test of the renderer asserted that a short string survived, and a
short string always did.

47. **A row that carries text is budgeted by `TEXT_WIDTH`; only a tool
    *argument* gets `ARG_WIDTH`.** `_clip`'s default parameter is `ARG_WIDTH`,
    so a row function that called `_clip(x)` without naming a width silently
    inherited the budget for a file path — 160 characters. `_result_row` did,
    and so did `_text_row` and `_thinking_row`, which meant **the tool output an
    operator opens a `-v` log to read was sized as if it were a path**: every
    grep's hits, every file's head and every stack trace was cut off mid-word,
    `...`, at a sentence and a half.

    Not silent in the usual sense — the `...` is right there — but it fails in
    the direction that reads as working. The log still has one row per event and
    still lines up between the two backends, so it looks complete; it just says
    that claude ran something and never what came back. `_init_row` (80),
    `_tool_row`'s name (20) and `_done_row`'s result text (200) had each named a
    width of their own, so the three content rows were the ones that never did,
    not a considered choice to make them narrow.

    The ceiling stays, and 2000 is not a step towards removing it: a `Read`
    returns whole files, so an unbounded result row is item 29's harm arriving
    through a tool's *output* instead of its input — every file claude opens, in
    full, in the log. Do not collapse the two constants back into one. A single
    width can only be right for one of them, and the merge direction that looks
    tidiest is the one that reinstates this bug.

    One test had to be repaired rather than re-asserted, and it is the
    interesting part. `test_a_clipped_message_inside_a_json_event_is_still_flagged`
    pins item 28 by placing the quota wording **past the clip width**, so that
    finding `[QUOTA]` proves the scan read the raw line. Its padding was a
    literal `"padding " * 40` — 320 characters, comfortably past 160 and
    comfortably short of 2000 — so widening the clip did not break the rule, it
    dissolved the test's premise, and the test would have gone green for the
    wrong reason had its second assertion not caught it. The padding is now
    `tests/conftest.py`'s `QUOTA_PAD_WORDS`, derived from `stream.TEXT_WIDTH`
    itself. **A test that works by exceeding a constant must read that
    constant**, or it stops testing anything the first time the constant grows,
    and nothing goes red to say so.

And two for the config folder packaged inside the wheel, which is what makes
`pip install lmi` the whole installation.

48. **The packaged default is last, it is announced, and it is copied out
    before anything is written to it.** `install/default-config/` holds an
    `lmi.json` and the `settings.json` beside it, laid out like any config
    folder so `template.load` finds the template for free. Three properties, and
    each is a silent failure without it.

    It is the **last** candidate, after `~/.lmi/config.json`, so every file a
    human placed outranks it — anything else is item 21 shipped as a feature.
    It reaches discovery through a `fallback` parameter on `core_config.find`
    and **must not** become a candidate inside `find_optional`: `lmi schedule`
    and `lmi config schedule` search through that function, and a packaged
    candidate there would point a `--set` at `site-packages`.

    `runner._describe` annotates it `(packaged default)` in the `Config:` line
    printed before the first npm command. **Silent without it:** a mistyped
    working directory used to be exit 2, "no config file found", and now
    installs successfully from whatever registry the wheel carries, with output
    indistinguishable from a run that read the site's own file.

    `defaults.adopt` copies **every file in the folder** to `~/.lmi/`
    immediately before `_write_mode`. **Silent without it:** `schedule.mode`
    written into `site-packages` is item 39 reached from a new direction — a
    file with exactly the right contents in it that `lmi schedule` never reads
    and the next `pip install --upgrade` replaces. It runs *after* the last
    Claude write, so a failed install leaves no config folder claiming to have
    provisioned the machine.

    Every file rather than the two it used to name, because the packaged folder
    is now the only default that ships: a `statusline.js` or a
    `settings_switch_<name>.json` in it is part of that default, and copying
    only `lmi.json` and `settings.json` leaves the rest in `site-packages`,
    where `lmi config switch` never looks. `lmi.json` becomes `config.json` —
    the home-level name discovery searches for — and everything else keeps its
    own name; adopting the config under its packaged name would produce a
    folder the next search walks straight past. A folder missing either
    required half is `BROKEN_PACKAGE`, a broken lmi rather than a
    misconfiguration, refused before anything is copied.

    `_back_up` is the other half of copying into a folder that may not be
    empty, and it must stay **before the first write and fatal**, for exactly
    item 31's reason. `adopt` fires when discovery found no config *file*,
    which does not mean an empty folder: a `~/.lmi` holding only a
    `settings.json`, only switch files, or a previous backup still falls
    through and is copied into. Those files are the operator's and this copy is
    the only version that survives, so a failed backup stops the adoption with
    nothing changed — the packaged default is still in the wheel and the
    command can be re-run. Earlier `backup_` directories are **skipped, not
    copied**: they live inside the folder being backed up, so including one
    nests every generation inside the next, the directory doubling on each
    adoption while the oldest copy sinks a level deeper each time.

    Two smaller ones ride along. `pyproject.toml` needs the
    `[tool.setuptools.package-data]` entry or the folder is in the checkout and
    **not** in the wheel — a green suite and broken installs, which is why
    `test_declares_the_packaged_config_folder_as_package_data` asserts the
    declaration itself; from a checkout there is nothing else to look at. Its
    glob is `default-config/*`, not `*.json`: the folder now carries a
    `statusline.js` too, and a `.json`-only glob would ship the checkout's
    behaviour and not the wheel's.

    The folder **does** now ship a `statusline.js`, and its template declares
    the `statusLine` that runs it — the operator asked for that, and it
    reverses what this item used to say. Item 32's rule is unchanged and is
    what makes it safe: both halves or neither, checked out loud. The earlier
    reasoning against it — one script in the wheel gives every site the same
    statusline — is answered by `adopt` copying it to `~/.lmi/`, where a site
    edits its own copy, and by the packaged folder being the only default that
    ships rather than an unavoidable one.

    Its two URLs are the public npm registry and public PyPI, so the fallback
    path provisions a machine with internet access end to end. That is **not**
    item 38 being softened: that rule forbids *inferring* public PyPI from an
    absent `index`, and `config._index` still returns None and still refuses to
    default. This is a value written in a file, printed before anything runs,
    consented to at the SDK question and left in `~/.lmi/config.json` where the
    operator can see it. Do not move it back into the code as a default for a
    missing key.
49. **Nothing about npm's TLS is inferred.** `_configure_npm` used to read "no
    `cafile`" as "verification cannot work here" and run
    `npm config set strict-ssl false`. Right for an internal Artifactory behind
    a private CA, wrong for every registry whose certificate already verifies —
    and the setting is **global and permanent**, covering every later
    `npm install` by that user, for every package. Item 48 made it the default:
    a bare `pip install lmi` would have turned verification off on the machine.
    A config setting neither key now leaves npm alone; `"strict-ssl"` says so
    explicitly, and `true` is the repair path for a machine an older `lmi`
    turned it off on. `cafile` with `"strict-ssl": false` is exit 2 —
    verification off means the CA is never consulted, so `cafile` would silently
    do nothing. The key is npm's own spelling, and
    `config._refuse_misspelt_strict_ssl` turns `strict_ssl` / `strictSsl` /
    `strictSSL` into exit 2: unknown keys pass unexamined by design, so a near
    miss would leave TLS in whatever state the machine had while the config
    states in plain sight that it was configured. One consequence to keep: a
    private CA now fails loudly at `npm install`, which is why `INSTALL_FAILED`
    grew a third hypothesis naming both keys.

    The same holds one file over, in `sdk._index_argv`, and it was found by a
    real run rather than by the suite: the absence of a `cafile` used to buy pip
    a `--trusted-host`, and once the packaged default named an `index` that
    guess ran on every fallback install. **One key governs both tools**, like
    `cafile` does — one decision about one pair of hosts, where two spellings
    would be two chances to configure half a machine. The asymmetry that stays
    is real: npm's write is global and permanent because npm has no
    per-invocation registry flag, while `--trusted-host` covers one command and
    no `pip.conf` is ever written. Do not "fix" that by writing one.

And two for named switch files, which put a keyword and a filename into one
argument for the first time.

50. **A switch name is a name, not a path.** `catalog._validate` allows
    `[A-Za-z0-9._-]+` and refuses `.` and `..` outright, so the argument cannot
    be a path expression. Without it `lmi config switch ../../etc/passwd` reads
    an arbitrary JSON document off the machine and `deep_merge`s it into
    `~/.claude/settings.json` — an escape from the config folder, and a way to
    build a settings file out of something that was never one. Not silent, but
    the damage is done before anything is printed. The narrow character class
    is deliberate: a name is typed at a shell and appears in the README, so
    there is nothing for a wider one to buy. `--file` is the way to apply a
    fragment from somewhere else, and it always was.
51. **`origin` is reserved, and a file claiming it is reported rather than
    shadowed.** The keyword and a switch name now occupy one positional. They
    used to be separated by `choices=["origin"]`, which removed the ambiguity
    by construction; names needed the slot, so the keyword wins instead and
    `catalog.RESERVED` refuses `origin` as a name.

    Reserving it is only half. A `settings_switch_origin.json` is then a file
    that can never be applied by any invocation, and **silent** in the way that
    costs most: it sits in the folder beside the ones that work, it is valid,
    `lmi config switch origin` reports a successful restore every time, and
    nothing anywhere connects that to the fragment never having run. Hence the
    `[WARN]` from `_list`, and `scan` returning reserved names as a second list
    rather than dropping them — dropping them is what makes the file invisible.

    The failure that the old `choices=` guarded — a filename read as the
    restore keyword — is unchanged and is the worse direction: a restore
    discards every switch since the first one and consumes the snapshot, so a
    name accidentally taking that path is not recoverable by running the
    command again. It is pinned by
    `test_a_name_never_takes_the_restore_path`, which is where that MANDATORY
    test went when its mechanism was removed. Repairing a test's premise is not
    relaxing its assertion; deleting it would have been.

And one for `lmi config init`, the second way the packaged folder lands in
`~/.lmi`. It exists because the first way was the *last step of provisioning
Claude Code*: an operator who deleted `~/.lmi` had to run `lmi install claude`
again — npm, the settings document, the onboarding keys — to recover files that
were inside the wheel the whole time, and a plain `pip install lmi` or either
bootstrap script created nothing, a wheel having no post-install hook. The four
installer scripts now run the command after the wheel, warned and never fatal
(item 36's reasoning: the install above it succeeded).

52. **`fill` never overwrites, and that is not a convenience — it is the whole
    safety of running it on every install.** `defaults.adopt` may replace what it
    finds because `_back_up` has copied the folder into `backup_<stamp>/` first;
    `defaults.fill` copies nothing anywhere, so the `fs.kind(dest) != fs.MISSING`
    skip is all that stands between an operator's edited `settings.json`, their
    own switch files and their hand-written `statusline.js` and the packaged
    examples. **Silent:** the scripts run `lmi config init` on every install and
    every upgrade, so an overwriting version reverts a site's whole configuration
    on a routine re-install, at exit 0, with `created` printed for each file and
    no copy of the previous version anywhere on the machine. The one visible
    consequence — an install that suddenly points at `gateway.example.com`
    again — looks like the operator's own mistake.

    A destination is kept whatever it *is*, not only when it is a file: a
    directory where `statusline.js` should be is somebody's mistake, and clearing
    it to make room is the one delete in this command, with nothing behind it.
    The `packaged_files` refusal (item 48's `BROKEN_PACKAGE`) runs before the
    first write for the same reason it does in `adopt`, so a broken wheel leaves
    the folder as it was rather than half filled.

    Two smaller rules ride along. `init` takes **no `--config`**: the folder it
    fills is the one discovery searches at the home level, which is the only
    folder whose absence it exists to fix, and a `--config` would let it build a
    second config folder for the operator to keep in step with the first. And the
    shipped `direct` switch names `https://api.anthropic.com` **explicitly**
    rather than removing `ANTHROPIC_BASE_URL`, because `deep_merge` has no delete
    and `null` is refused by item 18 — a switch can only ever point the endpoint
    somewhere, and `docs/config.md` says so where an operator writing their own
    fragment will meet it.

And seven for one claude session carried across the intervals, which is the
first thing in this command with two memories instead of one. The state file is
still the durable one; the session is the one that makes an iteration continue
rather than re-read.

53. **The session id is minted by lmi, never learned from claude's output.**
    `uuid4`, written to the sidecar before the first call, passed as
    `--session-id` and then `--resume`. Without `-v` the CLI backend logs
    claude's plain text, which carries no session id anywhere, so observing one
    would mean forcing `--output-format stream-json` onto a run that did not ask
    for it - item 26 from the other side. **Silent:** an observed-id design
    works perfectly under `-v` and silently loses continuity without it, which
    is how most unattended runs run. Minting also means the id exists on disk
    *before* the call, so an iteration killed mid-flight still leaves something
    to resume.
54. **A quota failure must not discard the session.** The handle is dropped only
    on `backend.UNRESUMABLE_RE`, never on a non-zero exit in general, and
    `QUOTA_RE` and that pattern must never overlap - a test asserts it.
    **Silent:** the one scenario this feature exists for - a usage limit at
    iteration 1 - quietly becomes N unrelated fresh sessions, each exiting 0,
    with the state file's summary the only thing carried and nothing in the log
    to say a conversation was thrown away. This rule is one condition in one
    `if` in `runner._one_iteration`, and inverting it breaks no other test,
    which is why `tests/test_docs.py` pins this paragraph by name.
55. **The handle is dropped on exactly the failure that means it is gone, and
    the retry happens at most once.** Never dropping it makes every remaining
    iteration fail identically against a dead conversation, each failure looking
    like claude's own; retrying without a bound turns one iteration into an
    unbounded call loop. The retry is affordable *because* the failure is local:
    claude answers a missing session with "No conversation found with session
    ID: <id>" and exit 1 before any API call, verified on 2.1.235, so the wasted
    attempt costs nothing while waiting for the next interval costs a third of a
    `-c 3` run. `quota` is taken from **either** attempt, for item 43's reason.
56. **The sidecar is backed up or kept in the same breath as the state file.**
    One rule, `-r`, applied to both; `--no-session` touches the sidecar not at
    all, because an opt-out for one run must not destroy the session a later
    `-r` run would continue. **Silent:** a run without `-r` that starts a clean
    state file and resumes yesterday's session has two memories describing
    different work, both plausible, and exits 0 either way. The two calls are
    adjacent rather than nested - `session.prepare` runs before the header
    because the header must name the session (item 58), and `state.prepare`
    after it - so the pairing is pinned by a test on the pair, not by structure.
57. **`-f` may not carry the session flags while continuity is on.** Six names -
    `--resume`, `-r`, `--continue`, `-c`, `--session-id`, `--fork-session` -
    refused with exit 2, whole tokens only, with `--no-session` named as the way
    to take over and forwarding all six untouched. **Silent:** `-f` is appended
    last and claude takes the last occurrence of a repeated option, so the
    user's flag replaces lmi's own rather than adding to it, and the log still
    reads clean. This is why `_session_flags` goes *before* `cfg.user_flags` in
    the argv and must stay there.
58. **The header names the session and what chose it.** Item 33's rule for the
    second switch in this command, and for the identical reason: a resumed
    iteration and a fresh one both exit 0, neither marks the state file, and
    cost is the only other difference. `Session   : on (from <source>) - <id>
    (new | resuming, created <when>)`, or `off (from <source>)`. The source is
    half the line - `on` alone does not say whether a config file, `--no-session`
    or nothing at all decided.
59. **`fork_session` is never set, and the SDK's session fields are checked
    before the lock.** A forked resume returns a *new* id every iteration, so the
    sidecar goes stale while every iteration still looks like a correct resume.
    `continue_conversation` is absent for the neighbouring reason: it means "the
    most recent conversation in this directory", which is claude choosing rather
    than lmi, so any other claude run in the same `-d` between two intervals
    would silently steal the continuity. And `sdk.require(session=True)` checks
    `ClaudeAgentOptions` really has `session_id` and `resume`, because passing a
    keyword a dataclass does not define is a `TypeError` on **every** iteration -
    item 44 with a new field name. The floor did **not** have to move for this:
    `claude-agent-sdk==0.2.136`, the version both `pyproject.toml` and
    `install/sdk.REQUIREMENT` already name, has both fields and a `session_id` on
    `ResultMessage`, verified by inspecting the installed package and pinned by
    `tests/commands/schedule/test_sdk_fake_shapes.py`. The check is for a machine
    whose installed SDK is *older* than the floor, which an air-gapped mirror can
    easily be, and it is scoped to `session=True` so nothing that ran before this
    feature stops running because of it.

    One asymmetry is deliberate and must stay declared rather than faked: SDK
    mode compares the session id that answers against the one it asked to resume
    and warns on a mismatch, and CLI mode cannot, because its plain output
    carries no id. `docs/status.md` records that gap as unmeasured; a check
    invented for the CLI side would mean reading claude's undocumented session
    store.

And four for `lmi upgrade` learning a second source, and for the line every
other command now prints.

60. **The index arguments are passed on a repo install.** pip clones the
    repository and then builds it in an isolated environment which it populates
    **from a package index** — `setuptools` and `wheel` come from there, not from
    the repo. So a `git+` install with no `--index-url` clones successfully and
    then fails fetching build dependencies. Not silent, but it fails in the wrong
    costume: on the machines least able to reach PyPI, after the one step that
    worked, reading like a build error rather than a network one — so the
    operator inspects the repository, which was never the problem.
    `REPO_INSTALL_FAILED` names all three hypotheses for the same reason.
    `upgrade/pip._index_argv` returning `[]` for an absent index is the other
    half: `core_pip.index_argv(None, …)` would put a literal `None` into the
    argv, and "an index is optional because a repo can be the source" is this
    command's fact, not `core/`'s.
61. **Every uncertainty in the version lookup is silence, and versions compare
    as integer tuples.** No repo, no git, a non-zero exit, a timeout, a tag
    nobody can order (`nightly`, `v1.0-rc1`), a running version that does not
    parse — each answers None. **Silent in the corrosive direction:** a false "a
    newer lmi is available" is indistinguishable from a true one, and after the
    second false alarm the line is noise, so the real one months later is ignored
    too. The tuple rule is the other half and fails the same way: `"0.10.0" >
    "0.9.0"` is False as a string, which would report a machine as current for
    every release from 0.10.0 onward. `repo.version_string` exists because a tag
    NAME is not the version it carries — handing `v0.3.0` to `verify.confirm`
    fails a correct upgrade with "expected v0.3.0, got 0.3.0", which reads
    exactly like the stale-wheel failure that check exists to catch.
62. **The notice never becomes an action, and never fails a command.** It
    suggests `lmi upgrade`; it does not run it and does not prompt. Every
    exception inside `notice.maybe_say` is swallowed — including the unparseable
    config file `lmi upgrade` itself rightly refuses with exit 2, because a
    diagnostic on the startup path of *every* command must not be able to break
    the CLI. It is also the only network call on `lmi schedule`'s startup path,
    so the `timeout=3` and the 24-hour cache are load-bearing rather than
    tidy: without them a slow git host delays the first iteration of an
    unattended run on every invocation, which is invariant 3's spirit with no
    keypress involved. The cache is keyed by the repo URL, so re-pointing
    `lmi.repo` cannot report the old remote's tags.

    `tests/conftest.py`'s `_no_version_check` is the suite's half of this and
    must stay autouse: the notice runs before every dispatched command, so
    without it every test calling `main([...])` reads the **developer's own**
    `~/.lmi/config.json` and runs `git ls-remote` against whatever it names — a
    network call inside a unit test, whose answer changes underneath the suite.
    `test_notice.py` puts the real function back for itself, the way the
    schedule conftest does for `backend.resolve`.
63. **A tag is not evidence of an upgrade, and the source is named.** Item 22
    restated, because a git source makes it easier to get wrong: the tag is what
    was asked for, and the only thing that says what is installed is
    `verify.confirm` running the installed console script in a subprocess. The
    `Source:` line names repo or index for item 33's reason — both end in the
    same "Upgraded 0.2.1 → 0.3.0", so nothing else distinguishes a machine
    upgraded from the site's audited mirror from one upgraded off a git tag. And
    `install/default-config/lmi.json` carries `lmi.repo` but **never**
    `lmi.index`: lmi is not published to public PyPI, so a packaged index could
    only ever resolve a stranger's package of that name, while a git URL names
    one repository. `test_the_shipped_default_config_names_no_package_index_for_lmi`
    is that rule, and it is the narrowed form of a test that used to forbid the
    whole section — the assertion moved to the danger, the danger did not move.

---

## 4. Rules for editing

1. **Run the suite after every change** and say in your report that you did:
   `python3 -m pytest tests/ -q`. It ran in under three seconds and it costs
   nothing — several bugs above only appear with awkward paths, or only when a
   claude call fails.

   **964 passed, 21 skipped, in about seven seconds** — measured, not estimated.
   It was 505 (1 skipped) before the two-backend work, 664 before item 47, 704
   before item 30 grew its keep-the-existing-token branch, 722 before named
   switch files, 750 before the packaged folder became the only default, 756
   before `lmi config init`, 769 before session continuity and 859 before the
   repo source and the availability notice.

   The three seconds it gained are `fake_git` and `fake_claude` subprocesses,
   not slower code: the new suites spawn a real interpreter per call, the same
   way the CLI backend's tests always have.

   The number written here had drifted to 669 while the suite was actually at
   704, which is worth a sentence because of what it costs: the point of
   recording it is that a report saying "the suite passes" can be checked
   against something, and a stale figure quietly turns 35 tests appearing into
   evidence of nothing. Re-measure it, do not adjust it by the count of tests
   you think you added.

   The 21 skips are the point of the number, not noise. Twenty are
   `test_sdk_fake_shapes.py`, which is the only module that validates the SDK
   fake against the real dataclasses and which skips rather than fails when the
   `sdk` extra is absent; the twenty-first is a Windows-only clause. So the
   default run leaves the SDK backend's shapes unchecked, and making the package
   importable then re-running is the run that checks them: **984 passed, 1
   skipped**. Both numbers are worth knowing, because a green default run is not
   evidence that the SDK backend matches the SDK it will meet.

   **Both numbers above are now measured**, which ends four consecutive changes
   of the second one being arithmetic. This machine still cannot `pip install`
   into its own interpreter — the Python is PEP 668 externally managed and
   `python3 -m venv` fails for a missing `ensurepip` — so the way it was
   measured, and the way to measure it again, is a `--target` install and a
   `PYTHONPATH`:

   ```bash
   python3 -m pip install --target=/tmp/sdklib "claude-agent-sdk==0.2.136"
   PYTHONPATH=/tmp/sdklib python3 -m pytest tests/ -q     # 984 passed, 1 skipped
   ```

   That is worth keeping written down: it is the only way this machine can run
   the twenty tests that check the fake against the real package, and pinning
   the floor version rather than taking the newest is what makes the run an
   answer about the version lmi actually promises to work with.
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

   The one distinction worth drawing, because item 47 hit it: repairing a
   test's *premise* is not adjusting its *assertion*. That test needed the
   quota wording to fall past the clip width, and widening the clip stopped
   the fixture supplying enough padding — the rule was untouched, the setup
   stopped reaching it. Restoring the setup is right; relaxing the assertion
   would not have been. Tell the two apart by inverting the guard the test
   pins and checking it still goes red, which is the only real evidence that
   a repaired test still tests anything.
6. `os.geteuid` is Unix-only and a `skipif` argument is evaluated at import time,
   so permission tests use the shared `skip_as_root` marker in `tests/conftest.py`
   rather than a bare call, which would lose a whole module to an
   `AttributeError` during collection on Windows.

---

## 5. Testing

```bash
python3 -m pytest tests/ -q          # 964 passed, 21 skipped - no install needed

# The 20 skips are the SDK shape checks. Make the package importable to run
# them; on a PEP 668 machine with no working venv, --target plus PYTHONPATH is
# the way in. See section 4.1.
python3 -m pip install --target=/tmp/sdklib "claude-agent-sdk==0.2.136"
PYTHONPATH=/tmp/sdklib python3 -m pytest tests/ -q    # 984 passed, 1 skipped
```

The SDK backend's tests need `pip install -e ".[sdk]"` for the one module that
validates the fake's message shapes against the real dataclasses; every other
test runs without it and that one skips rather than errors.

Fixtures worth knowing, in `tests/conftest.py` and the four per-command
`conftest.py` files under `tests/commands/`:

| Fixture | What it gives you |
|---|---|
| `fake_claude` | A fake CLI on an exclusive PATH; records argv and the composed prompt per call, and can be told to misbehave through `FAKE_RC`, `FAKE_OUT`, `FAKE_STATE_FILE`, `FAKE_COMPLETE_AT`, `FAKE_PROSE`, `FAKE_BLANK_FIRST_LINE`, `FAKE_WRECK_TMP`, `FAKE_SESSION_GONE`, `FAKE_SESSION_GONE_QUOTA` |
| `fake_npm` | The same trick for npm — an exclusive PATH, argv recorded per call, `FAKE_NPM_RC` and `FAKE_NPM_FAIL_GLOBAL` (fail only when a global flag is present, which is how the `--global` fallback is exercised without root) |
| `fake_git` | A fake `git` on an exclusive PATH, with the three answers that matter: `tags()`, `raw()`, `rc()` and `hang()`. Methods rather than raw env vars, because every test using it is about what lmi does with an answer |
| `fake_pip` | A fake interpreter that records every `-m pip` argv and answers `index versions`, plus a fake installed `lmi` command. pip is never found through `PATH` — it is `<interpreter> -m pip` — so the seam is the interpreter. `FAKE_PIP_RC`, `FAKE_PIP_LATEST`, `FAKE_SCRIPT_VERSION`, `FAKE_SCRIPT_RC`, `FAKE_SCRIPT_STDERR`, `FAKE_SCRIPT_BOM`, `FAKE_SCRIPT_PREFIX` |
| `home` | A throwaway `HOME`/`USERPROFILE`, so no test can touch the developer's real `~/.claude`. Defined separately in the `install` and `config` conftests rather than shared. Every `config` test reaching `settings_path()` or the snapshot must take it, or it writes to the real home |
| `answers` | Two of these now, one per command: `tests/commands/install/test_runner.py`'s is a scripted queue behind `prompts.confirm/secret/text`; `tests/commands/upgrade/test_runner.py`'s is confirm-only, since that command asks exactly one yes/no question. Neither test reaches a real stdin |
| `make_cfg` | A `Config` factory, so its ten fields are built in one place |
| `readonly_dir` | A 0o500 directory, restored on teardown |
| `on_windows` | Takes the Windows branch of `paths.py` (patches `_on_windows`, never `os.name`, which pathlib reads at instantiation). The install suite patches `gitbash.on_windows` for the same reason |
| `deny_touch` | Makes the writability probe fail the way `C:\Windows` does |
| `skip_as_root` | The root-skip marker described in section 4 |

`FAKE_SESSION_GONE` makes the fake answer a `--resume` with claude's own "No
conversation found with session ID" line and exit 1, which is how item 55's
one-shot retry is exercised without a real session store;
`FAKE_SESSION_GONE_QUOTA` adds quota wording to **that** attempt and nowhere
else, which is the only way to tell "the tag survives the retry" from "the retry
mentioned it too" — with the wording in `FAKE_OUT` the test passed either way.

`FAKE_PROSE` and `FAKE_BLANK_FIRST_LINE` are the fixtures for regression 2 — they
write a state file that says `IN_PROGRESS` on line 1 while mentioning
`TASK_STATUS: COMPLETE` elsewhere, which is what real claude does. Widening the
completion check must turn those tests red.

What a fake CLI can **never** cover is how the real one behaves: regressions 1 and
2 were both found by real runs, not by tests. `docs/status.md` is where that
lives now: what has actually been executed on a real machine, the eight
measurements still outstanding, and the five `lmi install claude` checks that
only a real Artifactory and a real Windows box can settle. It is one file
because the four places those notes used to sit could disagree with each other
and did.

`tests/test_docs.py` is the one module that tests documentation rather than code:
that `examples/lmi.json` still passes `config.build_config` and
`examples/settings_switch.json` still passes `fragment.load`, that the user
documentation still spells the three silent keys and still documents
`lmi config switch`, that invariant 3 above stays scoped to `schedule`, that
`install/default-config/` still holds the `statusline.js` its `settings.json`
declares (item 32, which is only a `[WARN]` at run time and so needs pinning
somewhere that fails), that every switch file in that folder is one
`fragment.read` accepts and `catalog.scan` can name — a shipped fragment that
exits 2, or one called `origin`, is a switch nothing can ever apply — and that
item 22 above is still in this file.

Those documentation assertions read `user_docs()` — `README.md` plus the
reference pages and the four install guides, concatenated — rather than one
file, because the user documentation was split into several and a fact may move
between them. `USER_DOCS` is an explicit tuple rather than a glob over `docs/`
for the reason `commands/__init__.py` is an explicit registry: a glob would
admit `docs/superpowers/`, where the design specs already spell most of these
needles out, and every one of those tests would pass while the documentation a
user reads said nothing at all. The `test_the_readme_*` names predate the split
and are kept, because several specs cite them by name. Both examples are what a new site copies, so one going
stale is a usage error on somebody's first day. The item-22 check is the odd
one: it guards
a paragraph rather than a file a user touches, because that rule exists nowhere
else — one line of code, no symptom when inverted, and this file the only place
that says why.
