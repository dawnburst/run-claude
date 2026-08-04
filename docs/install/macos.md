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

## Route A — the install script (recommended)

```bash
git clone https://github.com/dawnburst/run-claude.git ~/lmi
cd ~/lmi
./scripts/install-macos.sh
```

Then open a new Terminal tab:

```bash
lmi --version       # -> lmi 0.1.0
```

That is the whole installation.

By default the script builds a **single self-contained executable** with the
standard library's `zipapp` module and copies it to `~/.local/bin/lmi`:

- **No pip, no setuptools, no wheel, no virtual environment, no network.** It
  works on an air-gapped machine, and it avoids `sudo pip` entirely — which on
  macOS fights System Integrity Protection and leaves a mess where it partially
  succeeds.
- **The installed file is the whole program**, about 44 KB, so **the clone is
  disposable** afterwards. Delete `~/lmi` and `lmi` keeps working.
- Re-running the script is how you upgrade; `--uninstall` reverses it.

### Options

| Option | Meaning |
|---|---|
| `--zipapp` | Single self-contained executable. **The default.** |
| `--venv` | Traditional pip install into `.venv`. Needs pip, and network unless `setuptools` and `wheel` are already local. Keeps the clone load-bearing. |
| `--editable` | `pip -e`, so `lmi` tracks your checkout. Implies `--venv`. |
| `--link-dir DIR` | Where to put the command. Default `~/.local/bin`. |
| `--uninstall` | Remove the command, and `.venv` if there is one. Leaves the clone. |
| `-h`, `--help` | Show usage. |

### What it does about macOS specifics

- **Finds a usable Python.** It tries `python3` and then each of
  `python3.13` … `python3.9`, taking the first that is 3.9 or newer. If none is
  found it tells you to run `xcode-select --install` or
  `brew install python@3.12`.
- **Writes `#!/usr/bin/env python3`** rather than a fixed interpreter path,
  because Homebrew is at `/opt/homebrew` on Apple silicon and `/usr/local` on
  Intel, and the Command Line Tools `python3` is somewhere else again.
- **Names the right startup file.** zsh has been the macOS default since
  Catalina, so it suggests `~/.zshrc`, falling back to `~/.bash_profile` if your
  shell is bash.
- **Does not use `readlink -f`**, which stock macOS lacked before Monterey. The
  ownership check resolves symlinks with `cd` and `pwd` instead.

### If it stops

It fails loudly rather than half-installing:

- **No Python 3.9+** — names both ways to get one.
- **`--venv` with no network** — says that is expected and points at the default.
- **Something already at the target path it did not install** — refuses to touch
  it. It only removes a symlink into this clone, or an executable that really
  contains `lmi/cli.py`.
- **Run from outside a clone** — says so instead of leaving debris.
- **A different `lmi` earlier on your PATH** — warns and names the winner.

To uninstall:

```bash
cd ~/lmi
./scripts/install-macos.sh --uninstall
```

### Air-gapped machines

Use the default. Nothing is fetched. You only need to carry in two things,
neither of them a Python package: the source (or the built executable, which is
portable and even runs on Linux and Windows), and an already-authenticated
Claude Code CLI — `claude auth login` is browser-based and cannot be automated.

`pip install .` is what fails without a network: `[build-system]` asks for
`setuptools>=61`, which pip fetches from PyPI. `--no-build-isolation` only moves
the requirement to `setuptools` **and** `wheel` being local already.

---

## Manual installation

Route B is what the script does, step by step — use it if the script stopped, if
you want to see each command, or if you would rather not run a script.

---

### Route B — a self-contained executable by hand

Four steps, no pip and no network.

#### 1. Get the source onto the machine

```bash
git clone https://github.com/dawnburst/run-claude.git ~/lmi
cd ~/lmi
```

Air-gapped: copy the repository across instead.

#### 2. Stage just the package

```bash
mkdir -p build/stage
cp -R lmi build/stage/
find build/stage -name '__pycache__' -type d -exec rm -rf {} +
```

#### 3. Build the executable

`zipapp`'s own `-m` flag is deliberately **not** used. The `__main__.py` it
generates calls `main()` and throws the result away, so the process always exits
0 and every code `lmi` defines — 1 a failed claude call, 2 usage, 3 the lock, 4
an internal crash — is lost. Write the entry point yourself:

```bash
cat > build/stage/__main__.py <<'EOF'
import sys

from lmi.cli import main

sys.exit(main())
EOF

python3 -m zipapp build/stage -p "/usr/bin/env python3" -o build/lmi
chmod +x build/lmi
./build/lmi --version
```

**The output must not go inside `build/stage`.** The package is itself called
`lmi`, so writing the archive there collides with it and `zipapp` fails.

#### 4. Put it on your PATH

Copy rather than symlink — the file is the whole program, so copying makes the
clone disposable:

```bash
mkdir -p ~/.local/bin
cp build/lmi ~/.local/bin/lmi
chmod +x ~/.local/bin/lmi
```

Confirm the directory is on your PATH:

```bash
echo "$PATH" | tr ':' '\n' | grep -q "$HOME/.local/bin" && echo on-path || echo MISSING
```

If it prints `MISSING`, add it and open a new Terminal tab. zsh is the macOS
default since Catalina:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Use `~/.bash_profile` if `echo $SHELL` says bash.

To upgrade, repeat steps 2 to 4 after a `git pull`. To uninstall,
`rm ~/.local/bin/lmi`.

---

### Route C — a virtual environment by hand

#### 1. Clone the repository

```bash
git clone https://github.com/dawnburst/run-claude.git ~/lmi
cd ~/lmi
```

Pick a **permanent** location. The launcher in step 4 points back at this path;
moving or deleting the directory later leaves a command that fails confusingly.

#### 2. Create a virtual environment

```bash
python3 -m venv .venv
```

Unlike Debian and Ubuntu, macOS bundles `ensurepip`, so this works without extra
packages.

#### 3. Install `lmi` into it

```bash
.venv/bin/python -m pip install .
```

Use `pip install -e .` instead if you want the command to track your checkout as
you edit it.

Do **not** use `sudo pip` or install into the system Python. Writing into
`/usr/bin`'s Python is blocked by System Integrity Protection and, where it
partially succeeds, produces a broken mix that is unpleasant to unpick.

#### 4. Put the launcher on your PATH

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

#### 5. Verify

```bash
which lmi          # -> /Users/you/.local/bin/lmi
lmi --version       # -> lmi 0.1.0
lmi schedule --help
```

If `which lmi` finds nothing, open a new Terminal tab — PATH changes apply only
to shells started afterwards.

---

### Route D — pipx

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
./scripts/install-macos.sh          # re-running is how you upgrade
```

Re-running rebuilds the executable and replaces the installed one, writing to a
temporary name and moving it so an interrupted upgrade cannot leave a
half-written file where a working one was.

By hand: repeat Route B steps 2 to 4; or for Route C,
`.venv/bin/python -m pip install .`, which you can skip if you used
`--editable`; or `pipx upgrade lmi` for Route D.

---

## Uninstalling

```bash
cd ~/lmi
./scripts/install-macos.sh --uninstall
```

That removes the installed command, and `.venv` if a Route C install left one.
The clone stays; delete it too if you want it gone:

```bash
rm -rf ~/lmi
```

The script only removes what it recognises as its own — a symlink into this
clone, or an executable that really contains `lmi/cli.py`.

By hand: `rm ~/.local/bin/lmi`, plus `rm -rf ~/lmi/.venv` if you used Route C.
With pipx: `pipx uninstall lmi`.

---

## Troubleshooting

**`lmi: command not found`** — the symlink is missing, `~/.local/bin` is not on
PATH, or you have not opened a new Terminal tab. Re-run the checks in step 4.

**`bad interpreter: No such file or directory`** — only affects Route C: the
virtual environment moved or was deleted and its launcher's shebang holds an
absolute path into it. Re-run the install script, whose default produces a
self-contained executable with no such dependency.

**`/usr/bin/env: python3: No such file or directory`** — the executable from
Route A or B cannot find a `python3`. Its shebang is deliberately
`/usr/bin/env python3` rather than a fixed path, so this means `python3` is not
on PATH in that context — worth knowing if you are running from `launchd` or
`cron`, where PATH is minimal. Point those at the full path instead.

**Apple silicon and Homebrew paths** — Homebrew installs to `/opt/homebrew` on
Apple silicon and `/usr/local` on Intel. If `brew` itself is not found, add the
right one to your PATH; this affects Route B only.

**`claude is not on PATH`** — see "First run".
