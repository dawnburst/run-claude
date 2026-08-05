# Installing `lmi` on macOS

Goal: type `lmi` and have it run. No `python3 -m`, no activating anything.

> **Not yet verified on macOS.** Every step below is standard macOS practice, and
> the install script is a close mirror of the Linux one, which is exercised end to
> end — its shared logic was also run on Linux to check it works. But nothing here
> has executed on a Mac. Treat it as intended rather than proven, and please
> report what breaks. Linux and Windows have both been verified.

---

## What you install

**One file: `lmi-0.1.0-py3-none-any.whl`**, about 22 KB. That name is the whole
compatibility story:

| Part | Means |
|---|---|
| `py3` | any Python 3 (the floor, 3.9, is enforced separately) |
| `none` | no compiled ABI |
| `any` | **any operating system** |

`lmi` is pure Python with no third-party dependencies, so the same wheel installs
on macOS, Linux and Windows — Apple silicon and Intel alike, since there is
nothing compiled to match.

## Before you start

Open **Terminal**:

```bash
python3 --version        # need 3.9 or newer
```

macOS ships `python3` with the Xcode Command Line Tools; recent versions provide
3.9.x, which is exactly the floor `lmi` supports. If the command offers to install
the Command Line Tools, accept, or run:

```bash
xcode-select --install
```

If you would rather not use the system Python, `brew install python@3.12` and the
script will find it.

## Getting the files

You need the wheel and the install script. Either:

```bash
git clone https://github.com/dawnburst/run-claude.git ~/lmi
cd ~/lmi
```

or, with no git, download `lmi-0.1.0-py3-none-any.whl` and `install-macos.sh` into
the same folder and run the script from there. It looks for the wheel beside
itself first, precisely so that this works.

---

## Route A — the install script (recommended)

```bash
./scripts/install-macos.sh
```

Then open a new Terminal tab:

```bash
lmi --version       # -> lmi 0.1.0
```

That is the whole installation. It needs no sudo, and re-running it is how you
upgrade.

The script installs the wheel into a virtual environment of its own at
`~/.local/share/lmi/venv`, then symlinks the `lmi` command pip generates into
`~/.local/bin`. The venv holds nothing but `lmi`, so **the clone is disposable**
afterwards.

### Options

| Option | Meaning |
|---|---|
| `--wheel PATH` | the wheel to install. Default: the newest `lmi-*.whl` beside the script or in `dist/`, else built from the checkout. |
| `--link-dir DIR` | where to put the command. Default `~/.local/bin`. |
| `--venv-dir DIR` | where to keep the virtual environment. Default `~/.local/share/lmi/venv`. |
| `--uninstall` | remove the command and the virtual environment. |
| `-h`, `--help` | show usage. |

### Why a virtual environment and not `pip install --user`

Writing into the system Python is blocked by System Integrity Protection, and
where a `sudo pip` partially succeeds it leaves a mix that is unpleasant to
unpick. A Homebrew Python refuses too, being marked **externally managed** (PEP
668). A venv of our own avoids the whole question — and needs no sudo.

### What it does about macOS specifics

- **Finds a usable Python.** It tries `python3`, then each of `python3.13` …
  `python3.9`, taking the first that is 3.9 or newer and actually reports a
  version. The explicit names matter here: a bare `python3` may be the Command
  Line Tools stub that only offers to install itself, while a Homebrew
  `python3.12` is already present and works.
- **Does not use `readlink -f`**, which stock macOS lacked before Monterey. The
  ownership check resolves the symlink with plain `readlink`.
- **Names the right startup file.** zsh has been the macOS default since Catalina,
  so it suggests `~/.zshrc`, falling back to `~/.bash_profile` if `$SHELL` says
  bash.
- **Uses bash 3.2 syntax only**, because that is still what `/bin/bash` is on
  macOS.

### If it stops

It fails loudly rather than half-installing:

- **No Python 3.9+** — names both ways to get one, `xcode-select --install` and
  Homebrew.
- **No wheel, and no checkout to build one from** — tells you where to put the
  wheel, or to pass `--wheel`.
- **Something already at the target path it did not install** — refuses to touch
  it. It replaces only its own symlink, or the zipapp the previous version of this
  installer left there.
- **`~/.local/bin` is not on your PATH** — installs anyway, then prints the exact
  line to add.
- **A different `lmi` earlier on your PATH** — warns and names the winner.

