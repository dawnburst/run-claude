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

Three more commands surround it: [`lmi install claude`](docs/install-claude.md)
installs and configures Claude Code in the first place — on an air-gapped
machine, from an internal npm registry; [`lmi config`](docs/config.md) moves that
configuration between profiles afterwards and puts back the one the machine
started with; [`lmi upgrade`](docs/upgrade.md) updates `lmi` itself.

Pure Python, standard library only, Python 3.9 or newer.

---

## Getting started

Clone the repository, run the script for your platform, open a new terminal.
No sudo, no administrator rights, and nothing to activate afterwards.

### Prerequisites

- **Python 3.9 or newer** on `PATH` — check with `python3 --version`, or
  `py --version` on Windows. Nothing else: `lmi` is standard library only.
- **git**, to clone. Windows does not ship it; if you would rather not install
  it there, the two Windows guides start from downloading the wheel and the
  script into one folder instead.
- **A network, the first time.** A fresh clone carries no wheel, so the script
  builds one, and building fetches `setuptools`. Put a prebuilt
  `lmi-0.1.0-py3-none-any.whl` beside the script or in `dist/` and the install
  is offline end to end — which is how an air-gapped machine does it.
- **Not** the Claude Code CLI. You need it to *run* `lmi schedule`, but not to
  install `lmi`: [`lmi install claude`](docs/install-claude.md) puts it there
  afterwards.
- **Node.js 18 or newer**, but only for the `lmi install claude` step below —
  it installs Claude Code *through npm*, so a Node runtime has to be there
  first. `lmi` deliberately does not bootstrap one, and never invokes `sudo`.
  Nothing else in `lmi` needs Node.

### Linux, including WSL

```bash
git clone https://github.com/dawnburst/run-claude.git ~/lmi
cd ~/lmi
./scripts/install-linux.sh
```

### macOS

```bash
git clone https://github.com/dawnburst/run-claude.git ~/lmi
cd ~/lmi
./scripts/install-macos.sh
```

Both put `lmi` in a virtual environment of its own at `~/.local/share/lmi/venv`
and symlink the command into `~/.local/bin`. If that directory is not on your
`PATH` the script says so and prints the line to add.

### Windows — `cmd.exe` or PowerShell

```bat
git clone https://github.com/dawnburst/run-claude.git %USERPROFILE%\lmi
cd %USERPROFILE%\lmi
scripts\install-windows.cmd
```

Run the `.cmd` even from PowerShell: it wraps `install-windows.ps1` with
`-ExecutionPolicy Bypass` for that one invocation, because a default Windows
refuses to run a local `.ps1`. It installs with `pip install --user`, which
produces a real `lmi.exe`, and adds that Scripts directory to your user `PATH`.

### Then, on every platform

Open a **new** terminal — the installer put the command on your `PATH`, which
the shell you ran it from will not have picked up yet:

```bash
lmi --version           # -> lmi 0.1.0
lmi install claude      # installs and configures the Claude Code CLI
lmi schedule "read TASK.md and work through it" -i 30 -c 4
```

The clone is disposable once the script has run. Re-running the script is how
you upgrade, and `--uninstall` (`-Uninstall` on Windows) reverses it —
[`lmi upgrade`](docs/upgrade.md) is the other way, without re-cloning.

