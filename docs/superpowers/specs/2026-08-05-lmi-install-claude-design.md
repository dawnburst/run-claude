# lmi — design (scoped to `lmi install claude`)

**Date:** 2026-08-05 (revised 2026-08-06)
**Status:** designed, not implemented.

`lmi install claude` installs the Claude Code CLI on an air-gapped machine by
pointing npm at an internal Artifactory registry and running
`npm install -g @anthropic-ai/claude-code`. It is **interactive**: it asks
before repairing an existing install, asks for the auth token, and asks for the
Git Bash path when it cannot find one. It then writes the site's standard
configuration - marketplaces, the 256K context profile, the Windows Git Bash
path - and skips onboarding.

This is the second command in the skeleton the
`2026-08-03-lmi-schedule-design.md` spec laid down, and it is the `lmi install`
that spec named as out of scope and left room for. Nothing in `cli.py` changes.

---

## 1. Goal and non-goals

**Goal.** One command a user runs on a fresh air-gapped machine that leaves them
with a working, configured `claude`. Every value that differs between sites
lives in a JSON config file; nothing site-specific is compiled in.

**Non-goals.**

- **No mirror-side tooling.** Populating Artifactory is Artifactory's job: a
  remote/virtual npm repository proxies and caches `@anthropic-ai/claude-code`
  and its dependency tree. lmi consumes that; it does not build it.
- **No installing npm, Node.js or Git.** If `npm` is not on PATH the command
  stops and says so. pylmi's `requires_npm` decorator tried to install npm from
  a hardcoded `C:/Program Files/nodejs/npm` path on all three operating
  systems; on Linux it ran `bash "C:/Program Files/nodejs/npm" --silent`.
  Bootstrapping a runtime is a different problem with a different owner.
- **No `--version` and no `--dry-run`.** The registry decides what version
  resolves; a version pin belongs in Artifactory, not a flag.
- **No `--yes` / non-interactive mode.** Decided explicitly - see 6.1.
- **No second install target.** No agent-adapter layer.
- **No `sudo` escalation, ever.** See 6.4.
- **No new runtime dependencies.** `dependencies = []` stays, and
  `tests/test_packaging.py` enforces it.

**Why npm rather than the binary installer.** An earlier draft mirrored
Anthropic's GCS release bucket byte for byte, detected the platform, fetched
`manifest.json`, verified a SHA-256 and ran the binary's own `claude install`.
All of that is dead weight when the artifact arrives through npm: Artifactory
already mirrors, npm already checks integrity, the package already resolves the
platform. Recorded so the question is not reopened.

---

## 2. Facts verified against Claude Code 2.1.222

Every key below was read out of the shipped binary rather than assumed. Three of
them fail **silently** if written wrong - the file parses, the write succeeds,
and the setting does nothing.

| Fact | Consequence |
|---|---|
| The onboarding key is `hasCompletedOnboarding` - **lowercase `b`** | `hasCompletedOnBoarding` writes cleanly and is ignored. Onboarding still runs |
| `CLAUDE_CODE_GIT_BASH_PATH` is resolved through `require("path/win32")` | Windows-only. It is never consulted on Linux or macOS |
| Claude Code validates that variable: basename in `bash.exe`/`sh.exe`/`bash`/`sh` **and** the file exists, else it warns and falls back to auto-detection | lmi must apply the same validation or Claude Code silently ignores what we wrote |
| Its own auto-detection checks exactly two paths: `C:\Program Files\Git\bin\bash.exe` and `C:\Program Files (x86)\Git\bin\bash.exe` | A Git installed anywhere else is invisible to it. This is what makes lmi's wider search worth having |
| The context keys are `CLAUDE_CODE_MAX_CONTEXT_TOKENS`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | |
| Their validator caps an over-range value and warns; it does not reject | A wrong number degrades quietly. lmi must not guess values - hence 4.2 |
| `extraKnownMarketplaces` is `record(name, {source})`, written by Claude Code itself at `"userSettings"` scope | `~/.claude/settings.json` is the right file. Managed settings matter only for the enterprise allowlist gate |
| `settings.json` `env` is a map of string to string | `256000` as a JSON number is the wrong type. Values are strings |
| `~/.claude.json` is mode `600` and holds per-project history (63 KB on a normal machine) | Backups must preserve the mode, not land world-readable |

