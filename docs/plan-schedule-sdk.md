# Task: give `lmi schedule` two backends — the Claude Agent SDK (default) and the `claude` CLI — installed by `lmi install claude` and switched by `lmi config schedule`

> **Historical document. Two of its "verified facts" were wrong, and
> `CLAUDE.md` is the authority on everything below.**
>
> This is the plan the work was executed from, kept because the reasoning behind
> the decisions is still the reasoning in the code. But it was written before
> anything had ever been run against a real SDK, and the first real run
> falsified two of section 0's facts:
>
> * **Fact 1 named `anthropic` as a package to install.** It is not: the backend
>   imports `claude_agent_sdk`, which does not depend on it. Only that one
>   package is installed.
> * **Fact 4 said `ResultMessage` carries no `is_error` field.** It does — and a
>   real failed call carries `subtype == "success"` *with* `is_error == True`, so
>   gating on the subtype alone counts a call that did nothing as a success.
>   `CLAUDE.md` item 45 is the corrected rule and the three ways of getting it
>   wrong.
>
> Two further silent failures found the same way are items 43 and 46, and `-f`
> is now forwarded in **both** backends (item 46) rather than refused under
> `sdk` as task 37 below says. **Where this document and `CLAUDE.md` disagree,
> `CLAUDE.md` is right.** The plan is not maintained.

Add a second way for `lmi schedule` to reach Claude: the Python **Claude Agent
SDK**, which becomes the **default**. The existing `subprocess` + stdout-parsing
CLI invocation stays, fully working and fully tested, as the other choice.

`lmi install claude` gains the pip install of the SDK packages, from the site's
Artifactory, and **writes the mode to `cli` when that install cannot be done** —
so a machine whose Artifactory has never mirrored the wheels is provisioned into
a working configuration rather than a broken default. `lmi config schedule`
reads and writes the mode afterwards.

Every invariant in `CLAUDE.md` section 1 and every behaviour in section 3 must
survive, in **both** modes.

Work through the numbered tasks **in order**. Each names the file it touches and
how you know it is done. After every task run `python3 -m pytest tests/ -q`
(505 tests, 1 skipped, under 4 seconds when this plan was written) and record the
count in the state file. Do not enter a later phase while an earlier one is red.

---

## 0. Read this before writing any code

### Verified facts

Checked against the SDK's documentation and its `pyproject.toml` on 2026-08-11,
and against this repository's own code.

1. **The package is `claude-agent-sdk`, and it is the only one installed.** It
   is Claude Code as a library — the built-in `Read`/`Write`/`Edit`/`Bash`
   tools, the agent loop and the permission system — which is what
   `lmi schedule` needs. Its dependencies are `anyio`, `sniffio`, `mcp` and,
   below 3.11, `typing_extensions`. It does **not** depend on `anthropic`, and
   `anthropic` is not installed by this plan: that package is the Client SDK for
   the Messages API and gives `client.messages.create` and nothing else — no
   tools, no agent loop. The site's Artifactory is confirmed to mirror
   `claude-agent-sdk`.
2. **The SDK does not remove the CLI, even in SDK mode.** The
   `claude-agent-sdk` wheels bundle a native Claude Code binary and spawn it;
   where pip installs the source distribution instead of a platform wheel
   (documented case: ARM64 Windows) nothing is bundled and the SDK looks for
   `claude` on `PATH`. SDK mode replaces "build an argv, pipe stdin, parse
   stdout" with "call a library and consume typed messages" — it does not make
   the machine's Claude Code install optional, so the npm half of
   `lmi install claude` stays necessary either way.

   **Which of the two forms the site's Artifactory actually serves is not yet
   known, and it changes behaviour silently.** A mirror that carries only the
   sdist — or a resolution that falls back to it — installs cleanly, exits 0,
   and produces an SDK that depends on the npm-installed `claude` being on
   `PATH` in whatever shell the scheduled run happens to use. Task 53 settles
   it; until it is settled, do not write anything into the README that promises
   either form.
3. **`claude-agent-sdk` requires Python >= 3.10**, against this project's 3.9
   floor. Because the CLI backend is staying, that is containable rather than an
   amendment — see the decisions.
4. **The SDK is async, and has no exit codes.** `query()` is an async iterator
   with no sync entry point. `ResultMessage` carries `subtype`
   (`success` / `partial` / `error`) and `terminal_reason`, and no `is_error`
   field. The CLI backend returns a real process exit code. Both must reach the
   rest of the command speaking the `rc` vocabulary
   `_log_iteration_result`, `ITERATION_ERROR_RC` and `EXIT_CALL_FAILED` already
   use.
5. **Two existing comments in this repository constrain the design, and both
   were nearly violated by the obvious approach.**
   - `install/config.py`: *"PACKAGE … Deliberately not a config key: a command
     whose target is configurable is a different command."* So the SDK package
     names are constants beside `PACKAGE`, **not** a configurable list. Only the
     *index* they come from is configuration.
   - `scripts/install-linux.sh`: the bootstrap installs the lmi wheel with
     `--no-index`, *"never reach for the network. Safe because lmi declares no
     dependencies, which tests/test_packaging.py exists to keep true."* A hard
     dependency on the SDK would break every bootstrap script on every platform.
     An optional extra keeps `dependencies = []` true and keeps `--no-index`
     valid.

### Decisions

Six, taken here. If you disagree with one, say so in the state file under
`## Notes and blockers` and follow the plan anyway — do not quietly substitute
your own.

