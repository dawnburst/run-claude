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

## Route A — the install script (recommended)

```bash
git clone https://github.com/dawnburst/run-claude.git ~/lmi
cd ~/lmi
./scripts/install-linux.sh
```

Then open a new terminal:

```bash
lmi --version       # -> lmi 0.1.0
```

That is the whole installation.

By default the script builds a **single self-contained executable** with the
standard library's `zipapp` module and copies it to `~/.local/bin/lmi`. That
matters for three reasons:

- **It needs no pip, no setuptools, no wheel, no virtual environment and no
  network.** It therefore works on an air-gapped machine, and on Debian and
  Ubuntu where `python3 -m venv` fails because `ensurepip` ships separately.
- **The installed file is the whole program**, about 44 KB. Once it is in place
  **the clone is disposable** — delete `~/lmi` and `lmi` keeps working. A
  virtual-environment install cannot do that; its launcher points back at the
  clone forever.
- Re-running the script is how you upgrade, and `--uninstall` reverses it.

### Options

| Option | Meaning |
|---|---|
| `--zipapp` | Single self-contained executable. **The default.** |
| `--venv` | Traditional pip install into `.venv` instead. Needs pip, and network unless `setuptools` and `wheel` are already local. Keeps the clone load-bearing. |
| `--editable` | `pip -e`, so `lmi` tracks your checkout. Implies `--venv`. Use this if you intend to edit the source. |
| `--link-dir DIR` | Where to put the command. Default `~/.local/bin`. |
| `--uninstall` | Remove the command, and `.venv` if there is one. Leaves the clone. |
| `-h`, `--help` | Show usage. |

### Air-gapped machines

Use the default. Nothing is fetched. You only need to get two things onto the
machine yourself, neither of them a Python package:

1. **The source**, since `git clone` cannot reach GitHub. Copy the repository
   in, then run the script. Alternatively build the executable on a connected
   machine and carry just that one file — it is portable, and the same file even
   runs on Windows and macOS.
2. **The Claude Code CLI, already authenticated.** `lmi` shells out to `claude`,
   and `claude auth login` is browser-based, so it cannot be automated. This is
   usually the harder constraint.

`pip install .` is what fails air-gapped, and it is worth knowing why: the
`[build-system]` table asks for `setuptools>=61`, which pip fetches from PyPI
into an isolated build environment. `--no-build-isolation` only moves the
requirement — then `setuptools` **and** `wheel` must already be installed
locally. The zipapp route sidesteps all of it.

### If it stops

The script fails loudly rather than half-installing, and every message says what
to do next. It handles explicitly:

- **Python missing or older than 3.9** — names the requirement and stops.
- **`--venv` with no way to create one** — prints both fixes and points at the
  default mode, which needs neither.
- **`--venv` with no network** — says that is expected and names the default
  mode instead.
- **Something already at the target path that it did not install** — refuses to
  touch it. It only ever removes a symlink into this clone, or a zipapp that
  actually contains `lmi/cli.py`.
- **Run from outside a clone** — says so instead of leaving debris.
- **A different `lmi` earlier on your PATH** — warns and names the winner, so
  you are not left wondering why nothing changed.

To uninstall:

```bash
cd ~/lmi
./scripts/install-linux.sh --uninstall
```

---

## Manual installation

Everything below installs `lmi` without the script. Route B is what the script
actually does, step by step — reach for it if the script stopped somewhere, if
you want to see each command, or if you would rather not run a script at all.

---

### Route B — a self-contained executable by hand

The same result as Route A: one file, no pip, no virtual environment, no
network. Four steps.

#### 1. Get the source onto the machine

```bash
git clone https://github.com/dawnburst/run-claude.git ~/lmi
cd ~/lmi
```

On an air-gapped machine, copy the repository across instead — any transport
will do, since nothing is fetched from here on.

#### 2. Stage just the package

`zipapp` packs a whole directory, so stage the `lmi` package on its own. Without
this you would also pack the tests, the docs and any `.venv`, and the archive
would be far larger than it needs to be.

```bash
mkdir -p build/stage
cp -r lmi build/stage/
find build/stage -name '__pycache__' -type d -exec rm -rf {} +
```

#### 3. Build the executable

```bash
python3 -m zipapp build/stage -m "lmi.cli:main" -p "/usr/bin/env python3" -o build/lmi
chmod +x build/lmi
```