### Air-gapped machines

Carry in the wheel. Installing it needs no network: the install command passes
`--no-index`, and a wheel needs no build backend — that is the difference between
installing a wheel and installing from source, where pip fetches
`setuptools>=61`.

The only other thing you need is an already-authenticated Claude Code CLI;
`claude auth login` is browser-based and cannot be automated.

---

## Route B — by hand

What the script does, in four commands:

```bash
python3 -m venv ~/.local/share/lmi/venv
~/.local/share/lmi/venv/bin/python -m pip install --no-index lmi-0.1.0-py3-none-any.whl
mkdir -p ~/.local/bin
ln -sfn ~/.local/share/lmi/venv/bin/lmi ~/.local/bin/lmi
```

Unlike Debian and Ubuntu, macOS bundles `ensurepip`, so step 1 works with no extra
packages.

Then check `~/.local/bin` is on your PATH:

```bash
echo "$PATH" | tr ':' '\n' | grep -q "$HOME/.local/bin" && echo on-path || echo MISSING
```

If it prints `MISSING`, add it and open a new Terminal tab:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Use `~/.bash_profile` if `echo $SHELL` says bash.

Do **not** use `sudo pip` or install into the system Python; see above.

---

## Route C — pipx

```bash
brew install pipx
pipx ensurepath
# open a new Terminal tab, then:
pipx install ./lmi-0.1.0-py3-none-any.whl
```

pipx manages the venv and PATH for you. Equivalent result; one more tool to have
installed first, which is why it is not the default.

---

## Building the wheel yourself

Only needed if you are changing `lmi`. From a checkout:

```bash
python3 -m pip wheel --no-deps -w dist .
```

That writes `dist/lmi-0.1.0-py3-none-any.whl`. This step wants a network, because
pip fetches `setuptools` to build with — which is why the built wheel, not the
source, is what you carry to an air-gapped machine.

---

## First run

```bash
mkdir -p ~/work && cd ~/work
lmi schedule "Create a file named hello.txt containing the single word OK"
```

Expect exit 0, a `hello.txt`, a `run-claude-<timestamp>.log`, and a
`run-claude-state.md` that Claude has actually rewritten. A `run-claude.lock` sits
alongside them; that is normal.

`lmi` needs the Claude Code CLI on your PATH — check `claude --version`. If it is
missing, install it and run `claude auth login` once; `lmi` cannot perform the
interactive sign-in for you.

---

## Scheduled (unattended) runs

For a recurring job, `launchd` is the macOS equivalent of cron and survives
reboots. A `launchd` job does not inherit your interactive PATH, so give the full
path:

```
/Users/<you>/.local/share/lmi/venv/bin/lmi
```

That launcher's shebang pins the venv's interpreter, so it needs nothing on PATH
to start. The same applies to a `crontab` entry. Untested on macOS, like the rest
of this guide.

---

## Updating

```bash
cd ~/lmi && git pull
./scripts/install-macos.sh
```

Re-running is the upgrade. The install uses `--force-reinstall` on purpose: the
version number does not change on every source change, and without it pip treats
reinstalling 0.1.0 over 0.1.0 as nothing to do, so an "upgrade" would silently
keep the old code.

Upgrading from the previous zipapp-based installer needs no special step — the
script recognises the zipapp it used to leave at `~/.local/bin/lmi` and replaces
it.

---

## Uninstalling

```bash
./scripts/install-macos.sh --uninstall
```

Removes the command and the virtual environment. By hand:

```bash
rm ~/.local/bin/lmi
rm -rf ~/.local/share/lmi
```

With pipx: `pipx uninstall lmi`.

---

## Troubleshooting

**`lmi: command not found`** — `~/.local/bin` is not on PATH, or you have not
opened a new Terminal tab. Re-run the PATH check in Route B.

**`This environment is externally managed`** — you ran `pip install` against a
Homebrew Python instead of the venv. That is PEP 668, and it is what Route A
exists to avoid.

**`bad interpreter: No such file or directory`** — the venv moved or was deleted,
and the launcher's shebang holds an absolute path into it. Re-run the install
script.

**Apple silicon and Homebrew paths** — Homebrew installs to `/opt/homebrew` on
Apple silicon and `/usr/local` on Intel. If `brew` itself is not found, add the
right one to your PATH. This affects only which Python the script finds; the wheel
itself is architecture-independent.

**`claude is not on PATH`** — see "First run".
