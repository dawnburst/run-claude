# lmi — design (scoped to `lmi install claude`)

**Date:** 2026-08-05
**Status:** designed, not implemented.

`lmi install claude` installs the Claude Code CLI on an air-gapped machine by
pointing npm at an internal Artifactory registry and running
`npm install -g @anthropic-ai/claude-code`. It then seeds the plugin
marketplaces the site wants every user to have.

This is the second command in the skeleton the
`2026-08-03-lmi-schedule-design.md` spec laid down, and it is the `lmi install`
that spec named as out of scope and left room for. Nothing in `cli.py` changes.

---

## 1. Goal and non-goals

**Goal.** One command, `lmi install claude`, that a user runs on a fresh
air-gapped machine and gets a working `claude`. Every value that differs between
sites lives in a JSON config file; nothing site-specific is compiled in.

**Non-goals.**

- **No mirror-side tooling.** Populating Artifactory is Artifactory's job: a
  remote/virtual npm repository proxies and caches `@anthropic-ai/claude-code`
  and its dependency tree. lmi consumes that; it does not build it. There is
  deliberately no `lmi mirror` command and no release-layout for lmi to define.
- **No installing npm or Node.js.** If `npm` is not on PATH the command stops
  and says so. pylmi's `requires_npm` decorator tried to install npm from a
  hardcoded `C:/Program Files/nodejs/npm` path on all three operating systems;
  on Linux it ran `bash "C:/Program Files/nodejs/npm" --silent`. Bootstrapping a
  Node runtime is a different problem with a different owner.
- **No `--version` and no `--dry-run`.** The registry decides what version
  `@anthropic-ai/claude-code` resolves to; a version pin belongs in Artifactory,
  not in a flag. Both were in an earlier draft and were cut.
- **No second install target.** `lmi install claude` takes `claude` and nothing
  else. No agent-adapter layer: that pays off at the second agent, and there is
  no second agent.
- **No `sudo` escalation, ever.** See section 6.
- **No new runtime dependencies.** `dependencies = []` stays, and
  `tests/test_packaging.py` enforces it.

**Why npm rather than the binary installer.** An earlier draft of this design
mirrored Anthropic's GCS release bucket byte for byte, detected the platform
(`linux-x64-musl`, `darwin-arm64`, ...), fetched `manifest.json`, verified a
SHA-256 and ran the binary's own `claude install`. All of that is dead weight
when the artifact arrives through npm: Artifactory already does the mirroring,
npm already does the integrity check, and the npm package already resolves the
platform. Three of the six planned modules disappeared with it. It is recorded
here only so the question is not reopened.

---

## 2. Platforms and prerequisites

- **Linux, macOS, Windows.** No per-OS branch in this command: `npm` is `npm`
  everywhere, and `shutil.which` finds `npm.cmd` on Windows.
- **Python 3.9**, stdlib only. `json`, `os`, `shutil`, `subprocess`, `pathlib`,
  `typing`. No PEP 604 unions (`str | None`) in evaluated annotations - use
  `typing.Optional`. pylmi has that bug in six places while declaring
  `requires-python = ">=3.8"`, and it is an import-time `TypeError`, not a
  runtime one.
- **npm on PATH**, from a Node.js the site provides. Claude Code needs Node 18
  or newer; lmi does not check the Node version, because npm's own engine check
  reports it better than a duplicated floor would.

---

## 3. Package structure

```
lmi/commands/install/
  __init__.py      NAME, HELP, add_arguments, run - the command contract
  config.py        --config discovery, JSON validation, the frozen Config
  exit_codes.py    this command's codes: 1, 3, 4
  npm.py           locating npm and running one npm command
  settings.py      merging marketplaces into ~/.claude/settings.json
```

Registration is one line in `lmi/commands/__init__.py`:

```python
from . import install, schedule

COMMANDS = [install, schedule]
```

`install` is listed first so `lmi --help` reads in the order a user meets the
commands: install the tool, then schedule it. Registry order is display order,
which is the reason the registry is an explicit list and not `pkgutil`
discovery.

**Why two modules and not one.** `npm.py` is subprocess work and `settings.py`
is JSON-file work; they share no state and fail in different ways (an npm
command exits non-zero, a settings write raises `OSError`). Keeping them apart
is what lets the settings merge - the part that can corrupt a file a user cares
about - be tested without a subprocess anywhere near it.

**Nothing is added to `lmi/core/`.** Every piece here has command flavour:
`npm.py` knows npm's flags, `settings.py` knows Claude Code's settings schema.
Per the architecture rule in `CLAUDE.md`, promote later if a second command
needs them, not in advance.

---

## 4. Configuration file

### 4.1 Discovery

First match wins:

