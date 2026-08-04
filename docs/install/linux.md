# Installing `lmi` on Linux

Goal: type `lmi` and have it run. No `python -m`, no activating anything.

Verified on Ubuntu 24.04 (including WSL2) with Python 3.13 and 3.9.23.

---

## Before you start

You need **Python 3.9 or newer** and `git`:

```bash
python3 --version
git --version
```

Anything from 3.9 up works. `lmi` has no third-party dependencies at runtime.

---

## Route A — virtual environment plus a symlink (recommended)

Nothing to install beyond what you have. Five steps.

### 1. Clone the repository

```bash
git clone https://github.com/dawnburst/run-claude.git ~/lmi
cd ~/lmi
```

Pick a **permanent** location. Do not install from a temporary directory or a
git worktree you intend to delete — the launcher in step 4 points back at this
path, and removing it later leaves a dangling command that fails confusingly.

### 2. Create a virtual environment

```bash
python3 -m venv .venv
```

**If that fails with `ensurepip is not available`**, you are on Debian or
Ubuntu, which ship `ensurepip` separately. Either install it:

```bash
sudo apt install python3-venv     # or python3.12-venv for a specific version
python3 -m venv .venv
```

or use `virtualenv`, which needs no root:

```bash
pip install --user virtualenv 2>/dev/null || python3 -m pip install --user virtualenv
virtualenv .venv
```

### 3. Install `lmi` into it

```bash
.venv/bin/python -m pip install .
```

Use `pip install -e .` instead if you want the command to track your checkout
as you edit it.

Do **not** run `pip install --user` or `pip install` outside the venv. On
Ubuntu 24.04 the system Python is externally managed (PEP 668) and will refuse.
`--break-system-packages` appears to work and then leaves an install wired to
whatever directory you ran it from, which breaks `import lmi` system-wide when
that directory moves.

### 4. Put the launcher on your PATH

The venv already contains a working launcher at `.venv/bin/lmi`, whose shebang
pins the venv's interpreter. Link it into a directory on your PATH:

```bash
mkdir -p ~/.local/bin
ln -sfn ~/lmi/.venv/bin/lmi ~/.local/bin/lmi
```

Check that `~/.local/bin` is actually on your PATH:

```bash
echo "$PATH" | tr ':' '\n' | grep -q "$HOME/.local/bin" && echo on-path || echo MISSING
```

If it prints `MISSING`, add it and reload:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Use `~/.zshrc` instead if your shell is zsh (`echo $SHELL` tells you).

### 5. Verify

```bash
which lmi          # -> /home/you/.local/bin/lmi
lmi --version       # -> lmi 0.1.0
lmi schedule --help
```

If `which lmi` finds nothing, open a new terminal — PATH changes only apply to
shells started afterwards.

---

## Route B — pipx

`pipx` gives each tool its own isolated environment and puts the command on
your PATH for you. Cleaner if you install several tools this way.

```bash
sudo apt install pipx        # Ubuntu/Debian
pipx ensurepath              # adds ~/.local/bin to PATH
# open a new terminal, then:
pipx install ~/lmi
lmi --version
```

`pipx ensurepath` edits your shell profile, so a new terminal is required.

To install straight from GitHub without cloning:

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
`run-claude-state.md` that Claude has actually rewritten.

`lmi` needs the Claude Code CLI on your PATH. Check with `claude --version`; if
it is missing, install it and run `claude auth login` once — `lmi` cannot do
the interactive sign-in for you.

---

## Updating

```bash
cd ~/lmi
git pull
.venv/bin/python -m pip install .     # skip if you installed with -e
```

With pipx: `pipx upgrade lmi`, or `pipx reinstall lmi` after pulling.

---

## Uninstalling

```bash
rm ~/.local/bin/lmi
rm -rf ~/lmi
```

With pipx: `pipx uninstall lmi`.

---

## Troubleshooting

**`lmi: command not found`** — the symlink is missing, or `~/.local/bin` is not
on PATH, or you have not opened a new terminal. Run the two checks in step 4.

**`bad interpreter: No such file or directory`** — the venv moved or was
deleted. The launcher's shebang holds an absolute path. Recreate the venv
(steps 2-3) and relink.

**`error: externally-managed-environment`** — you are installing outside the
venv. Use `.venv/bin/python -m pip`, not bare `pip`.

**`claude is not on PATH`** — `lmi` found no Claude Code CLI. See "First run".
