# lmi

A Python CLI that runs the [Claude Code](https://claude.com/claude-code) CLI
**unattended**: start now or at a scheduled time, repeat on an interval, carry
progress across iterations through a state file, log everything, and never die
because a single `claude` call failed.

It exists because a long task usually does not fit in one session. Instead of one
huge prompt, you give `lmi schedule` a task and an iteration count; each
iteration is a fresh `claude -p` invocation that reads the state file the previous
iteration wrote, continues from there, and updates it. The loop stops early the
moment the state file reports the task is done.

A second command, [`lmi install claude`](#lmi-install-claude), installs and
configures that CLI in the first place — on an air-gapped machine, from an
internal npm registry.

Pure Python, standard library only. Requires Python 3.9 or newer and the Claude
Code CLI.

---

## Requirements

- **Python 3.9 or newer.** No runtime dependencies beyond the standard library.
- The **Claude Code CLI on `PATH`**, resolvable as `claude`. If the machine does
  not have it yet, [`lmi install claude`](#lmi-install-claude) installs it from
  an internal npm registry and configures it.
- **Authentication already done**, interactively, once: `claude auth login`. An
  unattended run has nobody to complete a sign-in prompt. Credentials live in
  `~/.claude/.credentials.json` (`%USERPROFILE%\.claude\` on Windows) and are
  per-user — WSL credentials do not carry over to a Windows install.

`lmi schedule` validates its arguments and prerequisites up front and exits with
a clear message rather than failing halfway through a scheduled overnight run.

---

## Installing

Step-by-step guides, one per platform. Each ends with a bare `lmi` command on
your PATH — no `python -m` prefix and nothing to activate.

| Platform | Guide | Status |
|---|---|---|
| Linux, including WSL | [docs/install/linux.md](docs/install/linux.md) | verified on Ubuntu 24.04, Python 3.12 and 3.9.23 |
| Windows — `cmd.exe` | [docs/install/windows-cmd.md](docs/install/windows-cmd.md) | verified on Windows, Python 3.13 |
| Windows — PowerShell | [docs/install/windows-powershell.md](docs/install/windows-powershell.md) | verified on Windows, Python 3.13 |
| macOS | [docs/install/macos.md](docs/install/macos.md) | install script verified on macOS 15, Python 3.9.6; **`lmi` itself not yet run there** |

Each guide gives a scripted route, the same steps by hand, and `pipx` if you
prefer it to manage isolation for you — plus a first run, updating,
uninstalling, and the troubleshooting specific to that platform.

### One wheel, every platform

You install **one file: `lmi-0.1.0-py3-none-any.whl`**, about 22 KB. That name is
the compatibility contract: `py3` any Python 3, `none` no compiled ABI, `any`
**any operating system**. `lmi` is pure Python with no third-party dependencies
(`dependencies = []`, every import from the standard library, no `.c` or `.so`
anywhere), which is what earns the universal tag. There is no per-platform
artefact to build, test, or keep in sync — `tests/test_packaging.py` fails if any
of those properties is lost.

pip then generates whatever launcher the local OS needs from that same wheel: a
real `lmi.exe` on Windows, a shebang script elsewhere. The platform-specific work
happens on the user's machine, at install time, by pip.

Build it once, on any machine with a network:

```bash
python3 -m pip wheel --no-deps -w dist .
```

Linux and WSL:

```bash
git clone https://github.com/dawnburst/run-claude.git ~/lmi
cd ~/lmi && ./scripts/install-linux.sh
```

It installs the wheel into a virtual environment of its own at
`~/.local/share/lmi/venv` and symlinks the generated command into
`~/.local/bin`, so **the clone is disposable afterwards**. Re-running it is how
you upgrade; `--uninstall` reverses it. [`lmi upgrade`](#lmi-upgrade) is the
other way to upgrade, without re-cloning — but it reads its config from the
same file as `lmi install claude`, and `./config/lmi.json` goes away with the
clone. A machine you intend to upgrade in place this way wants a config kept
somewhere the clone's disappearance cannot take with it. Copy
[`examples/lmi.json`](examples/lmi.json), not the shipped `config/lmi.json` —
the shipped file has no `lmi` section at all, precisely so nobody points
`lmi upgrade` at public PyPI by accident, where `lmi` is not a package this
project publishes. Edit the copy's `lmi.index` to name your site's own Python
index before using it:

```bash
mkdir -p ~/.lmi && cp examples/lmi.json ~/.lmi/config.json
# then edit ~/.lmi/config.json: set "lmi.index" to your site's package index
```

Windows:

```bat
scripts\install-windows.cmd
```

It installs the wheel with `pip install --user`, which produces a **real
`lmi.exe`**, and adds that Scripts directory to your user PATH. Run the `.cmd`
even from PowerShell: it wraps `install-windows.ps1` with `-ExecutionPolicy
Bypass` for that one invocation, because a default Windows refuses to run a local
`.ps1`. Note **git is not on a stock Windows** — both Windows guides start from
downloading the wheel and the script into one folder, which the installer expects.

macOS has `scripts/install-macos.sh`, a close mirror of the Linux one. It has now
run end to end on macOS 15 with the Command Line Tools Python 3.9.6, which
exercised the macOS-specific parts — the `python3` search, the `readlink -f`-free
ownership check, bash 3.2 syntax — and produced a working `lmi --version`.
`--uninstall` has not run there.

That run found the one bug the mirror could not predict: the Command Line Tools
pip (21.2.4) mis-resolves the paths of its own build environment, so the
`setuptools>=61` it downloads never reaches the build backend, and the system
setuptools 58 — which predates PEP 621 and cannot read `[project]` — builds an
empty `UNKNOWN-0.0.0-py3-none-any.whl` and reports success. Both Unix installers
now check that a wheel called `lmi-*` actually appeared, and rebuild in a
throwaway venv with a current pip if not.

That retry is deliberately narrow, for the air-gapped case: it fires only when
pip exited **0** having built the wrong thing. A non-zero pip is a real failure —
usually no network — which a second pip cannot fix either, so it is reported
straight away rather than retried behind another venv and two more index
timeouts. And none of it runs at all when a wheel is supplied: with
`lmi-*.whl` beside the script, in `dist/`, or passed to `--wheel`, the build
block is skipped entirely and the install is pure `--no-index`. Verified against
an unreachable index: 0.9 s with the wheel present, 2.3 s including creating the
venv from scratch.

**Installing needs no network.** Every install command passes `--no-index`, and a
wheel needs no build backend — unlike `pip install .`, which fetches
`setuptools>=61` to build. So an air-gapped machine needs the 22 KB wheel and
nothing else. Only *building* the wheel wants a network.

Three pitfalls the guides exist to steer around:

- **On Windows, `pip install --user` appears to work and then `lmi` is still
  "not recognized"**, because the user Scripts directory is not on PATH by
  default. The installer adds it. Its location comes from `sysconfig`, not
  `%APPDATA%\Python\PythonXX\Scripts`, which is wrong for a Microsoft Store
  Python — that inserts a version level.
- **On Debian and Ubuntu, `pip install --user` is refused outright** with "This
  environment is externally managed" (PEP 668), and `python3 -m venv` fails with
  `ensurepip is not available` because Debian ships that separately. The
  installer needs neither root nor apt: it falls back to
  `python3 -m venv --without-pip` and populates it with the system pip's
  `--python` flag. Verified on Ubuntu 24.04 with `python3-venv` absent.
- **Running from a UNC path on Windows.** Windows cannot lock a file on a share,
  so `lmi schedule` **refuses** a UNC working directory with exit 2 and points at
  the fix — `-s` on a local drive, which lets the working directory stay on the
  share. See [Known limitations](#known-limitations).

For development in a repo-local environment:

```bash
python3 -m venv .venv          # or: virtualenv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

You do not need to install anything to run the test suite — see
[Testing](#testing).

---

## Usage

```
lmi schedule "<prompt or prompt-file>" [-t "YYYY-MM-DD HH:MM"] [-i minutes]
             [-c count] [-d workdir] [-f "flags"] [-l logfolder]
             [-s statefile] [-r]
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
| `-f "<flags>"` | Extra claude CLI flags, appended after the always-on defaults. |
| `-l <folder or file>` | Log destination. A folder receives `run-claude-<timestamp>.log`; a path with an extension is used as the log file itself. Omitted = `<workdir>/run-claude-<timestamp>.log`. |
| `-s <file>` | State file. Omitted = `<workdir>/run-claude-state.md`. |
| `-r` | Resume: keep the existing state file instead of backing it up and starting clean. |

`-i` and `-c` are **mutually required** — either both or neither. Each alone exits
2, with a message explaining why. On its own, `-i` says how long to wait but never
when to stop; `-c` says how many iterations but never how long to wait between
them. There is deliberately no unlimited-loop mode: an unattended runner with no
stop condition is a liability.

Every invocation always passes `--allowed-tools=Edit,Write` and
`--add-dir <state file directory>`. Anything you give with `-f` is appended after
those, so `-f "--model opus"` composes rather than replaces.

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
lmi schedule task.md -t "2026-08-01 22:00" -i 60 -c 12 -f "--model opus"

# continue yesterday's task instead of starting clean
lmi schedule task.md -i 20 -c 5 -r
```

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
[`lmi install claude`](#lmi-install-claude) is interactive by design, and guards
only against *hanging*.

### Logging

Everything claude prints, plus every runner action, goes to both the console and
the log file: the resolved configuration, each iteration's start, end, exit code
and duration, state file handling, and a final summary of how many iterations ran,
succeeded and failed. A crash inside the runner itself is logged with its full
traceback, not merely printed to a terminal nobody may be watching.

A log file that cannot be written **degrades to console output** with one `[WARN]`
— it never decides the exit code.

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
- **No log rotation.** Each run writes a new timestamped log file.
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

## lmi install claude

The second command, and the one you run first. It installs the **Claude Code CLI
itself** on a machine with no route to the public npm registry: it points npm at
your internal Artifactory, runs `npm install -g @anthropic-ai/claude-code`, and
then writes the configuration the site expects — the auth token, the
marketplaces, the 256K context profile, the Windows Git Bash path — and marks
onboarding complete, so the first `claude` gets to work instead of asking
questions.

```
lmi install claude [--config PATH]
```

**It is interactive, and it needs a terminal.** It asks before repairing an
existing install, asks for the auth token, and asks for the Git Bash path when it
cannot find one. There is deliberately no `--yes`, so it cannot be driven from an
Ansible play, a Dockerfile or a CI step — an accepted cost, not an oversight.
What it will never do is *hang*: with no terminal, `input()` and `getpass()`
raise `EOFError`, and that becomes exit 2 with a message rather than a
provisioning run blocked forever with nobody there to answer it.

**npm has to be there already.** If `npm` is not on PATH the command stops with
exit 2 and says to install Node.js 18 or newer first. `lmi` deliberately does not
bootstrap a runtime, and it never invokes `sudo`.

### The config file

Everything that differs between sites lives in one JSON file; nothing
site-specific is compiled into `lmi`. [`examples/lmi.json`](examples/lmi.json) is
a complete one — copy it and edit it.

Searched in this order, first match wins:

1. `--config PATH`
2. `$LMI_CONFIG`
3. `./config/lmi.json`
4. `~/.lmi/config.json`

The working-directory default is `./config/lmi.json` — a checkout keeps its
config in one obvious place rather than loose in the root. This repository
ships one, pointing at the public npm registry; a site replaces it.

A file left at the **old** `./lmi.json` path is **exit 2**, not a silent skip.
Skipping it would let `~/.lmi/config.json` win — a different registry — while
an `lmi.json` sits in plain view in the working directory, which is the same
wrong-registry provisioning the `--config` rule below prevents, arrived at from
the other direction. The message says how to move it, and `--config ./lmi.json`
keeps it where it is.

A `--config` that points at a file which does not exist is **exit 2**, never a
quiet fall-through to the next candidate: an explicitly named file that silently
resolves to a different one is how a machine gets provisioned against the wrong
registry without anybody finding out.

```json
{
  "claude": {
    "registry": "https://artifactory.example.com/api/npm/npm-virtual/",
    "cafile": "/etc/ssl/certs/corp-ca.pem",
    "marketplaces": {
      "corp-tools": {
        "source": {
          "source": "git",
          "url": "https://git.example.com/claude/marketplace.git"
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
| `registry` | **yes** | The npm registry URL to install from — your internal Artifactory. |
| `cafile` | no | PEM file for the internal CA. Present: TLS verification stays on. Absent: `npm config set strict-ssl false`, with a warning every run. |
| `marketplaces` | no | Merged verbatim into `extraKnownMarketplaces` in `~/.claude/settings.json`. |
| `env` | no | Merged into `env` in `~/.claude/settings.json`. Defaults to the three keys above. |

Anything else in the file is ignored, and the whole `claude` section is validated
before a single npm command runs. `cafile` in particular is checked for existence
up front, because `npm config set cafile /typo` succeeds and the mistake resurfaces
much later as an unrelated TLS error from the install step.

**The three `env` keys are the 256K context profile, and they are a default
rather than a hardcode.** A config file with no `env` still gets them; a site that
needs different numbers, or an extra variable such as `ANTHROPIC_BASE_URL` for a
gateway, sets them here and no code changes. **The values are strings** —
`"256000"`, not `256000`. Claude Code types `settings.json` `env` as string to
string, so a JSON number writes cleanly, parses cleanly and does nothing at all.
`lmi` refuses one with exit 2 rather than letting you discover that a month later.

The auth token is **not** a config key. The file is site-wide and meant to be
copied between machines; the token is per user, and it is prompted for.

### What it asks

At most three questions, and all of them are asked **before anything on the
machine changes**. Abandon the command at a prompt and nothing has been touched.

| Question | When | A blank answer |
|---|---|---|
| `Repair the installation?` | only when `claude` is already on PATH — the resolved path is printed first | keeps the default, **no**: exit 0, no npm command, no backup, no write |
| `Claude Code auth token` | on every run that is going to do anything — i.e. once the repair question, if it was asked at all, has been answered yes. Read with `getpass`, so it is never echoed into your scrollback | **keeps whatever token is already configured**, or skips it if there is none |
| `Full path to bash.exe` | Windows only, and only when no Git Bash was found | skips it, with a `[WARN]` naming `CLAUDE_CODE_GIT_BASH_PATH` |

Declining the repair is not an error. You answered the question; the answer was
no; exit 0.

### What it writes

`~/.claude/settings.json`, merged one level down rather than at the document
root, so `model`, `theme`, an `env` key `lmi` does not manage and a marketplace
under another name all survive:

- `env` — the 256K profile, plus `ANTHROPIC_AUTH_TOKEN` if you gave one, plus
  `CLAUDE_CODE_GIT_BASH_PATH` on Windows.
- `extraKnownMarketplaces` — your `marketplaces` object, passed through
  unaltered. `lmi` checks only that it is an object; Claude Code's own schema
  reports a malformed source better than a duplicated validator would.

A `settings.json` that ends up holding the token is mode `600`, and it is `600`
for the whole of its existence: the temp file it is written through is *created*
`600` rather than created at the umask default and fixed afterwards, and the mode
is settled before the atomic replace publishes it. `~/.claude/` is `0755`, so the
tidier-looking order — write the token, then `chmod` — would leave it readable by
every user on the box for the length of the write, and leave nothing behind to
show it had. On Windows `os.chmod` only toggles the read-only bit and grants no
protection — `lmi` does not pretend otherwise there.

`~/.claude.json`, one key: `hasCompletedOnboarding` set to `true`. **Lowercase
`b`.** `hasCompletedOnBoarding` is the natural way to write it, and it writes
cleanly, parses cleanly and does nothing — you meet the onboarding flow this
command promised to skip, and the run reports success. A key already exactly
`true` means the file is not rewritten at all: no backup and no churn on a 63 KB
document for a no-op. A key present but `false` is corrected.

Both writes are atomic — temp file beside the target, then `os.replace`. A
half-written `settings.json` is invalid JSON and Claude Code will not start
without it. And an existing file that is **already** invalid JSON is refused with
exit 3 and left byte-identical, rather than treated as an empty document and
overwritten: that would silently discard everything you had hand-edited.

### Backups

Any file about to be modified, that already exists, is copied first to:

```
<name>.bk_<YYYYmmdd-HHMMSS>
```

— `settings.json.bk_20260806-141530`, `.claude.json.bk_20260806-141530`. The copy
preserves the mode, because `~/.claude.json` is `600` and holds your per-project
history; a backup at the default 644 would publish it. If a backup fails, **the
file it was for is not modified** and the run stops there with exit 3: changing a
file we could not preserve first is not worth the risk.

Every backup is reported by full path at the end of the run, which is normally
the only moment you learn that a file you may want back exists. Normally, because
that summary is printed only when the run reaches the end: if a later step fails,
backups already taken are on disk but never announced. On a run that ended with
an error, look for `.bk_` beside `~/.claude/settings.json` and `~/.claude.json`
rather than assuming there is nothing there. **They are never pruned.**
A provisioning tool that deletes your previous configuration to keep a directory
tidy has its priorities backwards.

### Git Bash — Windows only

`CLAUDE_CODE_GIT_BASH_PATH` is resolved by Claude Code through
`require("path/win32")` and is **never read on Linux or macOS**. So on those
platforms this work does not run at all — not "runs and no-ops": nothing is
probed, `setx` is never called, and the variable never appears in
`settings.json`, where it would just be a meaningless line in a file you read.

Claude Code's own detection checks exactly two paths —
`C:\Program Files\Git\bin\bash.exe` and the `(x86)` variant — so a Git installed
anywhere else is invisible to it. That is what makes searching harder worth
doing. In order, first hit wins: an existing valid `CLAUDE_CODE_GIT_BASH_PATH`,
`InstallPath` from `HKLM\SOFTWARE\GitForWindows` in both registry views, the two
paths above, `C:\Program Files\Git\usr\bin\bash.exe`, a per-user install under
`%LOCALAPPDATA%\Programs\Git`, and finally a path derived from `where git`.

Every candidate is validated **the way Claude Code validates**: the basename must
be one of `bash.exe`, `sh.exe`, `bash`, `sh`, and the file must exist. Anything
else it warns about and ignores — so writing a path it rejects is worse than
writing nothing, because the machine looks configured and is not. The same check
is applied to the path you type at the prompt.

What is found is persisted twice, for different reasons: `setx` for the user
environment variable, so every future shell has it, and `settings.json` `env`, so
it applies however `claude` is launched. A failed `setx` is a `[WARN]`, not a
failed install — npm has already succeeded by then, and the `settings.json` half
still takes effect.

### When it does not work

- **`npm install -g` failed with `EACCES`.** The global `node_modules` is
  root-owned. Either re-run with `sudo` (an Administrator shell on Windows), or
  give npm a prefix you own — `npm config set prefix ~/.npm-global`, then put
  `~/.npm-global/bin` on your PATH — and run this again. `lmi` never invokes
  `sudo` itself: a provisioning tool that silently escalates is one nobody can
  audit. Note that `npm config set` *does* retry without `--global`, writing
  `~/.npmrc`, which needs no root and still governs every `npm install -g` you
  run. `npm install -g` has no such fallback, on purpose — dropping `-g` does not
  degrade, it installs into `./node_modules` of whatever directory you were in,
  creates no `claude`, and exits 0.
- **"npm reported success but `claude` is not on PATH".** Exit 0 with a `[WARN]`,
  and normally not a problem: this is what the first use of npm's global bin
  directory on a machine looks like, because the running process cannot see a
  PATH change made a moment ago. **Open a new terminal** and run `claude`. If it
  is still missing, add the `bin` subdirectory of `npm prefix -g` to your PATH.
  Exiting non-zero here would fail runs that in fact succeeded.
- **"certificate verification is now OFF".** You have no `cafile` configured, so
  `strict-ssl` was turned off for **every** npm install by this user, not just
  this one. The risk is not interception from outside — it is that anyone on the
  internal network who can answer as the registry host gets a package whose
  install scripts run. Point `cafile` at your internal CA to close it. The
  warning repeats every run, deliberately.

### Exit codes

`0` and `2` mean the same thing for every `lmi` command. `4` matches `schedule`'s
`4` rather than exercising the freedom to differ, because a provisioning script
should not have to learn a per-command definition of "a bug in `lmi`".

| Code | Meaning | Scope |
|---|---|---|
| 0 | Done — including "you declined the repair" and the PATH warning above | global |
| 1 | An npm command failed | `install` |
| 2 | Bad or missing config, npm not on PATH, or no terminal to ask in | global |
| 3 | A Claude config file could not be read, backed up or written | `install` |
| 4 | A bug in `lmi` | `install` |

`3` is separate from `1` on purpose. When a config file cannot be *written*, npm
has already succeeded, so the outcome is a working `claude` with unwritten
settings — partial success, which wants its own code. Folding it into `1` would
report that the install failed.

`3` on its own tells you **nothing** about how far the run got, so do not key a
provisioning script off it as "partially done" — or as "nothing happened". Both
extremes occur:

- `~/.claude/settings.json` is *read* before any npm command runs — that is how
  the command knows whether a token is already configured — so an unparseable
  one **there** is exit 3 with nothing installed and nothing changed.
- `~/.claude.json` is read *last*, after npm has installed Claude Code and after
  `settings.json` has been backed up and rewritten. An unparseable one **there**
  is exit 3 with the install done, the settings replaced, a
  `settings.json.bk_<stamp>` on disk — and no summary, because the run ends
  before the closing report that would have named it.

The message says which file it was, and every backup is named
`<original>.bk_<timestamp>` beside the original whether it was announced or not.
The exit code does not distinguish the two cases.

### Real-run checklist

The suite drives a **fake npm** on an exclusive PATH, which proves the argv, the
order and the exit codes and proves nothing whatever about the real one. Four
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

---

## lmi upgrade

The third command. It installs a newer `lmi` from the package index named in the
config file, over the installation it is currently running from.

```
lmi upgrade [--version VERSION] [--config PATH]
```

It exists because the install scripts need a clone, and the guides above say the
clone is disposable — re-cloning it every time you want a newer `lmi` defeats
that. `lmi upgrade` lets an already-installed `lmi` update itself, with no clone
and no network access beyond the same index that provisioned it in the first
place.

### The config file

`lmi upgrade` reads the **same config file** as `lmi install claude` — the
search order above is identical — but its own top-level section, `lmi`. The
shipped `config/lmi.json` in this repository does **not** have one: `lmi` is
never published anywhere, so the only honest default is none at all rather
than a placeholder that would resolve a stranger's package of the same name
from public PyPI. Copy [`examples/lmi.json`](examples/lmi.json) and point
`lmi.index` at your site's own package index:

```json
{
  "lmi": {
    "index": "https://artifactory.example.com/api/pypi/pypi-virtual/simple/",
    "cafile": "/etc/ssl/certs/corp-ca.pem"
  }
}
```

| Key | Required | Meaning |
|---|---|---|
| `index` | **yes** | The Python package index to install from — pip's `--index-url`. It **replaces** pip's default index rather than adding to it, so an air-gapped machine cannot silently resolve `lmi` from public PyPI. |
| `cafile` | no | A CA certificate file — pip's `--cert`. Checked for existence when the config is read, not when pip runs, for the same reason `claude.cafile` is: a typo here would otherwise surface much later as an unrelated TLS error. |

### What it asks

At most one question, asked **before anything on the machine changes**:
whether to replace the running `lmi` with the version it found (the newest on
the index, or the one named by `--version`). Abandon it there and nothing has
been touched. There is deliberately no `--yes` — this command replaces the
binary that is currently executing it, and that is not something to automate
past. It has the same no-keypress-when-unattended guard as `lmi install
claude`: with no terminal, the question cannot be asked, and rather than hang
forever waiting for one, the command exits 2.

### `--version`

Omit it and `lmi upgrade` asks the index for the newest version. Pass one to
pin an exact version instead — including going **back** to a known-good
version if a newer one turns out to be bad.

An unchanged version number means exactly that: nothing to install, exit 0.
`scripts/install-linux.sh` passes `--force-reinstall` because the version does
not change on every source change during development; `lmi upgrade`
deliberately has no such flag, so if a site republishes `0.1.0` with different
content inside, `lmi upgrade` reports "already at the newest" and changes
nothing. Bump the version in `pyproject.toml` to ship new code.

### What it upgrades, and what it refuses

`lmi upgrade` upgrades exactly the two installation shapes the install scripts
produce:

- a **virtual environment of its own** — `~/.local/share/lmi/venv`, the shape
  `install-linux.sh` and `install-macos.sh` create.
- a **`pip install --user`** install — the shape `install-windows.cmd`
  produces.

Anything else is refused with exit 2, before pip is invoked, rather than
guessed at:

- **An editable checkout** (`pip install -e`, what a repo clone under active
  development looks like). Upgrading it would install a released wheel over a
  working tree — it would look exactly like a successful upgrade while
  discarding whatever is uncommitted there.
- **A pipx install.** Upgrading it from underneath pipx would leave pipx's own
  record describing a version that is no longer installed. The message says to
  run `pipx upgrade lmi` instead.
- **Anything else** — a system-wide install, in particular. A wrong guess here
  installs a second copy that nothing on `PATH` ever reaches, which is worse
  than refusing.

### Verification

Success is confirmed by running the **installed console script** in a fresh
subprocess and reading what it reports — never by reading this process's own
`lmi.__version__`. That value was imported before pip ran, so it is always the
*old* version, whatever pip just put on disk: a command that trusted it would
report "upgraded 0.1.0 → 0.2.0" while 0.1.0 was still what ran.

### Exit codes

`0` and `2` mean the same thing for every `lmi` command; `4` matches
`schedule`'s and `install`'s.

| Code | Meaning | Scope |
|---|---|---|
| 0 | Upgraded, already at the newest (or the requested) version, or you answered no | global |
| 1 | The pip install failed | `upgrade` |
| 2 | Bad config, an installation shape `lmi upgrade` cannot handle, no terminal to ask in, Ctrl-C at the prompt, or a bad `--version` | global |
| 3 | pip succeeded, but the installed command now reports the wrong version | `upgrade` |
| 4 | A bug in `lmi` | `upgrade` |

`3` is separate from `1` on purpose: by the time verification runs, pip has
already succeeded and the machine has changed, so "the upgrade failed" would be
the wrong sentence for what happened.

Whether pip can displace a running `lmi.exe` on Windows is not yet settled —
see [Still to verify](#still-to-verify).

---

## Project layout

```
lmi/                  the package
  cli.py              top-level argparse parser and command dispatch
  core/               errors and global exit codes, path classification,
                      BOM-aware decoding, the single-instance lock
                      (fcntl / msvcrt), logging, config file discovery, and
                      asking a yes/no question
  commands/
    install/          the lmi install claude command: the "claude" config
                      section, the prompts, npm, the two Claude config
                      documents, Windows Git Bash
    schedule/         the lmi schedule command: config/validation, paths,
                      prompt composition, the state file, the iteration loop
    upgrade/          the lmi upgrade command: the "lmi" config section,
                      detecting the installation, the one pip command,
                      verifying by running the installed script
tests/                pytest suite, mirrors the lmi/ tree
config/lmi.json       the config lmi install claude reads by default, when run
                      from this directory. It has no "lmi" section on purpose
                      (see lmi upgrade, below) - lmi upgrade run against this
                      checkout with no other config hits the usual "no config
                      file found" error and prints the pasteable example
examples/lmi.json     a complete lmi.json, with both "claude" and "lmi"
                      sections, to copy and edit
docs/install/         per-platform install guides, one file each
docs/superpowers/     the design specs, one per command
scripts/              install scripts, all four installing the same wheel:
                      install-linux.sh, install-macos.sh,
                      install-windows.cmd, install-windows.ps1
runner-test-task.md   a deliberately five-step task file, for exercising a
                      real multi-iteration loop end to end
pyproject.toml        packaging: name, entry point, Python >=3.9, pytest
CLAUDE.md             developer handoff: architecture and the behaviours that
                      must not regress
README.md             this file
LICENSE               MIT
```

`runner-test-task.md` is CRLF, as a file that came from Windows. The two Windows
installers (`install-windows.cmd`, `install-windows.ps1`) are currently **LF**,
and the verified Windows install ran that way — worth knowing before anyone
"fixes" them in either direction, since cmd.exe can misparse an LF batch file.

---

## Testing

```bash
python3 -m pytest tests/ -v
```

No install is required first — pytest puts the repository root on `sys.path`,
so the suite runs against a clean checkout. A virtual environment is only
needed to exercise the installed `lmi` console script itself, not to run the
tests. Currently **351 tests, 1 skipped, the rest passing**, in under two
seconds.

The suite never reaches a real `claude`, a real `npm`, or a real `pip`: the
`fake_claude`, `fake_npm` and `fake_pip` fixtures replace `PATH` (or, for pip,
the interpreter) entirely with a temporary one, so no test can spend quota,
rewrite your `~/.npmrc`, or install a real package over the developer's own
`lmi`. The fakes are real subprocesses, deliberately, because the argv, the
stdin redirection and the exit code are the parts most worth
covering.

What a fake can **never** cover is how the real CLI behaves. The two most
expensive bugs in this project's history — a state file the CLI refused to write
because it sat in `.claude/`, and a false `TASK_STATUS: COMPLETE` match on prose
inside the state file — were both *silent successes* that a fake reported as
healthy. Only a real run caught either. So also run one:

```bash
lmi schedule "Create a file named hello.txt containing the single word OK"
```

Expect exit 0, a `hello.txt`, a `run-claude-<timestamp>.log`, and a
`run-claude-state.md` that Claude has actually rewritten. If it still reads like
the blank template, the state write was blocked.

### Platform status — be precise about this

Development happens on Linux. What has actually been executed elsewhere:

- **Windows: verified.** Install and uninstall through both
  `install-windows.cmd` and `install-windows.ps1` against a Microsoft Store
  Python 3.13; a real `lmi.exe` produced by pip; a bare `lmi` resolving in a new
  window; exit codes 0 and 2 coming back through the `.exe`; and a full
  `lmi schedule` run on local NTFS writing its log, state file and lock. The
  **Windows file-locking branch** (`msvcrt.locking`) has therefore now run — and
  running it is what exposed the UNC limitation in
  [Known limitations](#known-limitations).
- **macOS: the install script only.** `scripts/install-macos.sh` has run end to
  end on macOS 15 with the Command Line Tools Python 3.9.6 — Python search,
  wheel build, venv, install, symlink, and `lmi --version` returning `lmi 0.1.0`.
  That run is what found the empty-`UNKNOWN-0.0.0`-wheel bug described above.
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

### Still to verify

Three measurements have not been taken. None blocks use of `lmi schedule` or
`lmi upgrade`; all are named so nobody mistakes reasoning for evidence. `lmi
install claude` has its own four, in [Real-run checklist](#real-run-checklist).

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

---

## License

MIT — see [LICENSE](LICENSE). Use it, adapt it, redistribute it; just keep the
copyright notice.