1. `--config PATH`
2. `$LMI_CONFIG`
3. `./lmi.json`
4. `~/.lmi/config.json`

**A `--config` that does not exist is exit 2**, never a silent fall-through to
the next candidate. An explicit request that quietly resolves to a different
file is how a machine gets provisioned against the wrong registry and nobody
finds out.

`~` in `--config` and `$LMI_CONFIG` is expanded through the same guarded
`expanduser` as `lmi schedule` uses: `Path.expanduser()` raises `RuntimeError`
for a `~someuser` whose home it cannot resolve, and an unguarded call turns a
typo into a traceback. Classification goes through `core.fs.classify`, so an
over-long or unreadable path is exit 2 rather than an `ENAMETOOLONG` traceback.

### 4.2 Shape

```json
{
  "claude": {
    "registry": "https://artifactory.corp.local/api/npm/npm-virtual/",
    "cafile": "/etc/ssl/certs/corp-ca.pem",
    "marketplaces": {
      "corp-tools": {
        "source": {
          "source": "git",
          "url": "https://git.corp.local/claude/marketplace.git"
        }
      }
    }
  }
}
```

| Key | Required | Meaning |
|---|---|---|
| `registry` | yes | npm registry URL for the internal Artifactory |
| `cafile` | no | PEM bundle for the internal CA. Present: TLS verification stays on. Absent: `strict-ssl false`. See 6.2 |
| `marketplaces` | no | merged verbatim into `extraKnownMarketplaces`. See section 5 |

Everything is under a `"claude"` object so a future `lmi install <other>` gets
its own section without a migration.

**Only site-specific values are configurable.** Timeouts, download directories
and package names are not decisions an environment makes, and an earlier draft
of this design had twelve keys where three will do. The npm package name
`@anthropic-ai/claude-code` is a constant in `npm.py`, not a config key: it
identifies *what this command installs*, and a command whose target is
configurable is a different command.

### 4.3 Validation

All of these are exit 2, each naming the file it read:

- the file is absent (no candidate matched, or `--config` pointed at nothing)
- it is not valid JSON - the `json.JSONDecodeError` message is included, since
  line and column are the whole diagnosis
- the top level is not an object, or `"claude"` is missing or not an object
- `registry` is missing, empty, or not a string
- `cafile` is set but no file exists at that path. Checked before any npm
  command runs: `npm config set cafile /typo` succeeds, and the failure surfaces
  later as an unrelated TLS error from step 4
- `marketplaces` is set and is not an object

The no-config message prints a paste-ready example and the four paths that were
searched, in order.

---

## 5. Marketplaces

`marketplaces` is merged into the `extraKnownMarketplaces` key of
`~/.claude/settings.json`.

**The key and its scope were verified against the shipped binary**, not assumed.
In Claude Code 2.1.222:

- the settings schema declares
  `extraKnownMarketplaces: record(string, MarketplaceSource)` - a map of
  marketplace **name** to an object with a `source` field;
- the writer Claude Code itself uses defaults to user scope
  (`$in(name, entry, scope = "userSettings")`), and the reader merges the key
  across user and project settings. So `~/.claude/settings.json` is honoured.
  Managed settings matter only for the enterprise allowlist gate
  (`strictKnownMarketplaces`, `blockedMarketplaces`), which is not in play here;
- `source.source` may be `github`, `git`, `npm`, `file`, `directory` or
  `settings`. Of those, `git` (internal GitLab or similar), `directory` (a
  mounted share) and `npm` (Artifactory again) all work with no internet.

**lmi does not model marketplace source types.** The `marketplaces` object is
passed through unaltered. lmi validates only that it is a JSON object; whether
a given entry is a well-formed source is Claude Code's schema's business, and it
reports violations better than a duplicated validator would. This is also what
keeps lmi working when a source type is added upstream.

**Merge semantics.** Read the existing settings file, `dict.update` the new
marketplaces into `extraKnownMarketplaces`, write the whole document back:

- every unrelated key - `model`, `enabledPlugins`, `theme` - is preserved;
- marketplaces already present under other names are preserved;
- a name that is already present is **overwritten**, so re-running the command
  after editing the config converges on the config rather than accumulating
  stale entries;
- a missing or empty settings file is created, with `~/.claude/` created if
  needed;
- indent is 2 spaces, matching what Claude Code writes.

**The write is atomic**: a temp file in the same directory, then `os.replace`.
A half-written `settings.json` is invalid JSON, and Claude Code cannot start
without it - the one failure in this command that could damage something the
user already had. `os.replace` is atomic on POSIX and on Windows.

**An unparseable existing settings file is exit 3, and nothing is written.**
Overwriting a file that a user hand-edited into invalid JSON would silently
discard their settings; refusing and naming the file lets them fix it.

`marketplaces` absent or `{}` skips step 5 entirely, including the read.