- **The SDK is an optional extra, and invariant 4 survives intact for the CLI
  backend.** `pyproject.toml` keeps `requires-python = ">=3.9"` and
  `dependencies = []`; the SDK goes in an extra. A CLI-mode site stays
  stdlib-only on 3.9 exactly as today, `tests/test_packaging.py` keeps passing,
  and the bootstrap scripts keep their `--no-index`.
- **The default is SDK, and a missing SDK is never a silent fallback at run
  time.** Falling back is the *installer's* job, once, out loud, by writing the
  mode (Phase D). At run time an unimportable SDK under SDK mode is exit 2
  naming both fixes. A runner that quietly changes backend is the one outcome
  worse than a runner that stops: both backends exit 0 on success, so the
  difference shows up only in cost, latency, and which settings file was read.
- **The pip index is configuration; the package names are not.** `claude.index`
  joins the existing `claude.registry` and `claude.cafile` — the section
  `lmi install` already owns. **An absent `index` does not mean public PyPI**; it
  means the SDK install is not attempted and the mode is set to `cli`. Reaching
  for pypi.org unasked on an air-gapped machine is either a hang or an unvetted
  package, and on a machine with egress it silently bypasses the Artifactory
  vetting that is the whole reason this command exists.
- **Nothing about the CLI backend gets "tidied" on the way past.** `-f`,
  `_reject_output_format`, `VERBOSE_FLAGS`, `_claude_argv`, `_capture_claude`,
  `_stream_claude`, the `prompt-N.txt` / `out-N.txt` temp workspace and the
  `fake_claude` fixture all stay, unchanged. Section 3 items 26 and 28 keep
  their current meaning for that path.
- **The mode vocabulary has exactly one definition, and one writer.** Three
  commands now touch it — `schedule` reads it, `config schedule` writes it,
  `install` writes it — so the valid names, the default, the parser and the
  write all live in one module. Because `schedule` owns the *meaning*, that
  module is `lmi/commands/schedule/backend.py`, and `commands/config/` and
  `commands/install/` import it. That is a new precedent — commands currently
  import only from `core/` — and it is taken deliberately: three copies of a
  valid-values list is three chances for one command to write a value another
  refuses, which is the same failure class as two commands disagreeing about
  where `settings.json` lives.
- **No per-run `--mode` flag on `lmi schedule`, and no new install target.** The
  switch is configuration, and `lmi install claude` keeps `choices=["claude"]`.
  See Non-goals.

---

## Phase A — packaging

1. **Add the SDK as an extra, and change nothing else in `pyproject.toml`.**
   Keep `requires-python = ">=3.9"` and `dependencies = []`. Add
   `[project.optional-dependencies] sdk = ["claude-agent-sdk>=<version>"]`, with
   the lower bound read from `pip show claude-agent-sdk` after installing it —
   an unpinned SDK is how a message-type rename silently empties the activity
   log. One package, because that is the one `sdk.py` imports (fact 1).
   *Done when:* `pip install -e .` still works, `pip install -e ".[sdk]"`
   installs it, `dev` is untouched, and `tests/test_packaging.py` passes
   unchanged.

2. **Extend `tests/test_packaging.py` to pin the boundary, not just the empty
   dependency list.** It currently keeps `dependencies = []` true because the
   bootstrap scripts' `--no-index` depends on it. Add the other half: the `sdk`
   extra exists, and no module outside `lmi/commands/schedule/` imports
   `claude_agent_sdk`.
   *Done when:* moving the SDK from the extra into `dependencies`, or importing
   it from `lmi/core/`, turns that test red.

3. **State the boundary in `CLAUDE.md` invariant 4.** It now reads: `lmi/core/`,
   `lmi/cli.py`, `lmi/commands/__init__.py` and the `install`, `config` and
   `upgrade` commands are standard-library only; `lmi/commands/schedule/` may
   import the SDK, lazily, in one module. `pytest` remains importable nowhere in
   `lmi/`.
   *Done when:* section 1 says so and task 2's test enforces it.

## Phase B — the mode: one definition, one writer

4. **Add `lmi/commands/schedule/backend.py`.** The shared vocabulary from
   decision 5, and it must stay small: the two mode names (`sdk`, `cli`), the
   default (`sdk`), a parser that turns a raw config value into one of them or
   raises `LmiError(..., EXIT_USAGE)`, and the writer from task 8. **No SDK
   import here** — this module must be importable on 3.9 with no extra
   installed, because `lmi config schedule` and `lmi install` both import it.
   *Done when:* `python3 -c "from lmi.commands.schedule import backend"` works
   in an environment with no `claude_agent_sdk`.

5. **Parse the mode with a sentinel, not `.get("mode") is None`.** Section 3
   item 18's rule, fourth home: an absent `mode` key means "use the default",
   and `"mode": null` is a value the user wrote and must be refused. `null` is
   meaningful elsewhere in these documents, so the two cannot be collapsed. Any
   string that is not exactly one of the two names is exit 2 naming both valid
   names and the file the value came from — never a silent fall back to the
   default.
   *Done when:* tests cover absent, `null`, `""`, `"SDK"`, `"claude"` and both
   valid names, and the three invalid cases each exit 2.