One prerequisite `lmi` cannot do for you: Claude Code must be **signed in
already**, once, interactively — `claude auth login`. An unattended run has
nobody to answer a sign-in prompt. See
[Before the first run](docs/schedule.md#before-the-first-run).

| Platform | Step-by-step guide | Status |
|---|---|---|
| Linux, including WSL | [docs/install/linux.md](docs/install/linux.md) | verified on Ubuntu 24.04, Python 3.12 and 3.9.23 |
| Windows — `cmd.exe` | [docs/install/windows-cmd.md](docs/install/windows-cmd.md) | verified on Windows, Python 3.13 |
| Windows — PowerShell | [docs/install/windows-powershell.md](docs/install/windows-powershell.md) | verified on Windows, Python 3.13 |
| macOS | [docs/install/macos.md](docs/install/macos.md) | install script verified on macOS 15, Python 3.9.6; **`lmi` itself not yet run there** |

Each guide gives the scripted route, the same steps by hand, and `pipx` if you
prefer it — plus a first run, updating, uninstalling, air-gapped installs, and
the troubleshooting specific to that platform. They all install **one file**,
`lmi-0.1.0-py3-none-any.whl`, about 22 KB: `py3-none-any` means any Python 3, no
compiled ABI, any operating system, and pip generates whatever launcher the
local OS needs from it.

For development in a repo-local environment:

```bash
python3 -m venv .venv          # or: virtualenv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

You do not need to install anything to run the test suite — see
[Testing](#testing).

---

## The commands

| Command | What it does | Reference |
|---|---|---|
| `lmi schedule` | Runs your task through Claude Code unattended, iteration after iteration, carrying state between them. | [docs/schedule.md](docs/schedule.md) |
| `lmi install claude` | Installs the Claude Code CLI from an internal npm registry and configures it: settings, auth token, statusline, onboarding. | [docs/install-claude.md](docs/install-claude.md) |
| `lmi config init` | Copies the config folder `lmi` ships into `~/.lmi`, keeping every file already there. The bootstrap scripts run it; run it yourself if that folder is gone. | [docs/config.md](docs/config.md#lmi-config-init) |
| `lmi config switch` | Applies a partial `settings.json` over `~/.claude/settings.json`, and restores the one the machine started with. | [docs/config.md](docs/config.md) |
| `lmi config schedule` | Shows or sets which backend `lmi schedule` runs Claude through. | [docs/config.md](docs/config.md#lmi-config-schedule) |
| `lmi upgrade` | Installs a newer `lmi` over the installation currently running. | [docs/upgrade.md](docs/upgrade.md) |

`lmi --help` lists them; `lmi <command> --help` is the authoritative flag list.

---

## `lmi schedule` in brief

```
lmi schedule "<prompt or prompt-file>" [-t "YYYY-MM-DD HH:MM"] [-i minutes]
             [-c count] [-d workdir] [-f "flags"] [-l logfolder]
             [-s statefile] [-r] [-v]
```

The prompt is the only mandatory argument — either the text itself, quoted, or
the path of a file containing it. The options worth knowing before you read
anything else:

| Option | Meaning |
|---|---|
| `-i <minutes>` `-c <count>` | Wait this long between iterations, this many times. **Mutually required** — either both or neither, and omitting both is a single run. There is deliberately no unlimited-loop mode. |
| `-d <dir>` | Working directory for claude. Omitted = the current directory. |
| `-s <file>` | State file. Omitted = `<workdir>/run-claude-state.md`. |
| `-v` | Watch the run while it runs: log the prompt lmi sends, and render claude's activity live. |

The [full option table](docs/schedule.md#options), the two backends, the state
protocol, logging, verbose mode, encoding rules and the known limitations are in
**[docs/schedule.md](docs/schedule.md)**.

### How one iteration works

Each iteration composes a prompt file containing, in order: a header saying the
run is unattended and no question may be asked; the iteration number, time,
working directory and state file path; a numbered **state protocol**;
`## CURRENT STATE`, the state file inlined whole; and `## TASK`, your prompt.
That file is fed to claude on stdin.

The protocol tells claude to keep this layout in the state file:

```
TASK_STATUS: IN_PROGRESS
## Goal
## Completed
## In progress
## Next steps
## Notes and blockers
```

and to write `TASK_STATUS: COMPLETE` on the **first line** only when the whole
task is finished. After each iteration the runner reads line 1 of the state file
and stops the loop early if it matches — [line 1 only, on
purpose](docs/schedule.md#how-the-iteration-loop-works).

### What it guarantees

Three invariants, each covered by the test suite and explained in
[docs/schedule.md](docs/schedule.md#guarantees):

- **Iterations never overlap.** The loop is sequential, and a second *instance*
  is refused by a lock file beside the state file with exit 3.
- **A failing claude call never fails the runner.** It is logged with `[ERROR]`
  — `[QUOTA]` too, for rate-limit wording — counted as failed, and the loop
  continues.
- **Nothing in `lmi schedule` ever waits for a keypress.** The prompt arrives on
  stdin and every wait is a `time.sleep`. `lmi install claude` and `lmi upgrade`
  are interactive by design; the unattended runner is not.

---

## Exit codes

`0` and `2` mean the same thing for **every** `lmi` command, and no command may
redefine them. The rest are owned by the command that defines them, and are
deliberately kept parallel so a provisioning script does not have to learn a
per-command vocabulary.

| Code | Meaning |
|---|---|
| 0 | Done — including "you declined", and warnings that did not change the outcome |
| 1 | The external thing failed: a `claude` call (`schedule`), an npm command (`install`), pip (`upgrade`). `lmi config` has no `1` — it shells out to nothing |
| 2 | Bad parameters, bad or missing config, a missing prerequisite, or no terminal to ask in |
| 3 | Changed nothing, or changed only part of it: another run holds the lock (`schedule`); a file could not be read, backed up or written (`install`, `config`); pip succeeded but the new version did not take (`upgrade`) |
| 4 | A bug in `lmi`, not in your task or your config |

Each command's reference page gives the exact table, and the reasoning where a
code needed splitting.

---

## Documentation

| File | What is in it |
|---|---|
| [docs/schedule.md](docs/schedule.md) | `lmi schedule` in full: options, backends, the state file, logging, verbose mode, encoding, known limitations |
| [docs/install-claude.md](docs/install-claude.md) | `lmi install claude`: the config file and its search order, the settings template, the statusline script, what it asks, writes and backs up, Git Bash, troubleshooting |
| [docs/config.md](docs/config.md) | `lmi config init`, `lmi config switch` and `lmi config schedule`: filling `~/.lmi`, named switch files, fragments, the merge, `origin` |
| [docs/upgrade.md](docs/upgrade.md) | `lmi upgrade`: the config section, what it refuses to upgrade, how success is verified |
| [docs/status.md](docs/status.md) | What has actually been executed on a real machine, and the list of what has not |
| [docs/install/](docs/install/) | One step-by-step install guide per platform |
| [docs/schedule-dos-and-donts.md](docs/schedule-dos-and-donts.md) | Writing a task prompt that survives being run unattended (also in [Hebrew](docs/schedule-dos-and-donts.he.md)) |
| [examples/](examples/) | A complete `lmi.json`, a complete `settings.json` template, and a `settings_switch.json` fragment — copy and edit |
| [CLAUDE.md](CLAUDE.md) | Developer handoff: the architecture, and every behaviour that must not regress |

---

## Testing

```bash
python3 -m pytest tests/ -q     # 756 passed, 19 skipped, in about four seconds
```

No install is required first — pytest puts the repository root on `sys.path`, so
the suite runs against a clean checkout. Eighteen of those skips are the module
that validates the SDK message fakes against the real dataclasses;
`pip install -e ".[sdk]"` is what runs them.

The suite never reaches a real `claude`, a real `npm`, a real `pip` or the real
SDK: the `fake_claude`, `fake_npm` and `fake_pip` fixtures replace `PATH` — or,
for pip, the interpreter — entirely with a temporary one, so no test can spend
quota, rewrite your `~/.npmrc`, or install a real package over the developer's
own `lmi`. An SDK-mode test that forgets its fake **fails loudly** rather than
reaching the real service, because replacing `PATH` protects nothing once the
call is a Python import.

What a fake can **never** cover is how the real CLI behaves. The two most
expensive bugs in this project's history — a state file the CLI refused to write
because it sat in `.claude/`, and a false `TASK_STATUS: COMPLETE` match on prose
inside the state file — were both *silent successes* that a fake reported as
healthy. So also run one:

```bash
lmi schedule "Create a file named hello.txt containing the single word OK"
```

Expect exit 0, a `hello.txt`, a `run-claude-<timestamp>.log`, and a
`run-claude-state.md` that Claude has actually rewritten. If it still reads like
the blank template, the state write was blocked.

[docs/status.md](docs/status.md) is the honest record of what has been executed
on a real machine and what has not.

---

## Repository layout

```
lmi/                  the package: cli.py dispatches, core/ holds what has no
                      command flavour, commands/ holds one package per command
tests/                pytest suite, mirroring the lmi/ tree
docs/                 this documentation, and the design specs under
                      docs/superpowers/
examples/             a complete lmi.json, settings.json and switch fragment
scripts/              the four install scripts, all installing the same wheel
runner-test-task.md   a deliberately five-step task file, for exercising a real
                      multi-iteration loop end to end
```

[CLAUDE.md](CLAUDE.md) carries the file-by-file map and the reasoning behind it.

---

## License

MIT — see [LICENSE](LICENSE). Use it, adapt it, redistribute it; just keep the
copyright notice.
