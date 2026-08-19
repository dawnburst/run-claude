# Status — what has actually been run

Every claim in the other documents is either something the test suite covers or
something a person executed on a real machine. This file is the second kind, and
the honest list of what is **not** covered by either.

The distinction matters more here than in most projects: the failures this
codebase is built around are silent — a run that reports exit 0 having done
nothing. A document that read as though a measurement had been taken would be
the most expensive kind of stale.

[← README](../README.md) · [`lmi schedule`](schedule.md) ·
[`lmi install claude`](install-claude.md) · [`lmi config`](config.md) ·
[`lmi upgrade`](upgrade.md)

---

## Platform status

Development happens on Linux. What has actually been executed elsewhere:

- **Windows: verified.** Install and uninstall through both
  `install-windows.cmd` and `install-windows.ps1` against a Microsoft Store
  Python 3.13; a real `lmi.exe` produced by pip; a bare `lmi` resolving in a new
  window; exit codes 0 and 2 coming back through the `.exe`; and a full
  `lmi schedule` run on local NTFS writing its log, state file and lock. The
  **Windows file-locking branch** (`msvcrt.locking`) has therefore now run — and
  running it is what exposed the UNC limitation in
  [Known limitations](schedule.md#known-limitations).
- **macOS: the install script only.** `scripts/install-macos.sh` has run end to
  end on macOS 15 with the Command Line Tools Python 3.9.6 — Python search,
  wheel build, venv, install, symlink, and `lmi --version` returning `lmi 0.1.0`.
  That run is what found the empty-`UNKNOWN-0.0.0`-wheel bug the macOS guide
  [describes](install/macos.md).
  **`lmi` itself has still not run on a Mac** — no `lmi schedule` iteration, no
  `lmi install claude`, and `--uninstall` untried.

Do not describe macOS support as proven beyond that: installing works, running
is unverified rather than assumed working.

**The interpreter floor is verified.** The full suite and an end-to-end CLI run
both pass on **CPython 3.9.23** — single run, a loop that stops early on
`TASK_STATUS: COMPLETE`, a failing `claude` call leaving the runner alive at exit
1, quota detection, argument validation, and two concurrent runs where the second
is refused with exit 3. This matters because one real bug was found exactly here:
`Path.write_text(..., newline=...)` needs Python 3.10, so before it was fixed
every run died at the first iteration on 3.9. A syntax-level check cannot catch a
parameter added in a later version — only running the older interpreter can.

So: the **3.9 floor** is tested. **Linux** and **Windows** are tested. On
**macOS**, installing is tested and running is not.

## Still to verify

Ten measurements have not been taken. All are named so nobody mistakes
reasoning for evidence. `lmi install claude` has its own five, in
[the checks below](#lmi-install-claude-five-checks-per-site).

Items 4 to 8 are the two-backend work. The suite now runs green against it and
one real SDK-mode run has happened — the credential-free smoke test in
[`lmi schedule`](schedule.md#smoke-testing-sdk-mode-without-any-credential),
which is what found three silent bugs a green suite did not. What is still
missing is a **successful** SDK call: everything below the smoke test remains
reasoning rather than evidence.

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
3. **Whether pip can displace a running `lmi.exe` on Windows.** `lmi upgrade`
   replaces the package in place, and on Windows the console script being
   replaced is the one executing the command. pip stashes files by renaming
   rather than overwriting, and Windows permits renaming a running image on the
   same volume, so this is expected to work — but only a real Windows run
   settles it. If it fails, the exit-1 message already carries the
   `python -m pip …` line to run from a shell where no `lmi` is live.
4. **One real `lmi install claude` per outcome**, against a throwaway `HOME`:
   one against an index that carries `claude-agent-sdk`, ending in mode `sdk`,
   and one against an index that does not, ending in mode `cli` with the
   `[WARN]` — both exiting 0.
5. **Which distribution form the site's Artifactory actually serves.** A
   platform wheel bundles a Claude Code binary; the source distribution does
   not, and an SDK-mode run then needs `claude` on `PATH` **in the shell the
   scheduler uses** — a different and easier thing to get wrong than a `PATH`
   in an interactive terminal. `pip download --no-deps claude-agent-sdk`
   against the index shows what the mirror offers. The `sdk` extra's floor is
   `>=0.2.136`, the version that real run used; a mirror carrying only an older
   one fails the pip install, which is a `[WARN]` and the `cli` backend rather
   than a broken machine.
6. **One real single-iteration `lmi schedule` run per mode, with a working
   credential**, and a diff of the two logs. The credential-free smoke test
   exercises everything around the call; it cannot show that the two backends
   render identical rows for equivalent events, which only two real logs ever
   test. Regressions here have twice been found by real runs and not by tests.
7. **`lmi config schedule` against a read-only config file.**
8. **Whether `lmi upgrade` disturbs the SDK.** Reasoning says no —
   `upgrade`'s pip call always passes `--no-deps` and never `--force-reinstall`,
   and the SDK is an extra rather than a dependency — but that is reasoning.
   `python3 -m pip show claude-agent-sdk` either side of an `lmi upgrade`
   settles it.
9. **That a resumed iteration really does carry the earlier context.** The suite
   proves `--session-id` is minted once and `--resume <that id>` passed
   afterwards, in both backends, and that claude's own "No conversation found"
   line is answered with one fresh retry — all of it against fakes. What no fake
   can show is the thing the feature is for: that iteration 2 *knows* what
   iteration 1 did without being told by the state file. The cheap version is
   two iterations with `-i 0 -c 2` and a task whose second step is only possible
   with the first still in context — "pick a number and remember it", then "what
   number did you pick?" — read out of the `-v` log. The expensive version is
   `runner-test-task.md` with `-i 1 -c 5`, which item 1 above already wants.
10. **The id-mismatch warning, in the mode that can see it.** SDK mode compares
    the session id that answers against the one it asked to resume and warns on
    a mismatch. CLI mode **cannot**: its plain output carries no session id at
    all, and forcing `--output-format stream-json` onto a non-verbose run is the
    failure item 26 exists for. So a session silently substituted for the one
    requested is observable in one backend and not the other — a declared gap
    rather than a hidden one, and the only way to close it in CLI mode would be
    reading claude's session store directly, which means lmi depending on an
    undocumented on-disk layout. Whether the warning ever fires in practice is
    unmeasured.

---

---

## Checks only a real run can make

### `lmi install claude`: five checks per site

The suite drives a **fake npm** on an exclusive PATH, which proves the argv, the
order and the exit codes and proves nothing whatever about the real one. Five
things need a real machine, and are worth doing once per site:

1. **Artifactory really serves `@anthropic-ai/claude-code`** and its whole
   dependency tree — a virtual repository that proxies the public registry has to
   have been populated, and this command does not populate it.
2. **`--global` behaves as documented on the site's Node layout**, or the
   `~/.npmrc` fallback fires and the install still lands.
3. **`extraKnownMarketplaces` in user scope really registers the marketplace.**
   Check with `/plugin marketplace list` inside `claude`; a wrong key writes
   cleanly and does nothing.
4. **A Windows box with Git in a non-default location ends up with a working Bash
   tool** — the case Claude Code's own two-path detection cannot see, and the
   whole reason the registry search exists.
5. **The installed `statusLine` command actually runs.** `lmi` copies the script
   and installs the block; whether `node` is on the PATH Claude Code launches
   the command with, and whether that command's `~` expands there, is the
   machine's business and not something a fake can answer. Start `claude` and
   look at the bottom of the screen.

---

### `lmi config switch`: does Claude Code honour it

The suite drives the merge, the snapshot and the exit codes against a throwaway
`HOME`, which proves what `lmi` writes and proves nothing about whether Claude
Code **honours** it. Every key but `env` passes through unexamined, so a
perfectly valid fragment can mean nothing at all. Worth doing once:

1. Switch a fragment that changes `model` — `{"model": "opus"}` is enough.
2. Run `claude` and confirm the model it reports is the one the fragment named.
3. `lmi config switch origin`, and confirm it changed back.