6. **Read the mode from a `schedule` section of the resolved `lmi.json`.** Reuse
   `core/config.py`'s discovery unchanged — `--config`, `$LMI_CONFIG`,
   `./config/lmi.json`, `~/.lmi/config.json` — including `_refuse_legacy`'s
   exit 2 for a file left at the pre-move `./lmi.json` (item 21). No new search
   path and no new precedence rule.
   *Done when:* `{"schedule": {"mode": "cli"}}` in each discoverable location
   selects the CLI backend, and the discovery order is unchanged.

7. **Resolve the mode once per run, before the lock, and fail there.** A bad
   mode value, or `sdk` with no importable SDK, ends the run with one exit-2
   message *before* the header is written and before the loop starts — not five
   times over as skipped iterations.
   *Done when:* both failures produce a single message and no log iterations.

8. **Put the mode *writer* in `backend.py` too, and make it the only one.**
   Both `lmi config schedule` and `lmi install claude` write `schedule.mode`;
   two implementations is two chances to get task 12's shadowed-file rule wrong
   in only one of them. The writer validates through the task-5 parser, merges
   into the existing document, and goes through `core/jsonfile.py` — so items 19
   and 20 come free and must not be re-implemented: an unparseable `lmi.json` is
   refused rather than overwritten (exit 3, naming the file, nothing written),
   the temp file is born `0600` via `os.open(..., 0o600)` plus `os.fdopen`
   rather than chmod-ed afterwards, and `O_BINARY` keeps the write LF on Windows
   (section 4, rule 4). The exit code to raise with is a parameter, as `core/`
   cannot know a command's codes.
   *Done when:* `grep -rn "schedule.*mode.*write\|open(" ` finds no second
   writer, a corrupt `lmi.json` gives exit 3 and a byte-identical file, and a
   full `examples/lmi.json` round-trips with `claude` and `lmi` sections intact.

9. **Print the backend and its source in the `schedule` log header.**
   `_log_header` already records the resolved configuration — prompt source,
   which claude, the full flag list — because an unattended run's log is its
   only record. Add the mode and the file it came from (or "default").
   **This is the plan's central silent failure:** both backends exit 0 on
   success, so without this line nothing in the log distinguishes a run that
   used the intended backend from one that did not, and the entire point of a
   switch is that you cannot tell from the outcome.
   *Done when:* a test asserts the header names the mode and its source in both
   modes, marked `MANDATORY` in its docstring.

## Phase C — `lmi config schedule`

10. **Give `commands/config/` a nested sub-registry instead of an if/elif.**
    `config` has exactly one subcommand today and `args.py` hard-codes it.
    `schedule` is the second, which is the moment the repo's own rule fires:
    promote when a second caller appears, not in advance. Mirror
    `commands/__init__.py` — one import, one list entry, a subcommand exposing
    `NAME`, `HELP`, `add_arguments`, `run` — so a third `lmi config` subcommand
    needs no edit to the dispatch. `cli.py` still learns nothing.
    *Done when:* `lmi config --help` lists both in a deterministic order and
    `args.py` contains no subcommand-specific branching.

11. **Move `switch` behind that registry without changing its behaviour.**
    `fragment.py`, `merge.py`, `origin.py` and the current `runner.py` are
    `switch`'s, not `config`'s. Whether they move into a `switch/` package or
    stay put and are simply re-registered is your call — but item 25, the
    write-once origin snapshot, must come out byte-for-byte. That
    `if not exists()` is the entire mechanism of what `origin` means.
    *Done when:* every existing `tests/commands/config/` test passes unchanged.

12. **Add the `schedule` subcommand: `--mode sdk|cli` to set, no argument to
    show — and confirm a write actually wins.** Showing prints the current mode,
    the file it came from (or "default"), and the path a `--mode` would write
    to; build it in this task, because it is the debugging tool for tasks 5, 9
    and this one. The write goes through `backend.py`'s writer (task 8) to the
    file discovery **resolves**. When nothing is discovered, create one at a
    single documented default path and then re-run discovery to confirm the file
    just written is the one that wins — if it is not, exit 2 naming both paths
    and `--config`. Writing `~/.lmi/config.json` while a higher-priority
    `./config/lmi.json` exists otherwise reports success while `lmi schedule`
    keeps the old mode forever.
    *Done when:* an invalid `--mode` exits 2 without touching any file with the
    same message `lmi schedule` produces; a two-config-file test shows the write
    landing in the winning one; the shadowed case exits 2. Mark the last two
    `MANDATORY`.

13. **Add `exit_codes.py` entries only if this subcommand needs a code the
    `config` command does not already define.** Exit codes have owners; `0` and
    `2` are global and may not be redefined.
    *Done when:* no new global code exists and `config/exit_codes.py` is
    coherent for both subcommands.

## Phase D — `lmi install claude` installs the SDK, or sets the mode to `cli`

This phase is where the request's "try Artifactory, else default to the CLI"
lives. Its whole difficulty is that **pip exiting 0 does not mean the backend
will work**, and treating it as if it does produces exactly the failure this
project keeps paying for: a machine that looks provisioned and is not.

14. **Promote `upgrade/pip.py` to `core/pip.py`.** `lmi install` becoming the
    second caller that needs to run pip is the rule in section 2 firing again,
    on the same terms as `jsonfile.py`, `config.py` and `prompts.py` before it.
    Move only what is genuinely command-agnostic — building an argv for
    `<interpreter> -m pip` and running it — and leave the version probe and the
    self-upgrade reasoning with `upgrade`, which owns them. The exit code to
    raise with is a parameter.
    *Done when:* every existing `tests/commands/upgrade/` test passes unchanged
    and `core/pip.py` imports nothing from `lmi/commands/`.