---

## 6. Behaviour

`lmi install claude [--config PATH]`

The target is a positional argument with `choices=["claude"]`, so argparse
rejects `lmi install codex` with its own message and exit 2, and `lmi install`
with no target lists what is available. A positional rather than a hardcoded
name because `lmi install` alone would have to mean something, and "install
whatever this config mentions" is a worse command than one that says what it
installs.

Six steps, in order, stopping at the first failure:

1. **Locate npm.** `shutil.which("npm")`. Absent is exit 2: "npm was not found
   on PATH - install Node.js 18 or newer first".
2. **Configure TLS.** `npm config set cafile <cafile> --global` when `cafile` is
   configured, otherwise `npm config set strict-ssl false --global`.
3. **Configure the registry.** `npm config set registry <registry> --global`.
4. **Install.** `npm install -g @anthropic-ai/claude-code`.
5. **Seed marketplaces**, if any are configured (section 5).
6. **Confirm.** `shutil.which("claude")`.

Every npm command is a list argv through `subprocess.run`, never
`shell=True` - a registry URL from a config file must never reach a shell. Output
is inherited, not captured, so npm's own progress and errors reach the user
as they happen. `check=False`; the return code is inspected.

Each step prints what it is about to do before doing it, so a failure in an
unattended provisioning log is attributable to a step without re-running.

### 6.1 Privileges: the `--global` fallback

`npm config set --global` writes the npmrc under `npm prefix -g`, and
`npm install -g` writes the global `node_modules`. On a system-wide Node install
both are root-owned, so an unelevated run fails with `EACCES`.

**Steps 2 and 3 retry without `--global`.** Dropping the flag writes `~/.npmrc`
instead, which needs no root and still governs every `npm install -g` that user
runs. That is a correct fallback, not a degraded one. Both attempts are printed,
so the log shows which one took effect.

**Step 4 has no fallback.** Dropping `-g` from `npm install -g` does not degrade,
it does something else entirely: it installs the package into `./node_modules`
of whatever directory the user happened to be in and creates no `claude`
command at all - a silent wrong-install, which for a provisioning tool is worse
than a clean failure. So a failing step 4 goes straight to exit 1 with a message
naming the two ways forward:

- re-run with `sudo` (or in an Administrator shell on Windows);
- or give npm a writable prefix - `npm config set prefix ~/.npm-global` - and
  put `~/.npm-global/bin` on PATH.

**lmi never invokes `sudo` itself.** A provisioning tool that silently escalates
privileges is a tool nobody can audit, and it would prompt for a password
mid-run in something built to run unattended. Explicitly rejected.

### 6.2 TLS

Artifactory usually serves HTTPS with a certificate signed by an internal CA
that Node does not ship, which is the only reason `strict-ssl false` is reached
for at all.

- **`cafile` configured:** `npm config set cafile <path>`, and `strict-ssl` is
  left alone. Verification stays on.
- **`cafile` absent:** `npm config set strict-ssl false`, and lmi prints a
  `[WARN]` saying certificate verification is off for **every** npm install by
  this user from now on, and that setting `cafile` is the fix.

The risk `strict-ssl false` leaves open is not external interception - it is
that anyone on the internal network who can answer as the registry host gets a
package whose `postinstall` script runs, with whatever privileges step 4 has.
`cafile` closes that; `strict-ssl false` does not. Hence the warning on every
run rather than a one-time note.

### 6.3 Confirming, without overclaiming

Step 6 is `shutil.which("claude")`.

- Found: print the resolved path and exit 0.
- Not found: exit **0** with a `[WARN]`. npm reported success, so the install
  did happen; what is missing is PATH in *this* process, which cannot see an
  npmrc prefix change or a shell profile edit made moments ago. The warning says
  to open a new terminal, and names the directory that has to be on PATH as the
  `bin` subdirectory of `npm prefix -g`. Deliberately not `npm bin -g`, which
  said exactly that and was removed in npm 9 - an error message that tells the
  user to run a command that no longer exists is worse than no message.

Exiting non-zero here would fail runs that in fact succeeded - the normal
outcome the first time npm's global bin directory is used on a machine.

---

## 7. Exit codes

| Code | Owner | Meaning |
|---|---|---|
| 0 | global | installed. Possibly with the PATH warning of 6.3 |
| 2 | global | usage: bad or missing config, npm not on PATH |
| 1 | install | an npm command failed |
| 3 | install | `~/.claude/settings.json` could not be read or written |
| 4 | install | a bug in lmi |

0 and 2 come from `core/errors.py` and are not redefined. 1, 3 and 4 live in
`lmi/commands/install/exit_codes.py`.

