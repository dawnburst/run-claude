# Installing `lmi` on macOS

Goal: type `lmi` and have it run. No `python3 -m`, no activating anything.

> **Not yet verified on macOS.** Every step below is standard macOS practice and
> the code itself is tested on Python 3.9.23 and 3.13 — the version macOS ships
> is supported. But no part of this guide has been executed on a Mac. If
> something here is wrong, please report it; treat this as intended rather than
> proven. Linux and Windows have both been exercised end to end.

---

## Before you start

Open **Terminal** and check:

```bash
python3 --version
git --version
```

You need **Python 3.9 or newer**. macOS ships `python3` with the Xcode Command
Line Tools — recent versions provide 3.9.x, which is exactly the floor `lmi`
supports. If either command prompts you to install the Command Line Tools,
accept, or run:

```bash
xcode-select --install
```

`lmi` has no third-party dependencies at runtime, so the system Python is
enough. If you would rather not use it, `brew install python@3.12` and
substitute `python3.12` for `python3` throughout.

---

## Route A — virtual environment plus a symlink (recommended)

Nothing extra to install. Five steps.

### 1. Clone the repository

```bash
git clone https://github.com/dawnburst/run-claude.git ~/lmi
cd ~/lmi
```

Pick a **permanent** location. The launcher in step 4 points back at this path;
moving or deleting the directory later leaves a command that fails confusingly.

### 2. Create a virtual environment

```bash
python3 -m venv .venv
```

Unlike Debian and Ubuntu, macOS bundles `ensurepip`, so this works without extra
packages.

### 3. Install `lmi` into it

```bash
.venv/bin/python -m pip install .
```

Use `pip install -e .` instead if you want the command to track your checkout as
you edit it.

Do **not** use `sudo pip` or install into the system Python. Writing into
`/usr/bin`'s Python is blocked by System Integrity Protection and, where it
partially succeeds, produces a broken mix that is unpleasant to unpick.

### 4. Put the launcher on your PATH

The venv already contains a launcher at `.venv/bin/lmi` whose shebang pins the
venv's interpreter. Link it into a directory on your PATH:

```bash
mkdir -p ~/.local/bin
ln -sfn ~/lmi/.venv/bin/lmi ~/.local/bin/lmi
```

Check whether `~/.local/bin` is on your PATH:

```bash
echo "$PATH" | tr ':' '\n' | grep -q "$HOME/.local/bin" && echo on-path || echo MISSING
```

If it prints `MISSING`, add it. macOS has used **zsh** as the default shell
since Catalina, so the file is `~/.zshrc`:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Run `echo $SHELL` to confirm. If it says `/bin/bash`, use `~/.bash_profile`
instead.

### 5. Verify

```bash
which lmi          # -> /Users/you/.local/bin/lmi
lmi --version       # -> lmi 0.1.0
lmi schedule --help
```

If `which lmi` finds nothing, open a new Terminal tab — PATH changes apply only
to shells started afterwards.

---

## Route B — pipx

`pipx` gives each tool its own environment and manages PATH for you.

```bash
brew install pipx
pipx ensurepath
# open a new Terminal tab, then:
pipx install ~/lmi
lmi --version
```

Or without cloning:

```bash
pipx install "git+https://github.com/dawnburst/run-claude.git"
```

---

## First run

```bash
mkdir -p ~/work && cd ~/work
lmi schedule "Create a file named hello.txt containing the single word OK"
```

Expect exit 0, a `hello.txt`, a `run-claude-<timestamp>.log`, and a
`run-claude-state.md` that Claude has actually rewritten. A `run-claude.lock`
sits alongside them; that is normal.

`lmi` needs the Claude Code CLI on your PATH — check `claude --version`. If it
is missing, install it and run `claude auth login` once; `lmi` cannot perform
the interactive sign-in for you.

---

## Scheduled (unattended) runs

For a recurring job, `launchd` is the macOS equivalent of cron and survives
reboots. Point it at the **full launcher path** rather than the bare name, since
a `launchd` job does not inherit your interactive PATH:

```
/Users/you/lmi/.venv/bin/lmi
```

The same applies to a `crontab` entry. This is untested on macOS, like the rest
of this guide.

---

## Updating

```bash
cd ~/lmi
git pull
.venv/bin/python -m pip install .     # skip if you installed with -e
```

With pipx: `pipx upgrade lmi`.

---

## Uninstalling

```bash
rm ~/.local/bin/lmi
rm -rf ~/lmi
```

With pipx: `pipx uninstall lmi`.

---

## Troubleshooting

**`lmi: command not found`** — the symlink is missing, `~/.local/bin` is not on
PATH, or you have not opened a new Terminal tab. Re-run the checks in step 4.

**`bad interpreter: No such file or directory`** — the venv moved or was
deleted. The launcher's shebang holds an absolute path; recreate the venv
(steps 2-3) and relink.

**Apple silicon and Homebrew paths** — Homebrew installs to `/opt/homebrew` on
Apple silicon and `/usr/local` on Intel. If `brew` itself is not found, add the
right one to your PATH; this affects Route B only.

**`claude is not on PATH`** — see "First run".