---

## 3. Package structure

```
lmi/commands/install/
  __init__.py      NAME, HELP, add_arguments, run - the command contract
  config.py        --config discovery, JSON validation, the frozen Config
  exit_codes.py    this command's codes: 1, 3, 4
  prompts.py       every question asked, and the no-terminal guard
  npm.py           locating npm, running one npm command, the --global fallback
  gitbash.py       Windows Git Bash discovery and the persisted env var
  jsonfile.py      read / back up / atomically write one JSON document
  settings.py      what goes into ~/.claude/settings.json
  claude_json.py   what goes into ~/.claude.json
```

Registration is one line in `lmi/commands/__init__.py`:

```python
from . import install, schedule

COMMANDS = [install, schedule]
```

`install` first so `lmi --help` reads in the order a user meets the commands.
Registry order is display order, which is why the registry is an explicit list
and not `pkgutil` discovery.

**Why `jsonfile.py` exists.** `settings.json` and `.claude.json` need the same
four operations - read-or-empty, back up, write atomically, preserve mode - and
differ only in *what* they put in the document. Splitting the mechanism from the
content is what lets the dangerous part (clobbering a file the user cares about)
be tested once, thoroughly, without knowing anything about Claude Code's schema.

**Why `prompts.py` exists.** Every `input()` and `getpass()` in the command goes
through it, so the no-terminal guard (6.1) is in one place and the tests have one
seam to drive the whole interactive flow.

**Nothing is added to `lmi/core/`.** Every piece has command flavour. Per the
architecture rule in `CLAUDE.md`, promote later if a second command needs it.

**`CLAUDE.md` invariant 3 must be re-scoped.** It currently reads "Nothing may
ever wait for a keypress", stated as a global invariant. It is a property of the
unattended runner, and this command contradicts it by design. The invariant is
rewritten to name `lmi schedule`, in the same change that adds this command -
not silently violated.

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

