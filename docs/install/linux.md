# Installing `lmi` on Linux

Goal: type `lmi` and have it run. No `python -m`, no activating anything.

Verified on Ubuntu 24.04 (including WSL2) with Python 3.12 and 3.9.23: install,
re-install as an upgrade, upgrade from the previous zipapp install, uninstall,
and a refusal to overwrite a foreign `lmi`.

[← README](../../README.md) · other platforms: [macOS](macos.md) · [Windows (cmd.exe)](windows-cmd.md) · [Windows (PowerShell)](windows-powershell.md)

---

## What you install

**One file: `lmi-0.1.0-py3-none-any.whl`**, about 22 KB — the same file on every
operating system, because `lmi` is pure Python with no third-party dependencies.
See [the README](../../README.md#getting-started) for what that name means; pip
generates whatever launcher this platform needs from it.

## Before you start

```bash
python3 --version        # need 3.9 or newer
```

Nothing else. In particular you do **not** need pip on the system Python, a
network, or root.

## Getting the files

You need the wheel and the install script. Either:

```bash
git clone https://github.com/dawnburst/run-claude.git ~/lmi
cd ~/lmi
```

or, with no git, download `lmi-0.1.0-py3-none-any.whl` and `install-linux.sh`
into the same folder and run the script from there. It looks for the wheel beside
itself first, precisely so that this works.

---

## Route A — the install script (recommended)

```bash
./scripts/install-linux.sh
```

Then open a new terminal:

```bash
lmi --version       # -> lmi 0.1.0
```

That is the whole installation. It needs no sudo, and re-running it is how you
upgrade.

The script installs the wheel into a virtual environment of its own at
`~/.local/share/lmi/venv`, then symlinks the `lmi` command pip generates into
`~/.local/bin`. The venv holds nothing but `lmi`, so **the clone is disposable**
afterwards. Last, it runs [`lmi config init`](../config.md#lmi-config-init) to
copy the config folder inside the wheel to `~/.lmi`, keeping any file already
there — a warning rather than a failure if that does not work, since everything
above it has already succeeded.

### Options

| Option | Meaning |
|---|---|
| `--wheel PATH` | the wheel to install. Default: the newest `lmi-*.whl` beside the script or in `dist/`, else built from the checkout. |
| `--link-dir DIR` | where to put the command. Default `~/.local/bin`. |
| `--venv-dir DIR` | where to keep the virtual environment. Default `~/.local/share/lmi/venv`. |
| `--uninstall` | remove the command and the virtual environment. |
| `-h`, `--help` | show usage. |

### Why a virtual environment and not `pip install --user`

Because pip refuses. Debian, Ubuntu and most current distributions mark the
system Python **externally managed** (PEP 668), and a `--user` install stops with
"This environment is externally managed", suggesting a venv or pipx. Confirmed on
Ubuntu 24.04. The alternative flag, `--break-system-packages`, does what its name
says. A venv of our own avoids the question entirely.

### What it does about Debian's missing `venv`

Debian and Ubuntu ship the venv module's bootstrap (`ensurepip`) in a separate
package, so `python3 -m venv` fails on a machine that is otherwise perfectly able
to install this wheel. Rather than stopping and telling you to `apt install
python3-venv`, the script falls back to `python3 -m venv --without-pip`, which
needs no `ensurepip`, and populates it using the system pip's `--python` flag.
Verified on Ubuntu 24.04 with `python3-venv` absent — the install completes with
no root and no apt.

If even that is impossible it stops and names the one package to install.

### If it stops

It fails loudly rather than half-installing:

- **No Python 3.9+** — says so and stops.
- **No wheel, and no checkout to build one from** — tells you where to put the
  wheel, or to pass `--wheel`.
- **Something already at the target path it did not install** — refuses to touch
  it. It replaces only its own symlink, or the zipapp the previous version of
  this installer left there.
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

What the script does, in five commands:

```bash
python3 -m venv ~/.local/share/lmi/venv
~/.local/share/lmi/venv/bin/python -m pip install --no-index lmi-0.1.0-py3-none-any.whl
mkdir -p ~/.local/bin
ln -sfn ~/.local/share/lmi/venv/bin/lmi ~/.local/bin/lmi
~/.local/bin/lmi config init
```

The last one copies the config folder inside the wheel to `~/.lmi` — a
`config.json`, the `settings.json` template, the `statusline.js` it declares and
a gateway/direct switch pair. It keeps every file already there, so it is safe
to re-run, and [`lmi config init`](../config.md#lmi-config-init) is how you get
that folder back if it is ever deleted.

Then check `~/.local/bin` is on your PATH:

```bash
echo "$PATH" | tr ':' '\n' | grep -q "$HOME/.local/bin" && echo on-path || echo MISSING
```

If it prints `MISSING`, add it and open a new terminal:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Use `~/.zshrc` if `echo $SHELL` says zsh.

If step 1 fails with "ensurepip is not available", use the fallback the script
uses:

```bash
python3 -m venv --without-pip ~/.local/share/lmi/venv
python3 -m pip --python ~/.local/share/lmi/venv/bin/python install --no-index lmi-0.1.0-py3-none-any.whl
```

`--python` must come before `install`, and needs pip 22.3 or newer.

---

## Route C — pipx

If you already have pipx, it manages the venv and PATH for you:

```bash
pipx install ./lmi-0.1.0-py3-none-any.whl
```

Equivalent result; one more tool to have installed first, which is why it is not
the default.

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
`run-claude-state.md` that Claude has actually rewritten. A `run-claude.lock`
sits alongside them; that is normal.

`lmi` needs the Claude Code CLI on your PATH — check `claude --version`. If it is
missing, install it and run `claude auth login` once; `lmi` cannot perform the
interactive sign-in for you.

---

## Scheduled (unattended) runs

A `cron` or `systemd` job does not inherit your interactive PATH, so give the
full path:

```
~/.local/share/lmi/venv/bin/lmi
```

That launcher's shebang pins the venv's interpreter, so it needs nothing on PATH
to start.

---

## Updating

```bash
cd ~/lmi && git pull
./scripts/install-linux.sh
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
./scripts/install-linux.sh --uninstall
```

Removes the command and the virtual environment. By hand:

```bash
rm ~/.local/bin/lmi
rm -rf ~/.local/share/lmi
```

---

## Troubleshooting

**`lmi: command not found`** — `~/.local/bin` is not on PATH, or you have not
opened a new terminal. Re-run the PATH check in Route B.

**`This environment is externally managed`** — you ran `pip install` against the
system Python instead of the venv. That is PEP 668, and it is what Route A exists
to avoid.

**`ensurepip is not available`** — Debian's split packaging. Route A handles it
automatically; by hand, use the `--without-pip` form above.

**`bad interpreter: No such file or directory`** — the venv moved or was deleted.
Re-run the install script.

**`claude is not on PATH`** — see "First run".