15. **Add `claude.index` to the config section, and update all three documents
    that describe it.** `install/config.py`'s `EXAMPLE` is what a first-time
    operator pastes into their first `lmi.json` with nothing else on screen to
    copy from, so it must document every key; `examples/lmi.json` is the same
    document with real-looking URLs; and `tests/test_docs.py` pins the two key
    sets **equal**, so a key added to one and not the other fails the suite. The
    existing `claude.cafile` covers TLS for both npm and pip.
    *Done when:* all three carry `index`, and `test_docs.py` is green.

16. **Add `install/sdk.py`: the pip half, and the only place that names the
    package.** Two constants beside `install/config.py`'s `PACKAGE`, not config
    keys (fact 5): the distribution to install (`claude-agent-sdk`) and the
    module the `schedule` backend imports (`claude_agent_sdk`). They are two
    constants rather than one derived from the other because task 22 gates on the
    second, and a dash-to-underscore rule that happens to work for one package is
    not a rule.
    *Done when:* `grep -rn "claude.agent.sdk" lmi/commands/install/` matches only
    that module.

17. **Install into `sys.executable`, never a pip found on `PATH`.** `lmi`
    installed by the bootstrap scripts lives in `~/.local/share/lmi/venv`, and
    `lmi schedule` will run from that interpreter — so that is the interpreter
    the SDK has to be importable from. `upgrade/pip.py` already establishes the
    rule (*"pip is never found through PATH — it is `<interpreter> -m pip`"*)
    and `fake_pip` already tests at that seam. A `pip` from `PATH` installs into
    a different interpreter, exits 0, and leaves `sdk.py` unable to import a
    package that is definitely installed *somewhere*.
    *Done when:* a test asserts the argv begins with `sys.executable` and
    `-m pip`, and `fake_pip` intercepts it.

18. **Point pip at `claude.index`, and honour `claude.cafile` the way npm
    does.** `--index-url <claude.index>`, plus `--cert <cafile>` when one is
    set. With no `cafile`, mirror `_configure_npm`'s shape — disable
    verification for this command's own invocation only and print the same class
    of `[WARN]` — rather than silently either failing or trusting. Do not write
    a global `pip.conf`: npm's config writes are global because npm has no
    per-invocation registry flag, and pip does. That asymmetry is a feature.
    *Done when:* tests cover both branches, the warning appears in the
    no-`cafile` branch, and no file outside the interpreter's site-packages is
    written.

19. **Never retry against public PyPI, and never shuffle install locations.**
    Two anti-fallbacks, in the shape of `npm.install`'s "Deliberately NO
    fallback" comment, and for the same reason — a fallback that does something
    *else* is worse than a clean failure:
    - no `--index-url https://pypi.org/simple/` retry when Artifactory 404s.
      On an air-gapped machine that is a timeout; on one with egress it installs
      an unvetted package and exits 0, from a different site than every other
      package on the machine.
    - no `--user`, no `--break-system-packages`, no `--target` retry. Each puts
      the package somewhere `sys.executable` may not import from, which is task
      17's failure with a helpful-looking flag attached.
    Write both into the code as comments naming what the bug would be.
    *Done when:* a test with a failing pip asserts exactly one pip invocation.

20. **Ask before installing, in the "ask everything, change nothing" block, and
    say what declining does.** `_run`'s first half asks every question before
    the machine changes, and invariant 3 says `lmi install` is interactive by
    design with no `--yes`. Add one `prompts.confirm` beside `_ask_for_token`
    and `_resolve_git_bash`. Its text must say that declining sets the mode to
    `cli` — because declining *is* a choice about the mode, and leaving the mode
    unset would leave the default pointing at a backend the operator just
    declined to install. This is deliberately unlike item 16, where declining
    the repair question changes nothing at all: there, nothing was asked for;
    here, a decision was made.
    *Done when:* a scripted `answers` queue covers accept and decline, and the
    decline path writes `cli` and installs nothing.

21. **Run pip after `npm.install` and before any Claude config write.** Item
    15's order is load-bearing and this extends it on the same logic: an SDK
    installed onto a machine with no `claude` binary is the same "looks
    provisioned, is not". A failing npm still reaches no pip and no config file.
    *Done when:* a test with `FAKE_NPM_RC` set asserts pip was never invoked.

22. **Decide the mode by importing what the backend imports — never by pip's
    exit code.** After pip returns, run
    `sys.executable -c "import claude_agent_sdk"` in a **subprocess** and gate on
    that. Two reasons this is the check and pip's `rc` is not: pip can exit 0
    having installed into a different interpreter from the one that will run
    `lmi schedule` (task 17), and an in-process import inside the process that
    just ran pip can be misled by an already-populated `sys.path` cache — so a
    check that looks stricter than `rc` while sharing this process is not.
    Import succeeds → mode `sdk`. Anything else → mode `cli`, with a `[WARN]`
    naming the package, the index it was sought from, that Artifactory is not
    lmi's to populate, and `lmi config schedule --mode sdk` as the way back once
    it is.
    *Done when:* three tests — pip fails; pip exits 0 but the import fails; both
    succeed — produce `cli`, `cli`, `sdk`. Mark all three `MANDATORY`: each is a
    silent wrong-provision otherwise.

