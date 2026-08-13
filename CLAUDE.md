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
  stream.py                 `-v` only: two front ends onto one set of rows
  sdk.py                    the SDK backend; the ONLY importer of the SDK
  runner.py                 the loop, the seam, and the CLI backend
  exit_codes.py             this command's own codes (1, 3, 4)
lmi/commands/install/       `lmi install claude`, as a self-contained package
  config.py                 arguments, config-file discovery, the frozen Config
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
  switch.py                 `lmi config switch`: the flow
  fragment.py               finding, reading and validating the switch file
  merge.py                  the recursive merge
  origin.py                 the write-once snapshot
  schedule.py               `lmi config schedule`: show and set the backend
  exit_codes.py             this command's codes (3, 4), shared by both verbs
lmi/commands/upgrade/       `lmi upgrade`, as a self-contained package
  config.py                 arguments, the "lmi" config section, the frozen Config
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

Three commands now import `commands/schedule/backend.py`, which is the one
exception to "commands import only from `core/`". It is deliberate, and it is
the same reasoning that moved `settings_path()` into `core/claude.py`: three
copies of the valid-mode list is three chances for one command to write a value
another refuses. It stays in `schedule/` rather than moving to `core/` because
`schedule` owns what the value *means*, and `core/` has no opinion about
backends. It must never import the SDK — `lmi config` and `lmi install` both
import it, and both have to work on a machine whose SDK is missing.

`lmi schedule` has two backends behind one seam, chosen by `schedule.mode` in
the resolved `lmi.json` and defaulting to `sdk`. `runner._select_backend` is
the only place the mode decides anything; `_CliBackend` and `_SdkBackend` each
expose `prepare` / `describe` / `call`, and `call` returns the same
`(exit code, quota?)` pair whichever one it is. **There is deliberately no
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
    `settings.json` too, and no longer does: nothing parses that file any more
    — `lmi install` backs it up byte for byte and replaces it whole — so an
    unparseable one would only block an install that was about to overwrite it
    regardless. The rule stands unchanged for `.claude.json`, which is still
    read, and for `lmi config switch`, which still merges into what it finds.
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

30. **A blank auth token is refused, because the placeholder must never be
    installed.** The shipped and example templates carry
    `"ANTHROPIC_AUTH_TOKEN": "<Token from the user input>"`, and the template
    is installed whole — so unlike every earlier version of this command, a
    blank answer has nothing left to mean. It cannot mean "keep the token
    already there" (nothing is kept) and it cannot mean "sign in later"
    (the placeholder would be written in its place). `runner._ask_for_token`
    asks three times and then raises exit 2 with nothing changed.
    **Silent:** the install reports success, `~/.claude/settings.json` looks
    fully configured, the token key is present and roughly the right shape at
    a glance — and the 401 the user eventually hits points at the gateway
    rather than at lmi. Do not "restore" the blank-is-allowed branch;
    `settings.compose` has no way to tell a placeholder from a token, and
    teaching it one would mean lmi learning the shape of Anthropic's
    credentials.
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
    `tests/test_docs.py` pins the shipped `config/` pair, because neither is an
    error: only the operator knows what their command actually runs, and
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
    nothing, needs no API key, and is described in README's testing section —
    do it before trusting any change to this backend.
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

---

## 4. Rules for editing

1. **Run the suite after every change** and say in your report that you did:
   `python3 -m pytest tests/ -q`. It ran in under three seconds and it costs
   nothing — several bugs above only appear with awkward paths, or only when a
   claude call fails.

   **669 passed, 19 skipped, in under four seconds** — measured, not estimated.
   It was 505 (1 skipped) before the two-backend work, and 664 before item 47.

   The 19 skips are the point of the number, not noise. Eighteen are
   `test_sdk_fake_shapes.py`, which is the only module that validates the SDK
   fake against the real dataclasses and which skips rather than fails when the
   `sdk` extra is absent; the nineteenth is a Windows-only clause. So the
   default run leaves the SDK backend's shapes unchecked, and
   `pip install -e ".[sdk]"` then `python3 -m pytest tests/ -q` is the run that
   checks them: **687 passed, 1 skipped**. Both numbers are worth knowing,
   because a green default run is not evidence that the SDK backend matches the
   SDK it will meet.

   The second number is the one to distrust in a report. 669 was measured on a
   machine with no `sdk` extra installed; 687 is 669 plus the 18 shape tests
   that skipped there, which is arithmetic and not a run. Re-measure it the
   next time the extra is present.
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
python3 -m pytest tests/ -q          # 669 passed, 19 skipped - no install needed
pip install -e ".[sdk]"              # then 687 passed, 1 skipped: the 18 skips
python3 -m pytest tests/ -q          # are the SDK shape checks. See 4.1
```

The SDK backend's tests need `pip install -e ".[sdk]"` for the one module that
validates the fake's message shapes against the real dataclasses; every other
test runs without it and that one skips rather than errors.

Fixtures worth knowing, in `tests/conftest.py` and the four per-command
`conftest.py` files under `tests/commands/`:

| Fixture | What it gives you |
|---|---|
| `fake_claude` | A fake CLI on an exclusive PATH; records argv and the composed prompt per call, and can be told to misbehave through `FAKE_RC`, `FAKE_OUT`, `FAKE_STATE_FILE`, `FAKE_COMPLETE_AT`, `FAKE_PROSE`, `FAKE_BLANK_FIRST_LINE`, `FAKE_WRECK_TMP` |
| `fake_npm` | The same trick for npm — an exclusive PATH, argv recorded per call, `FAKE_NPM_RC` and `FAKE_NPM_FAIL_GLOBAL` (fail only when a global flag is present, which is how the `--global` fallback is exercised without root) |
| `fake_pip` | A fake interpreter that records every `-m pip` argv and answers `index versions`, plus a fake installed `lmi` command. pip is never found through `PATH` — it is `<interpreter> -m pip` — so the seam is the interpreter. `FAKE_PIP_RC`, `FAKE_PIP_LATEST`, `FAKE_SCRIPT_VERSION`, `FAKE_SCRIPT_RC`, `FAKE_SCRIPT_STDERR`, `FAKE_SCRIPT_BOM`, `FAKE_SCRIPT_PREFIX` |
| `home` | A throwaway `HOME`/`USERPROFILE`, so no test can touch the developer's real `~/.claude`. Defined separately in the `install` and `config` conftests rather than shared. Every `config` test reaching `settings_path()` or the snapshot must take it, or it writes to the real home |
| `answers` | Two of these now, one per command: `tests/commands/install/test_runner.py`'s is a scripted queue behind `prompts.confirm/secret/text`; `tests/commands/upgrade/test_runner.py`'s is confirm-only, since that command asks exactly one yes/no question. Neither test reaches a real stdin |
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
five `lmi install claude` checks that only a real Artifactory and a real Windows
box can settle.

`tests/test_docs.py` is the one module that tests documentation rather than code:
that `examples/lmi.json` still passes `config.build_config` and
`examples/settings_switch.json` still passes `fragment.load`, that the README
still spells the three silent keys and still documents `lmi config switch`, that
invariant 3 above stays scoped to `schedule`, that `config/` still holds the
`statusline.js` its `settings.json` declares (item 32, which is only a `[WARN]`
at run time and so needs pinning somewhere that fails), and that item 22 above
is still in this file. Both examples are what a new site copies, so one going
stale is a usage error on somebody's first day. The item-22 check is the odd
one: it guards
a paragraph rather than a file a user touches, because that rule exists nowhere
else — one line of code, no symptom when inverted, and this file the only place
that says why.