**4 deliberately keeps the meaning it has in `lmi schedule`.** The architecture
lets each command own its codes, and `schedule` uses 4 for "a bug in lmi". A
provisioning script should not have to learn a per-command definition of
internal error, so this command matches instead of exercising its freedom. 1 is
similarly the analogue of `schedule`'s 1: the external thing we shelled out to
failed.

**3 is separate from 1 on purpose.** By the time step 5 runs, Claude Code is
installed - the outcome is a working `claude` with unseeded marketplaces, which
is partial success and wants its own code. Folding it into 1 would say the
install failed.

Every user-caused failure raises `LmiError` with its code, which `cli.main`
already renders as `[ERROR] <message>` on stderr. No new error plumbing.

---

## 8. Testing

`python3 -m pytest tests/ -q`, no install needed, added to `tests/commands/install/`.

**A `fake_npm` fixture**, following `fake_claude` exactly: a recording script on
an **exclusive** PATH - `monkeypatch.setenv("PATH", str(bindir))`, replacing
rather than prepending, so a real npm on the machine cannot win and quietly
reconfigure the developer's own npmrc or install a real package. It records each
invocation's argv in order and honours `FAKE_NPM_RC` and
`FAKE_NPM_FAIL_GLOBAL` (fail only when `--global` is present, which is how the
6.1 fallback is exercised). On Windows it grows an `npm.cmd` shim the way
`fake_claude` grows `claude.bat`.

Coverage:

*Config* - the four-candidate precedence; `--config` at a nonexistent path is 2
and does not fall through; invalid JSON, non-object top level, missing
`"claude"`, missing/empty/non-string `registry`, non-object `marketplaces`, and
a `cafile` pointing at nothing are each 2; `~` expansion, and a `~nosuchuser`
that raises `RuntimeError` is 2 not a traceback.

*npm* - the commands run in order with the configured registry; `cafile` present
sends `cafile` and never `strict-ssl`; `cafile` absent sends `strict-ssl false`
and warns; a non-zero step 4 is exit 1 and **step 5 never runs**; npm missing
from PATH is 2; no argv ever contains a shell metacharacter path, and
`shell=True` appears nowhere in the package.

*The `--global` fallback* - with `FAKE_NPM_FAIL_GLOBAL`, steps 2 and 3 are each
attempted twice and the second attempt omits `--global`; step 4 is attempted
**once** and the run exits 1. That second assertion is the one that matters: a
retry without `-g` would be a silent wrong-install, so a test has to pin its
absence.

*Settings* - unrelated keys survive; existing marketplaces under other names
survive; a same-named entry is overwritten, not duplicated; a missing file and a
missing `~/.claude/` are created; an existing file that is not valid JSON is
exit 3 **and leaves the file untouched**; no `marketplaces` means the file is not
even read; the temp file is gone afterwards on both the success and failure
paths.

*Registration* - `[c.NAME for c in COMMANDS] == ["install", "schedule"]`, and the
existing contract test covers the new module for free.
`tests/test_cli.py::test_schedule_is_registered` asserts the exact list and
**will need updating** - it is the intended tripwire for adding a command.

Three tests carry `MANDATORY` in their docstring, marking failures that are
silent - the run reports success while being wrong:

1. a failing step 4 does not proceed to step 5 (otherwise: marketplaces seeded
   for a `claude` that was never installed, exit 0);
2. step 4 is never retried without `-g` (otherwise: a package in a random
   `./node_modules`, no `claude`, exit 0);
3. an unparseable `settings.json` is not overwritten (otherwise: a user's
   settings silently discarded).

**What tests cannot cover.** A fake npm proves nothing about the real one: that
Artifactory serves the package, that `--global` behaves as documented on a given
Node layout, and that `extraKnownMarketplaces` in user scope actually registers
a marketplace end to end. `README.md` gains a short real-run checklist covering
those three, in the style of the checks already there.

---

## 9. Documentation

- `README.md`: a `lmi install claude` section - the config file, the four search
  paths, the exit codes, the sudo and PATH messages, and the real-run checklist.
- `examples/lmi.json`: a complete config with all three keys and a comment-free
  `git`-source marketplace, so `cp` and edit is the whole setup.
- `CLAUDE.md`: `install` added to the architecture map, and any behaviour in
  section 6 here that becomes a regression guard added to its section 3.

---

## 10. Open questions

None. Four decisions were taken during design and are recorded so they are not
silently reversed:

1. **Delivery is npm via Artifactory**, not a mirrored binary release. Section 1.
2. **`--global`, then retry without it, never `sudo`** - and no retry at all for
   `npm install -g`. Section 6.1.
3. **`cafile` when configured, `strict-ssl false` otherwise**, with a warning
   every run in the second case. Section 6.2.
4. **Config holds only site-specific values** - three keys, one required.
   Section 4.2.