23. **A failed pip must not fail the install.** This inverts `npm.install`'s
    rule and the inversion has to be deliberate and commented: npm failing means
    there is no Claude Code and the command has failed, whereas pip failing
    means one of two supported backends is unavailable and the other one works.
    So: `[WARN]`, mode `cli`, carry on, exit 0. It must never be silent — a
    degradation nobody is told about is indistinguishable from success.
    *Done when:* a failing-pip install exits 0, writes `cli`, prints the warning,
    and still writes the settings, statusline and onboarding documents.

24. **Write the mode last, after every Claude config write has succeeded.** The
    `schedule.mode` key then only ever appears on a machine that got all the way
    through. A failure earlier leaves `lmi.json` untouched, which means the
    default — `sdk` — on a machine where pip may not have run; that is task 7's
    loud exit 2, not a silent wrong backend, which is the right side to fail on.
    *Done when:* a test failing the settings write asserts `lmi.json` is
    untouched.

25. **Absent `claude.index` skips the SDK install and sets `cli`.** Decision 3.
    Say so out loud: one line naming the key to add. Do not treat it as an error
    — a site that only wants CLI mode should not have to configure a PyPI mirror
    it will never use.
    *Done when:* an `lmi.json` with no `index` installs no SDK, writes `cli`,
    prints that line, and exits 0.

26. **Report the mode in `_report`.** It already lists backups and confirms
    `claude` is on `PATH`; it is where an operator looks to see what happened.
    State the mode and, when it is `cli`, why.
    *Done when:* both paths appear in the report and a test asserts the text.

27. **Update the four bootstrap scripts with a pointer, not a pip install.**
    `scripts/install-{linux.sh,macos.sh,windows.cmd,windows.ps1}` install the
    lmi wheel with `--no-index` and read no `lmi.json`, so they have neither the
    index nor the CA file nor a way to ask. They already close by telling the
    operator that lmi needs the Claude Code CLI; extend that to say
    `lmi install claude` also sets up the SDK backend. **Do not change their
    line endings**: `install-windows.cmd` and `install-windows.ps1` are LF and
    the verified Windows install ran that way (section 4, rule 4).
    *Done when:* all four mention it and `file scripts/*` shows unchanged line
    endings.

28. **Make `lmi upgrade` not silently undo Phase D.** `lmi upgrade` reinstalls
    lmi into the same interpreter. Check whether it can remove or shadow the
    `sdk` extra's packages — a plain `pip install --upgrade lmi` will not, but
    `--force-reinstall` or a fresh venv would. If it can, say so in the upgrade
    path's output; if it cannot, write that down in `CLAUDE.md` so the next
    reader does not have to re-derive it.
    *Done when:* the answer is recorded, with the command that establishes it.

## Phase E — the two backends behind one seam

29. **Define the seam: one function per backend, identical signature, identical
    return.** Both take the composed prompt and the `Config` and return the
    `(rc, quota)` pair `_capture_claude` and `_stream_claude` return today. The
    runner picks one by mode and otherwise cannot tell them apart.
    *Done when:* `grep -n "mode" lmi/commands/schedule/runner.py` matches only
    the selection point and the header line.

30. **Leave the CLI backend's code alone.** `_claude_argv`, `DEFAULT_FLAGS`,
    `VERBOSE_FLAGS`, `_capture_claude`, `_stream_claude`, `_decoded_lines`,
    `_pump` and the `tempfile.mkdtemp` workspace keep working exactly as they
    do. Move them if the seam reads better with them in a module beside
    `sdk.py`, but do not rewrite them, and keep the comments — including why
    `open(..., newline="\n")` is not `Path.write_text` (item 4) and why
    `check=False` is load-bearing (invariant 2).
    *Done when:* `git diff -w` of the moved functions is empty.

31. **Add `lmi/commands/schedule/sdk.py`: the only module that imports the
    SDK.** Same containment rule `stream.py` follows for claude's output schema.
    The import happens inside the function, because `commands/__init__.py`
    imports every command at startup and a broken SDK must not break
    `lmi install claude` or `lmi upgrade` — the two commands whose job is fixing
    a broken machine. `ImportError` becomes decision 2's exit 2, naming
    `lmi install claude`, `pip install "lmi[sdk]"` and
    `lmi config schedule --mode cli`.
    *Done when:* `grep -rn "claude_agent_sdk" lmi/` matches only `sdk.py`, and a
    test hiding it from `sys.modules` shows `lmi install claude --help` exits 0
    while `lmi schedule` exits 2 with that message.

32. **Translate the CLI flag set into `ClaudeAgentOptions`, one for one.**
    `_claude_argv` is the specification and nothing may be lost:
    `--allowed-tools=Edit,Write` → `allowed_tools=["Edit", "Write"]`;
    `--add-dir <state dir>` → `add_dirs=[str(state_path.parent)]`;
    `subprocess.run`'s `cwd=` → `cwd=str(cfg.work_dir)`; `-p` is implicit in
    `query()`. The two backends must grant the same tools and directories, or a
    task that works in one mode mysteriously cannot write the state file in the
    other.
    *Done when:* a test asserts all four values on the options object actually
    handed to the SDK, and a second asserts the tool list matches
    `DEFAULT_FLAGS`.