`-m` names the entry point, the same `lmi.cli:main` that `pyproject.toml`
declares. `-p` writes the shebang, so the file runs directly. `/usr/bin/env
python3` rather than a fixed interpreter path keeps it working if `python3`
moves.

**The output must not be `build/stage/lmi`.** The package being packed is itself
called `lmi`, so writing the archive inside the staging directory collides with
it and `zipapp` fails with `IsADirectoryError`.

Check it before going further:

```bash
./build/lmi --version       # -> lmi 0.1.0
```

#### 4. Put it on your PATH

Copy rather than symlink — the file is the entire program, so copying it makes
the clone disposable:

```bash
mkdir -p ~/.local/bin
cp build/lmi ~/.local/bin/lmi
chmod +x ~/.local/bin/lmi
```

Confirm `~/.local/bin` is on your PATH:

```bash
echo "$PATH" | tr ':' '\n' | grep -q "$HOME/.local/bin" && echo on-path || echo MISSING
```

If it prints `MISSING`, add it and open a new terminal:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Use `~/.zshrc` instead if your shell is zsh (`echo $SHELL` tells you).

Then:

```bash
which lmi          # -> /home/you/.local/bin/lmi
lmi --version       # -> lmi 0.1.0
```

To upgrade, repeat steps 2-4 after a `git pull`. To uninstall,
`rm ~/.local/bin/lmi`.

---

### Route C — a virtual environment by hand

Use this if you want an editable install, or if you would rather see each step.
It needs pip, so it also needs the network on a machine without `setuptools`
and `wheel` already installed. Five steps.

#### 1. Clone the repository

```bash
git clone https://github.com/dawnburst/run-claude.git ~/lmi
cd ~/lmi
```

Pick a **permanent** location. Do not install from a temporary directory or a
git worktree you intend to delete — the launcher in step 4 points back at this
path, and removing it later leaves a dangling command that fails confusingly.

#### 2. Create a virtual environment

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

#### 3. Install `lmi` into it

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

#### 4. Put the launcher on your PATH

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

#### 5. Verify

```bash
which lmi          # -> /home/you/.local/bin/lmi
lmi --version       # -> lmi 0.1.0
lmi schedule --help
```

If `which lmi` finds nothing, open a new terminal — PATH changes only apply to
shells started afterwards.

---

### Route D — pipx

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
./scripts/install-linux.sh          # re-running is how you upgrade
```

Re-running the script rebuilds the executable and replaces the installed one.
It writes to a temporary name and moves it into place, so an interrupted upgrade
cannot leave a half-written file where a working one was.

By hand:

- **Route B** — repeat its steps 2 to 4.
- **Route C** — `.venv/bin/python -m pip install .`, which you can skip entirely
  if you installed with `--editable`, since the command already tracks your
  checkout.
- **Route D** — `pipx upgrade lmi`, or `pipx reinstall lmi` after pulling.

---

## Uninstalling

```bash
cd ~/lmi
./scripts/install-linux.sh --uninstall
```

That removes the installed command, and `.venv` if a Route C install left one.
The clone stays; delete it too if you want it gone:

```bash
rm -rf ~/lmi
```

The script only removes something it recognises as its own — a symlink into this
clone, or an executable that really contains `lmi/cli.py`. Anything else at that
path it refuses to touch.

By hand: `rm ~/.local/bin/lmi`, plus `rm -rf ~/lmi/.venv` if you used Route C.

With pipx: `pipx uninstall lmi`.

---

## Troubleshooting

**`lmi: command not found`** — the command is missing from `~/.local/bin`, or
that directory is not on PATH, or you have not opened a new terminal. Run the
two PATH checks in Route B step 4.

**`bad interpreter: No such file or directory`** — only affects Route C: the
virtual environment moved or was deleted, and its launcher's shebang holds an
absolute path into it. Re-run the install script, which by default produces a
self-contained executable with no such dependency.

**`/usr/bin/env: 'python3': No such file or directory`** — the executable from
Route A or B cannot find a `python3`. Its shebang is deliberately
`/usr/bin/env python3` rather than a fixed path, so this means `python3` is not
on PATH at all in that context — which is worth knowing if you are running from
cron or a systemd unit, where PATH is minimal.

**`error: externally-managed-environment`** — you are installing outside the
venv. Use `.venv/bin/python -m pip`, not bare `pip`.

**`claude is not on PATH`** — `lmi` found no Claude Code CLI. See "First run".