`~` expansion goes through the same guarded `expanduser` `lmi schedule` uses:
`Path.expanduser()` raises `RuntimeError` for a `~someuser` whose home it cannot
resolve. Classification goes through `core.fs.classify`, so an over-long or
unreadable path is exit 2 rather than an `ENAMETOOLONG` traceback.

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
    },
    "env": {
      "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000",
      "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "204800",
      "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"
    }
  }
}
```

| Key | Required | Meaning |
|---|---|---|
| `registry` | yes | npm registry URL for the internal Artifactory |
| `cafile` | no | PEM for the internal CA. Present: TLS verification stays on. Absent: `strict-ssl false`. See 6.5 |
| `marketplaces` | no | merged verbatim into `extraKnownMarketplaces`. See section 7 |
| `env` | no | merged into `settings.json` `env`. **Defaults to the three keys above** - the 256K profile - which the file overrides or extends |

**The 256K profile is a default, not a hardcode.** 256000 context; 204800
autocompact window (80%, leaving headroom before compaction starts); 64000 max
output. They ship as defaults so a machine with no `env` in its config still
gets the profile, and any of the three can be changed per site without touching
lmi. Because `env` is a free-form merge, a site that later needs
`ANTHROPIC_BASE_URL` for a gateway adds it here - no code change.

**Values must be strings**, matching Claude Code's schema. `"256000"`, not
`256000`. Validated (4.3), because a JSON number here is precisely the kind of
mistake that writes cleanly and does nothing.

**Only site-specific values are configurable.** The npm package name
`@anthropic-ai/claude-code` is a constant in `npm.py`, not a config key: it
identifies *what this command installs*, and a command whose target is
configurable is a different command.

### 4.3 Validation

All exit 2, each naming the file it read:

- the file is absent (no candidate matched, or `--config` pointed at nothing)
- it is not valid JSON - the `json.JSONDecodeError` message is included, since
  line and column are the whole diagnosis
- the top level is not an object, or `"claude"` is missing or not an object
- `registry` is missing, empty, or not a string
- `cafile` is set but no file exists at that path. Checked before any npm
  command runs: `npm config set cafile /typo` succeeds, and the failure surfaces
  later as an unrelated TLS error from the install step
- `marketplaces` is set and is not an object
- `env` is set and is not an object, or any of its values is not a string

The no-config message prints a paste-ready example and the four paths searched,
in order.

---

## 5. What the command does

`lmi install claude [--config PATH]`

The target is a positional with `choices=["claude"]`, so argparse rejects
`lmi install codex` with its own message and exit 2, and `lmi install` with no
target lists what is available.

Steps, in order, stopping at the first failure. Steps marked **W** run on
Windows only.

| # | Step |
|---|---|
| 1 | Load and validate config (section 4) |
| 2 | Locate npm - `shutil.which("npm")`. Absent is exit 2 |
| 3 | Detect an existing install and ask about repair (6.2) |
| 4 | Ask for `ANTHROPIC_AUTH_TOKEN` (6.3) |
| 5 | **W** Resolve the Git Bash path, asking if not found (section 8) |
| 6 | `npm config set` TLS (6.5) and registry, then `npm install -g @anthropic-ai/claude-code` (6.4) |
| 7 | **W** Persist `CLAUDE_CODE_GIT_BASH_PATH` as a user environment variable (8.2) |
| 8 | Back up and update `~/.claude/settings.json` (section 7) |
| 9 | Back up and update `~/.claude.json` (section 9) |
| 10 | Report backups written, and confirm `claude` is on PATH (6.6) |

**Every question is asked before anything is changed.** Steps 3 to 5 gather
input; step 6 is the first step that modifies the machine. A user who abandons
the command at a prompt leaves nothing half-done.

Every npm command is a list argv through `subprocess.run`, never `shell=True` -
a registry URL from a config file must never reach a shell. Output is inherited,
not captured, so npm's own progress reaches the user as it happens.
`check=False`; the return code is inspected. Each step prints what it is about
to do first, so a failure in a provisioning log is attributable without a re-run.

---

## 6. Behaviour in detail

### 6.1 Interactive, with a guard against hanging

The command is interactive by design and has **no `--yes` flag**. Consequence,
accepted: `lmi install claude` cannot be driven from a script, an Ansible play
or a Docker build.

What it must not do is *hang*. With no terminal, `input()` and
`getpass.getpass()` raise `EOFError`, which `prompts.py` catches once and turns
into exit 2: "lmi install claude is interactive and needs a terminal". A guard
against an unbounded wait, not a mode.

All prompting lives in `prompts.py`:

- `confirm(question, default=False)` - `[y/N]`, anything but `y`/`yes` is no
- `secret(question)` - `getpass`, so the token is never echoed and never lands
  in a screen-scrape or a terminal scrollback
- `text(question, default=None)`

### 6.2 Repair of an existing install

Step 3 is `shutil.which("claude")`.

- **Not found:** fresh install, continue silently.
- **Found:** print the resolved path and ask *"Claude Code is already installed
  at &lt;path&gt;. Repair the installation?"*, default **no**.
  - No: exit 0, having changed nothing. Not an error - the user answered the
    question.
  - Yes: continue. `npm install -g` reinstalls over the top, and the config
    steps rewrite the site's settings, which is what repair means here.

**Backups are not tied to repair.** Any file lmi is about to modify is backed up
first if it already exists, in either mode. This is deliberately wider than the
requirement, which asked for a backup during repair: on a fresh install
`settings.json` may exist anyway - Claude Code was uninstalled, or another tool
wrote it - and "back up whatever we are about to overwrite" is one rule instead
of two, and never the wrong one.

### 6.3 The auth token

Step 4 asks for `ANTHROPIC_AUTH_TOKEN` through `prompts.secret`. Blank means
leave whatever is already there, which is what makes a repair run safe to do
without having the token to hand. The prompt says so, and when a value already
exists in `settings.json` it says that too - without printing it.

The token is written into `settings.json` `env` alongside the 256K profile. It
is **never** written into `lmi.json`: the config file is site-wide and meant to
be copied between machines; the token is per user.

**After writing a `settings.json` that contains the token, lmi sets the file to
mode `600`.** The file is otherwise created 644, which puts a credential in a
world-readable file on a multi-user box. On Windows `os.chmod` only toggles the
read-only bit and grants no protection - lmi does not pretend otherwise, and the
Windows path simply does not claim it.

### 6.4 Privileges: the `--global` fallback

`npm config set --global` writes the npmrc under `npm prefix -g`, and
`npm install -g` writes the global `node_modules`. On a system-wide Node install
both are root-owned, so an unelevated run fails with `EACCES`.

**The `npm config set` commands retry without `--global`.** Dropping the flag
writes `~/.npmrc`, which needs no root and still governs every `npm install -g`
that user runs. A correct fallback, not a degraded one. Both attempts are
printed, so the log shows which took effect.

**`npm install -g` has no fallback.** Dropping `-g` does not degrade, it does
something else: it installs into `./node_modules` of whatever directory the user
was in and creates no `claude` command at all - a silent wrong-install, which
for a provisioning tool is worse than a clean failure. A failing install goes
straight to exit 1, naming the two ways forward:

- re-run with `sudo` (or in an Administrator shell on Windows);
- or give npm a writable prefix - `npm config set prefix ~/.npm-global` - and
  put `~/.npm-global/bin` on PATH.

**lmi never invokes `sudo` itself.** A provisioning tool that silently escalates
privileges is one nobody can audit, and it would prompt for a password mid-run.
Explicitly rejected.

### 6.5 TLS

Artifactory usually serves HTTPS with a certificate signed by an internal CA
that Node does not ship, which is the only reason `strict-ssl false` is reached
for at all.

- **`cafile` configured:** `npm config set cafile <path>`; `strict-ssl` is left
  alone and verification stays on.
- **`cafile` absent:** `npm config set strict-ssl false`, plus a `[WARN]` every
  run saying verification is off for **every** npm install by this user from now
  on, and that `cafile` is the fix.

The risk is not external interception - it is that anyone on the internal
network who can answer as the registry host gets a package whose `postinstall`
script runs, with whatever privileges the install step has. `cafile` closes that;
`strict-ssl false` does not. Hence a warning every run rather than a one-time
note.

### 6.6 Confirming, without overclaiming

Step 10 is `shutil.which("claude")`.

- Found: print the resolved path, exit 0.
- Not found: exit **0** with a `[WARN]`. npm reported success, so the install
  happened; what is missing is PATH in *this* process, which cannot see an npmrc
  prefix change made moments ago. The warning says to open a new terminal and
  names the directory that must be on PATH: the `bin` subdirectory of
  `npm prefix -g`. Deliberately not `npm bin -g`, which meant exactly that and
  was removed in npm 9 - an error message telling the user to run a command that
  no longer exists is worse than none.

Exiting non-zero here would fail runs that in fact succeeded - the normal
outcome the first time npm's global bin directory is used on a machine.

---

## 7. `~/.claude/settings.json`

One read, one merge, one atomic write. Three things are merged in:

1. `env` - the 256K profile from config (4.2), plus `ANTHROPIC_AUTH_TOKEN` if
   one was given, plus `CLAUDE_CODE_GIT_BASH_PATH` on Windows (section 8).
2. `extraKnownMarketplaces` - the `marketplaces` object, passed through
   **unaltered**. lmi validates only that it is an object; whether an entry is a
   well-formed source is Claude Code's schema's business, and it reports
   violations better than a duplicated validator would. This is also what keeps
   lmi working when a source type is added upstream.
3. Nothing else. `model`, `enabledPlugins`, `theme` and every other key are
   preserved untouched.

**Merge semantics.** `dict.update` at the level of `env` and of
`extraKnownMarketplaces`, not at the document root - so an existing `env` key
lmi does not manage survives, and a marketplace under another name survives. A
key lmi *does* manage is overwritten, so re-running after editing the config
converges on the config rather than accumulating stale entries.

**An unparseable existing file is exit 3 and nothing is written.** Overwriting a
file a user hand-edited into invalid JSON would silently discard their settings;
refusing and naming the file lets them fix it.

---

## 8. Git Bash (Windows only)

Windows only, because `CLAUDE_CODE_GIT_BASH_PATH` is resolved through
`path/win32` and is never read on Linux or macOS. On those platforms steps 5 and
7 do not exist - not "run and no-op", but are not reached at all.

### 8.1 Finding it

In order, first hit wins. Every candidate is validated the way Claude Code
validates: the basename must be one of `bash.exe`, `sh.exe`, `bash`, `sh`,
**and** the file must exist. A candidate failing either is skipped, because
writing one Claude Code rejects gets us a warning and its own two-path fallback -
worse than having written nothing.

1. `CLAUDE_CODE_GIT_BASH_PATH` already set in the environment and still valid
2. `HKLM\SOFTWARE\GitForWindows` → `InstallPath`, then `\bin\bash.exe`, via
   `winreg` (stdlib). Also the `WOW6432Node` variant. This is the authoritative
   source and the reason lmi finds installs Claude Code cannot
3. `C:\Program Files\Git\bin\bash.exe`
4. `C:\Program Files (x86)\Git\bin\bash.exe`
5. `C:\Program Files\Git\usr\bin\bash.exe`
6. `%LOCALAPPDATA%\Programs\Git\bin\bash.exe` - a per-user Git install, which
   needs no admin and is therefore common on locked-down machines
7. Derived from `shutil.which("git")`: `<git_root>\bin\bash.exe`, where
   `git_root` is the parent of the parent of `git.exe` - it sits in `cmd\` or
   `bin\`

Not found: ask for a path with `prompts.text`, validating the same way and
re-asking once. Still nothing - or a blank answer - is a `[WARN]`, not a
failure: the install itself succeeded, Claude Code has its own fallback, and the
user can set the variable later. The warning names the variable and what it is
for.

### 8.2 Persisting it

Two places, both needed for different reasons:

- **The user environment variable**, so every future shell has it:
  `setx CLAUDE_CODE_GIT_BASH_PATH "<path>"`. `setx` is used rather than a raw
  `winreg` write because it broadcasts `WM_SETTINGCHANGE` itself. Its 1024-byte
  truncation - the trap pylmi walks into by using `setx` for **PATH** - does not
  apply: this value is a single short path, not an accumulated list. lmi never
  uses `setx` for PATH.
- **`settings.json` `env`**, so it applies regardless of how `claude` is
  launched. Requirement 5, and it also covers the case where the variable was
  set but the shell that runs `claude` predates it.

An existing value is overwritten, having already been preferred as candidate 1 -
so a valid existing setting round-trips unchanged, and only an invalid one is
replaced.

---

## 9. `~/.claude.json`

Set `hasCompletedOnboarding` to `true`. All operating systems.

**Lowercase `b`.** The exact key is `hasCompletedOnboarding`, verified in the
binary's settings key list and in a live file. The requirement was written
`hasCompletedOnBoarding`, which would write cleanly, parse cleanly, and leave
onboarding running.

**Written unless it is already exactly `true`.** A key present but `false` is
corrected: the requirement is that onboarding is skipped, and a `false` left in
place does not achieve it. Already `true` means the file is not written at all -
no backup, no rewrite, no timestamp churn on a 63 KB file for a no-op.

**Mode is preserved.** The file is `600` and holds per-project history; both the
rewrite and the backup keep that. `shutil.copymode` on the backup, and the
atomic write's temp file is chmod-ed before the `os.replace` rather than after,
so there is no window in which the contents exist at the default mode.

---

## 10. Backups

Any file lmi is about to modify, that already exists, is copied first to:

```
<name>.bk_<YYYYmmdd-HHMMSS>
```

`settings.json.bk_20260806-141530`, `.claude.json.bk_20260806-141530`. The
timestamp format matches the one `lmi schedule` uses in generated file names.
The constant is re-declared in this package rather than imported from
`commands/schedule/paths.py`: commands do not import each other, and promoting
it to `core/` in advance is the thing the architecture rule warns against.

Every backup is reported at the end of the run, by full path, in the summary -
which is the requirement, and is also the only moment at which a user learns a
file they may want back exists.

Backups are never pruned. A provisioning tool that deletes the user's previous
configuration to keep a directory tidy has its priorities backwards.

**Writes are atomic**: temp file in the same directory, `os.replace`, which is
atomic on POSIX and on Windows. A half-written `settings.json` is invalid JSON
and Claude Code cannot start without it - the one failure here that could damage
something the user already had. If the backup itself fails, nothing is written
and the run is exit 3: proceeding would mean modifying a file we could not
preserve.

---

## 11. Exit codes

| Code | Owner | Meaning |
|---|---|---|
| 0 | global | done. Includes "user declined repair" and the PATH warning of 6.6 |
| 2 | global | usage: bad or missing config, npm not on PATH, no terminal |
| 1 | install | an npm command failed |
| 3 | install | a Claude config file could not be read, backed up or written |
| 4 | install | a bug in lmi |

0 and 2 come from `core/errors.py` and are not redefined. 1, 3 and 4 live in
`lmi/commands/install/exit_codes.py`.

**4 deliberately keeps the meaning it has in `lmi schedule`.** The architecture
lets each command own its codes, and `schedule` uses 4 for "a bug in lmi". A
provisioning script should not have to learn a per-command definition of
internal error, so this command matches rather than exercising its freedom. 1 is
likewise the analogue of `schedule`'s 1: the external thing we shelled out to
failed.

**3 is separate from 1 on purpose.** By the time the config steps run, Claude
Code is installed - the outcome is a working `claude` with unwritten settings,
which is partial success and wants its own code. Folding it into 1 would say the
install failed.

Every user-caused failure raises `LmiError` with its code, which `cli.main`
already renders as `[ERROR] <message>` on stderr. No new error plumbing.

---

## 12. Testing

`python3 -m pytest tests/ -q`, no install needed, added under
`tests/commands/install/`.

**`fake_npm`**, following `fake_claude` exactly: a recording script on an
**exclusive** PATH - `monkeypatch.setenv("PATH", str(bindir))`, replacing rather
than prepending, so a real npm cannot win and quietly reconfigure the
developer's own npmrc or install a real package. Records each invocation's argv
in order; honours `FAKE_NPM_RC` and `FAKE_NPM_FAIL_GLOBAL` (fail only when
`--global` is present, which is how the fallback is exercised). Grows an
`npm.cmd` shim on Windows the way `fake_claude` grows `claude.bat`.

**`answers`**, a fixture that monkeypatches `prompts.confirm/secret/text` with a
scripted queue and records what was asked. Every interactive path is driven
through it; no test ever touches a real stdin.

**`on_windows`**, reused from the schedule suite - it patches the module's own
`_on_windows()`, never `os.name`, which pathlib reads at instantiation and which
makes every `Path()` raise `NotImplementedError` on Linux if faked.

Coverage:

*Config* - four-candidate precedence; `--config` at a nonexistent path is 2 and
does not fall through; invalid JSON, non-object top level, missing `"claude"`,
missing/empty/non-string `registry`, non-object `marketplaces`, non-object
`env`, a **non-string value inside `env`**, and a `cafile` pointing at nothing
are each 2; `~` expansion, and a `~nosuchuser` that raises `RuntimeError` is 2
not a traceback. The three 256K defaults appear when `env` is absent, and a
config `env` overrides one without dropping the other two.

*Interactive* - declining repair exits 0 and runs **no** npm command and writes
**no** file; accepting proceeds; a blank token leaves an existing one in place
and does not write the key; `EOFError` from any prompt is exit 2, not a hang;
every question is asked before the first npm command.

*npm* - commands run in order with the configured registry; `cafile` present
sends `cafile` and never `strict-ssl`; absent sends `strict-ssl false` and
warns; a non-zero install is exit 1 and **no config file is touched**; npm
missing is exit 2; `shell=True` appears nowhere in the package.

*The `--global` fallback* - with `FAKE_NPM_FAIL_GLOBAL`, each `npm config set`
is attempted twice and the second omits `--global`; `npm install -g` is
attempted **once** and the run exits 1.

*Git Bash* - each of the seven candidates wins in isolation and the order holds
when several exist; a candidate whose basename is `git.exe`, or which does not
exist, is skipped; registry lookup absent falls through cleanly; not-found
prompts, re-asks once, then warns and still exits 0; the resolved path reaches
both `setx` and `settings.json` `env`; **on Linux and macOS no candidate is
probed, no `setx` runs, and `CLAUDE_CODE_GIT_BASH_PATH` never appears in
settings**.

*settings.json* - unrelated keys survive; an unmanaged `env` key survives;
marketplaces under other names survive; a managed key is overwritten not
duplicated; missing file and missing `~/.claude/` are created; invalid existing
JSON is exit 3 and leaves the file byte-identical; a written token leaves the
file mode `600` on POSIX; the temp file is gone on both success and failure.

*.claude.json* - absent key is written; `false` is corrected to `true`; already
`true` writes nothing **and creates no backup**; mode `600` survives on the file
and on the backup; a 63 KB document round-trips with only that key changed.

*Backups* - naming is `<name>.bk_<stamp>`; both files are backed up when both
change; a failed backup aborts before any write; every backup path appears in
the final summary.

*Registration* - `[c.NAME for c in COMMANDS] == ["install", "schedule"]`.
`tests/test_cli.py::test_schedule_is_registered` asserts the exact list and
**will need updating** - it is the intended tripwire for adding a command.

Tests carrying `MANDATORY` in their docstring, each pinning a failure that is
**silent** - the run reports success while being wrong:

1. `hasCompletedOnboarding` is spelled with a lowercase `b`;
2. a failing `npm install -g` touches no config file;
3. `npm install -g` is never retried without `-g`;
4. an unparseable `settings.json` is not overwritten;
5. declining repair changes nothing at all;
6. Git Bash candidates are basename-validated, so lmi never writes a path Claude
   Code will reject;
7. no Git Bash work happens off Windows.

**What tests cannot cover.** A fake npm proves nothing about the real one. Four
things need a real run and go into `README.md` as a checklist, in the style of
the checks already there: that Artifactory serves the package; that `--global`
behaves as documented on the site's Node layout; that `extraKnownMarketplaces`
in user scope really registers a marketplace; and that a Windows box with Git in
a non-default location ends up with a working Bash tool.

---

## 13. Documentation

- `README.md`: a `lmi install claude` section - the config file, the four search
  paths, what each prompt asks, the exit codes, the sudo and PATH messages,
  where backups go, and the real-run checklist above.
- `examples/lmi.json`: a complete config with every key, so `cp` and edit is the
  whole setup.
- `CLAUDE.md`: `install` added to the architecture map; invariant 3 re-scoped to
  `lmi schedule` (section 3 here); and the silent failures listed in section 12
  added to its section 3 as regression guards.

---

## 14. Decisions

Recorded so they are not silently reversed.

1. **Delivery is npm via Artifactory**, not a mirrored binary release. §1.
2. **Interactive, with no `--yes`** - accepted cost: not scriptable. Guarded
   against hanging, which is not the same thing. §6.1.
3. **`--global`, then retry without it, never `sudo`** - and no retry at all for
   `npm install -g`. §6.4.
4. **`cafile` when configured, `strict-ssl false` otherwise**, warning every run
   in the second case. §6.5.
5. **Config holds only site-specific values**, plus the 256K `env` profile as an
   overridable default. §4.2.
6. **The token is prompted for, never stored in `lmi.json`**, and forces mode
   600 on `settings.json`. §6.3.
7. **Backups are taken whenever a file is about to change**, not only during
   repair. §6.2.
8. **`hasCompletedOnboarding` is corrected when `false`**, not only added when
   absent. §9.
9. **Git Bash work is Windows-only**, verified rather than assumed. §8.

**Open questions:** none.