33. **Set a non-interactive `permission_mode`, and prove it.** Invariant 3 —
    nothing in the unattended runner may ever wait for a keypress — and the
    SDK's default permission mode is not it. `acceptEdits` is the narrowest mode
    that lets the state file be written. `can_use_tool` must never be set here at
    all: a callback that awaits anything is a keypress wait wearing a library's
    clothing.
    *Done when:* a test asserts the non-interactive `permission_mode` and
    `can_use_tool is None`, marked `MANDATORY` — invariant 3 is exactly what
    section 4 rule 5 protects.

34. **Set `setting_sources` so `~/.claude/settings.json` is still read.** New
    silent failure, and the sharpest asymmetry between the backends. The CLI read
    that file by virtue of being the CLI; the SDK loads settings only from the
    sources you name. Omit the user source and SDK mode runs against the wrong
    endpoint with no credentials — while `lmi config switch`, whose entire
    purpose is changing that file, silently stops affecting `lmi schedule`.
    Include it explicitly, with a "do not simplify this back to X" comment.
    *Done when:* a test asserts the user settings source is present, marked
    `MANDATORY`, and `CLAUDE.md` carries the item from task 43.

35. **Feed the prompt as a string in SDK mode.** `query(prompt=...)` takes the
    text directly, so SDK mode needs no `prompt-N.txt` and no `out-N.txt`. The
    temp workspace still exists for CLI mode — do not delete `mkdtemp` or its
    `shutil.rmtree` in the `finally`; make SDK mode simply not use it.
    *Done when:* an SDK-mode run creates no files there and a CLI-mode run still
    creates both.

36. **Wrap each SDK iteration in its own `asyncio.run`.** One event loop per
    iteration, created and torn down inside `sdk.py`, so the runner stays
    synchronous and the interval wait stays a `time.sleep` — invariant 3's other
    half: every wait is a sleep, never an async idle nobody can reason about. Do
    not make `run()`, `_run_locked` or `_one_iteration` async.
    *Done when:* `grep -n "async" lmi/commands/schedule/runner.py` matches
    nothing.

37. **Refuse `-f` in SDK mode, and keep it working in CLI mode.** Arbitrary
    `claude` flags have no SDK equivalent, and mapping them would mean lmi
    learning claude's flag grammar — the thing item 26 exists to refuse. So `-f`
    with `mode = sdk` is exit 2 naming the mode and `lmi config schedule`. Do
    not invent `--model`, `--max-turns` or any replacement; nobody asked. Keep
    the argument registered and keep `Config.user_flags`.
    *Done when:* `-f` exits 2 under SDK mode and behaves exactly as today under
    CLI mode, `_reject_output_format`'s own exit 2 included.

## Phase F — exit codes, the quota tag and the renderer

38. **Map SDK messages to an `rc`, in one place, and document the table.**
    - `subtype == "success"` → `0`
    - any other `subtype`, and **a stream that ends with no `ResultMessage` at
      all** → non-zero, distinct from `ITERATION_ERROR_RC` (90), so a failed call
      stays distinguishable from a skipped iteration in the log
    - an exception out of the SDK → let it reach `_iteration_rc`, which records a
      skip and carries on. Invariant 2's exception half; do not catch it in
      `sdk.py`.
    The missing-`ResultMessage` row is not a detail: mapping it to 0 is item 1's
    failure with a new front end — exit 0, iteration counted as a success,
    nothing done.
    *Done when:* a test covers all four rows including the missing-result row.

39. **Scan for quota wording before rendering, in both modes.** Item 28,
    restated for a shape where "the raw line" no longer exists. In SDK mode the
    scan runs over the `ResultMessage`'s `result` text, over assistant text
    blocks, and over whatever the `stderr` callback delivers — all of it
    *before* the renderer touches any of it. `[QUOTA]` is the one tag that tells
    an unattended run its result is not to be trusted; no renderer change may be
    able to disable it. `QUOTA_RE` is shared by both backends and does not
    change.
    *Done when:* a fake SDK putting usage-limit wording only in the
    `ResultMessage` still produces the two `[QUOTA]` lines, and that test passes
    with the renderer stubbed out entirely. CLI-mode quota tests untouched.

40. **Route the SDK's `stderr` callback into the log.** `ClaudeAgentOptions`
    takes `stderr=Callable[[str], None]`. Send it to `Logger` so the underlying
    binary's diagnostics reach an unattended run's only record, as
    `stderr=subprocess.STDOUT` does in CLI mode — and through the quota scan
    (task 39). Do not touch `lmi/core/log.py`: item 7, the logger never raises,
    is core behaviour.
    *Done when:* a fake writing to stderr shows those lines in the log file and
    `git diff --stat lmi/core/log.py` is empty.

41. **Give `stream.py` a second front end, not a second renderer.** Keep the
    JSON-line `Renderer` as it is for CLI mode. Add message-object rendering for
    `AssistantMessage` / `UserMessage` / `ToolResultMessage` / `ResultMessage`
    and the blocks `TextBlock` / `ThinkingBlock` / `ToolUseBlock`, reusing
    `_row`, `_clip`, `ARG_WIDTH` and `ARG_KEYS` so the two modes produce
    byte-identical rows for equivalent events — otherwise the logs from the two
    backends are not comparable and neither is a review of them. Both founding
    rules carry over: an unrecognised shape degrades to one dull line and never
    raises (an exception here reaches `_iteration_rc` and abandons the
    iteration), and a shape the module cannot read at all warns once and then
    passes through — the SDK analogue of `_give_up`, replaced rather than
    dropped, because "degrade out loud" is half of why item 26 exists.
    *Done when:* a table-driven test feeds the same logical event to both front
    ends and asserts identical rows; a fake emitting an unknown message type
    produces exactly one `[WARN]`, one line per message, and exit 0.

42. **Keep `ARG_KEYS` an allowlist and keep `content` out of it.** Item 29. A
    `ToolUseBlock.input` for a `Write` carries the whole new file; rendering it
    puts the state file into the log on every save. The typed block makes that
    field easier to reach, which makes the rule easier to break.
    *Done when:* a test renders a large `Write` through both front ends and
    asserts the body appears in neither.

## Phase G — documentation

43. **Append the new silent failures to `CLAUDE.md` section 3.** Append, never
    renumber — `tests/test_docs.py` pins item 22 by name and the list is
    explicitly append-only. At minimum:
    - the `schedule` header not naming the backend (task 9);
    - `lmi install` deciding the mode from pip's exit code rather than a
      subprocess import (task 22), including the wrong-interpreter case
      (task 17);
    - a failing pip that is silent rather than a `[WARN]` (task 23);
    - the mode written before the Claude config writes succeed (task 24);
    - a mode write landing in a shadowed config file (task 12);
    - `setting_sources` omitting the user source (task 34);
    - a message stream with no `ResultMessage` mapped to 0 (task 38);
    - `permission_mode` left at its default (task 33) — the SDK blocks on a
      decision nobody is there to make, so the run hangs instead of failing.
    Also update invariant 4 (task 3), and section 2's architecture map for
    `backend.py`, `sdk.py`, `install/sdk.py`, `core/pip.py` and the `config`
    sub-registry. Section 2 still quotes the `subprocess.run` call; that call
    survives, so mark it as the CLI backend's rather than the only path.
    *Done when:* `python3 -m pytest tests/test_docs.py -q` is green and the
    section 2 map lists every new module.

44. **Update `README.md`.** It is the user-facing documentation and is currently
    accurate; keep it that way. Document `lmi config schedule`, the default, the
    `claude.index` key, what `lmi install claude` now does and when it sets
    `cli`, that CLI mode needs no pip install and stays on the 3.9 floor, that
    `-f` is CLI-only, and — the one thing a reader will otherwise assume — that
    SDK mode still runs a Claude Code binary (fact 2).
    *Done when:* `test_docs.py`'s README assertions pass, the three silent keys
    it checks are still spelled correctly, and its `lmi config switch`
    assertion has not been broken by the sub-registry.

45. **Extend `tests/test_docs.py` for the new surface.** It already pins
    `examples/lmi.json` against `config.build_config` and the `EXAMPLE`/example
    key sets against each other. Add a `schedule` section to the example and
    assert both `build_config` and `backend`'s parser accept it, so the file a
    new site copies documents the switch on day one.
    *Done when:* the example carries `schedule` and `claude.index`, and the test
    asserts all of it.

## Phase H — tests

46. **Make every existing `schedule` test declare its mode, and fail the ones
    that do not.** The phase's real risk: the default is now SDK, so ~500 tests
    written against the CLI path would silently change backend under themselves
    — passing or failing for reasons unrelated to what they assert, and leaving
    one backend untested while the suite looks complete. Add a fixture that sets
    the mode explicitly and a guard that errors on any schedule test which did
    not.
    *Done when:* removing the mode from one test makes it error with a message
    saying so, not pass.

47. **Keep `fake_claude` exactly as it is, for CLI mode.** It replaces `PATH`
    *entirely* rather than prepending, precisely so a real `claude` cannot win
    and quietly spend quota (section 4, rule 3). Every knob keeps its meaning:
    `FAKE_RC`, `FAKE_OUT`, `FAKE_STATE_FILE`, `FAKE_COMPLETE_AT`, `FAKE_PROSE`,
    `FAKE_BLANK_FIRST_LINE`, `FAKE_WRECK_TMP`.
    *Done when:* `fake_claude` is untouched and the CLI-mode suite is green.

48. **Build a separate SDK fake, and treat its containment as a safety
    requirement.** `PATH` replacement protects nothing once the call is a Python
    import: an SDK-mode test that forgets the fake will spawn the bundled binary
    and spend real money. The SDK's documented injection point is
    `query(transport=...)`; a fake module in `sys.modules` is the fallback if
    that shape does not fit. Build the guarantee before the first SDK-mode test.
    *Done when:* a deliberately un-faked SDK-mode test fails loudly instead of
    making a network call, and the conftest documents which mechanism guarantees
    that.

49. **Mirror the `FAKE_*` knobs onto the SDK fake.** Each pins a specific
    failure; a knob that works in one mode only is a regression test covering
    half of what it claims. `FAKE_PROSE` and `FAKE_BLANK_FIRST_LINE` must still
    turn red in **both** modes if the completion check is widened, and
    `FAKE_WRECK_TMP`'s guarantee — item 12, an exception mid-iteration must not
    abort the loop — needs an SDK equivalent, since SDK mode has no temp
    workspace to wreck. A transport that raises part-way through the message
    stream is the natural one.
    *Done when:* the item-12 test passes in both modes and still fails in both
    if the `except Exception` clause in `_iteration_rc` is removed.

50. **Extend `fake_pip` for the install path rather than writing a second
    one.** It already records every `-m pip` argv and fakes an installed
    command, and it exists precisely because the seam is the interpreter (task
    17). Add what Phase D needs — `FAKE_PIP_RC` per package, and a knob for
    "pip exits 0 but the import fails" — so `install` and `upgrade` share one
    pip seam and cannot drift apart about what pip looks like.
    *Done when:* `tests/commands/upgrade/` passes unchanged and the four task-22
    cases drive off the same fixture.

51. **Validate the SDK fake's shapes against the real dataclasses.** A fake
    emitting a shape the real SDK never produces is worse than no fake. Assert
    the fake's messages against the imported SDK types field by field, so a
    version bump that renames something fails the suite instead of passing it.
    Skip cleanly when the extra is absent, in the style of `skip_as_root` in
    `tests/conftest.py` — a `skipif` argument evaluated at import time would lose
    the module during collection.
    *Done when:* the test validates against the real types when `lmi[sdk]` is
    installed and skips, not errors, when it is not.

52. **Get the suite green and say the number.** `python3 -m pytest tests/ -q`.
    The count will have moved a long way. Report the new number rather than the
    old 505, and update section 4 rule 1 and section 5 of `CLAUDE.md`, including
    the `<3s` claim if the runtime moved.
    *Done when:* zero failures and both counts in `CLAUDE.md` match reality.

## Phase I — what only a real run can settle

53. **One real `lmi install claude` per outcome, against a throwaway `HOME`, and
    record which distribution form Artifactory served.** Run it against the real
    index, and against one that does not carry the package. Nothing in Phase D is
    really tested until a real pip has resolved a real index, because the whole
    phase is about distinguishing pip's success from a working backend.

    Then settle fact 2's open question, because the answer decides whether SDK
    mode depends on `claude` being on `PATH`: check whether the installed
    distribution is a platform wheel with a bundled Claude Code binary or the
    sdist without one. `pip download --no-deps claude-agent-sdk` against the
    index shows which files the mirror actually offers, and the installed
    package's own directory shows what arrived. If it is the sdist, say so in the
    README and in `docs/install/` — an SDK-mode scheduled run then needs the
    npm-installed `claude` on `PATH` in the shell the scheduler uses, which is a
    different and easier thing to get wrong than a `PATH` in an interactive
    terminal.
    *Done when:* both runs are quoted in the state file, one ending in mode
    `sdk` and one in mode `cli` with the `[WARN]`, both exiting 0; and the
    wheel-or-sdist answer is written down with the command that established it.

54. **One real single-iteration `schedule` run per mode.** `lmi schedule "add a
    one-line comment to a scratch file" -i 0 -c 1 -v` against a throwaway
    directory, once in each mode. Regressions 1 and 2 were both found by real
    runs, not by tests, and no fake can tell you whether the settings file was
    actually read, whether the state file was actually written, or whether quota
    wording lands where task 39 expects it.
    *Done when:* both logs are quoted in the state file, each showing the header
    with its backend named, one rendered activity block, and `exit code 0`.

55. **Diff the two logs.** Task 41 claims the two front ends produce identical
    rows for equivalent events; two real logs are the only place that claim is
    actually tested. List every difference beyond the header, the timings and
    the flag list, with a judgement on whether each is acceptable.
    *Done when:* the list is in the state file.

56. **One real multi-iteration run in the default mode.** `-i 0 -c 3` with a
    task that finishes in two iterations, checking that `TASK_STATUS: COMPLETE`
    on line 1 stops the loop early and the summary counts agree — the exact pair
    item 2 exists to protect.
    *Done when:* the run reports 2 runs, 2 succeeded, 0 failed, exit 0, and the
    state file's line 1 says `COMPLETE`.

57. **List what is still unverified.** Windows, the real Artifactory PyPI
    mirror, the sdist-versus-wheel split from fact 2, `lmi config schedule`
    against a read-only config file, and task 28's `lmi upgrade` interaction
    cannot all be settled from this machine. Add them to the README's
    outstanding-measurements section beside the five `lmi install claude` checks
    already there, rather than leaving them implied.
    *Done when:* the README names them.

---

## Non-goals

Do not do these. They are adjacent, they are tempting, and nobody asked.

- **No `--mode` flag on `lmi schedule`.** The switch is configuration. A flag
  would also need a precedence rule against the config file, and a precedence
  rule nobody asked for is one more way for a run to use a backend the operator
  did not intend.
- **No auto-detection or fallback between backends at run time.** The fallback
  is the installer's, once, recorded in a file a human can read. A runner that
  quietly switches backend is worse than one that stops.
- **No configurable package names** (fact 5), **no `lmi install sdk` target**,
  and **no pip install in the bootstrap scripts** — they have no config file, no
  CA file, and no way to ask.
- Do not expose `max_turns`, `model`, `effort`, `thinking`, `mcp_servers`,
  `hooks`, `output_format` or subagents as flags or config keys. The SDK offers
  them; that is not a reason to surface them.
- Do not replace the state-file protocol with the SDK's session resume or
  `continue_conversation`. It is a plausible redesign and a different request —
  the state file is what makes a run inspectable and restartable by a human, and
  `check_complete` is load-bearing.
- Do not change `lmi config switch`'s behaviour while restructuring `config` in
  tasks 10 and 11, and do not touch `lmi upgrade` beyond tasks 14 and 28.
- Do not change line endings as a side effect. `runner-test-task.md` is CRLF;
  `scripts/install-windows.cmd` and `install-windows.ps1` are LF (section 4,
  rule 4).
- Do not adjust a test whose docstring says `MANDATORY` to match new behaviour.
  If one goes red, a silent failure is back.
