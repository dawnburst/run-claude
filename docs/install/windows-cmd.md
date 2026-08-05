# Installing `lmi` on Windows (cmd.exe)

Goal: type `lmi` in a `cmd` window and have it run. No `python -m`, no activating
anything.

Verified on Windows with Python 3.13 (Microsoft Store install): install,
uninstall, re-install through this wrapper, cleanup of the previous installer's
files, a full `lmi schedule` run, and a bare `lmi` resolving in a new window.

> Using PowerShell instead? See
> [windows-powershell.md](windows-powershell.md). The installer is the same file;
> only how you launch it differs.

---

## What you install

**One file: `lmi-0.1.0-py3-none-any.whl`**, about 22 KB. The `py3-none-any` in
that name means any Python 3, no compiled ABI, **any operating system** — `lmi`
is pure Python with no third-party dependencies, so the same wheel installs on
Windows, Linux and macOS.

`pip` turns it into a **real `lmi.exe`**. That executable is the point:

- It is a genuine PE binary with the interpreter path built in, so nothing has to
  find `python` on PATH at run time — which is what makes a Scheduled Task
  resolve `lmi` at all.
- There is no `cmd.exe` in the chain. The previous installer shipped a two-line
  `lmi.cmd` shim, and cmd.exe cannot hold a UNC working directory: launched from
  `\\wsl.localhost\...` it silently substitutes `C:\Windows`, so `lmi` aimed its
  state file, log and lock at `C:\Windows` and failed with Permission denied.
  Measured from the same UNC path:

  ```
  direct .exe  ->  \\wsl.localhost\Ubuntu-24.04\home\...     (correct)
  via cmd      ->  C:\Windows                                (the old bug)
  ```

## Before you start

Open a `cmd` window:

```bat
python --version
```

You need **Python 3.9 or newer**. Install it from
[python.org](https://www.python.org/downloads/windows/) and tick **"Add python.exe
to PATH"**.

If typing `python` opens the Microsoft Store, what you have is the App Execution
Alias — a 0-byte placeholder, not an interpreter. Install Python properly. (A real
Store install of Python works fine; that is what this was verified against.)

You do not need administrator rights, and you do not need a network for the
install itself.

## Getting the files

You need the wheel and the installer. **git is not installed on a stock Windows**,
so the likely route is a download: put `lmi-0.1.0-py3-none-any.whl`,
`install-windows.cmd` and `install-windows.ps1` in the same folder. The installer
looks for the wheel beside itself first, precisely so that this works.

With git available:

```bat
git clone -b lmi-schedule https://github.com/dawnburst/run-claude.git C:\lmi
cd /d C:\lmi
```

---

## Route A — the install script (recommended)

```bat
scripts\install-windows.cmd
```

Then open a **new** `cmd` window:

```bat
lmi --version
```

That is the whole installation. No administrator rights, and re-running it is how
you upgrade.

`install-windows.cmd` is a thin wrapper around `install-windows.ps1`, so there is
one implementation rather than two that drift. It passes `-ExecutionPolicy
Bypass` for that one invocation, which changes no machine setting and is what
lets the installer run on a default Windows where the policy would block a local
script.

### Options

Everything is passed straight through to the PowerShell script:

| Option | Meaning |
|---|---|
| `-Wheel PATH` | the wheel to install. Default: the newest `lmi-*.whl` beside the script or in `dist\`, else built from the checkout. |
| `-Uninstall` | remove `lmi` with pip. |
| `-Help` | show usage. |

```bat
scripts\install-windows.cmd -Wheel C:\downloads\lmi-0.1.0-py3-none-any.whl
scripts\install-windows.cmd -Uninstall
```

### What it does

1. Finds a Python 3.9+ — trying `python`, then `python3`, then the `py` launcher,
   and skipping any that fails to report a version (which is how a Store alias
   stub is stepped over rather than tripped on).
2. Refuses to continue inside an active virtual environment, where a `--user`
   install is not allowed, instead of letting pip produce a traceback.
3. Installs the wheel with `pip install --user`.
4. Asks that same Python where its user Scripts directory is, and checks
   `lmi.exe` really arrived there.
5. Deletes `lmi.pyz` and `lmi.cmd` from `%USERPROFILE%\.local\bin` if the previous
   installer left them — otherwise the old shim could shadow the new `.exe` and
   an upgrade would appear to do nothing.
6. Adds that Scripts directory to your **user** PATH if it is missing.
7. Runs the installed `lmi.exe` to prove it works.

### Why `--user`, and why the PATH edit

`--user` needs no administrator rights and puts the command in a directory the
script can compute exactly, rather than depending on whether Python was installed
for one user or for all of them.

The trade-off is that the user Scripts directory is **not** on PATH by default.
That is the trap where `pip install --user` appears to succeed and `lmi` is still
unrecognised — so the script adds the directory. It uses
`SetEnvironmentVariable`, deliberately not `setx`, which folds the whole system
PATH into your user variable and truncates it at 1024 characters.

### Air-gapped machines

Carry in the wheel. Installing it needs no network: the install command passes
`--no-index`, and a wheel needs no build backend. You also need an
already-authenticated Claude Code CLI — `claude auth login` is browser-based and
cannot be automated.

---

## Route B — by hand

Two commands, from the folder holding the wheel:

```bat
python -m pip install --user lmi-0.1.0-py3-none-any.whl
python -c "import sysconfig; print(sysconfig.get_path('scripts', 'nt_user'))"
```

The second prints the folder holding your new `lmi.exe`. Add it to your PATH:

**Settings → System → About → Advanced system settings → Environment
Variables → User variables → Path → New**, paste the folder, OK, then open a new
`cmd` window.

Use `sysconfig`, not `%APPDATA%\Python\PythonXX\Scripts` — the answer differs
between installs. A Microsoft Store Python puts it under
`%LOCALAPPDATA%\Packages\PythonSoftwareFoundation...\LocalCache\local-packages\Python313\Scripts`.

Verify:

```bat
where lmi
lmi --version
```

---

## Route C — pipx

If you already have pipx:

```bat
pipx install lmi-0.1.0-py3-none-any.whl
```

Same result; one more tool to install first, which is why it is not the default.

---

## First run

```bat
mkdir C:\work && cd /d C:\work
lmi schedule "Create a file named hello.txt containing the single word OK"
echo exit=%ERRORLEVEL%
```

Expect `exit=0`, a `hello.txt`, a `run-claude-<timestamp>.log`, and a
`run-claude-state.md` that Claude has actually rewritten. A `run-claude.lock`
sits alongside them; that is normal.

`lmi` needs the Claude Code CLI on your PATH — check `claude --version`. If it is
missing, install it and run `claude auth login` once in a Windows window. WSL
credentials do not carry over to a Windows install.

**Run from a local drive.** See the UNC note under Troubleshooting.

---

## Scheduled (unattended) runs

Point Task Scheduler at the full path of the `.exe`, which the installer printed:

```
C:\Users\<you>\AppData\Roaming\Python\Python313\Scripts\lmi.exe
```

The `.exe` carries its interpreter path internally, so it does not depend on PATH
being set up inside the task's environment — the main reason this install route
was chosen. Set "Start in" to your working directory.

Credentials are per-user: the task must run as the user who did
`claude auth login`.

> Not yet verified. A Scheduled Task run has not been tested end to end. The
> `.exe` removes two of the three things that could go wrong (no `python` lookup,
> no `cmd.exe`), but that is reasoning, not a measurement.

---

## Updating

```bat
scripts\install-windows.cmd
```

Re-running is the upgrade. It uses `--force-reinstall` on purpose: the version
number does not change on every source change, and without it pip treats
reinstalling 0.1.0 over 0.1.0 as nothing to do, so an "upgrade" would silently
keep the old code.

---

## Uninstalling

```bat
scripts\install-windows.cmd -Uninstall
```

Or by hand: `python -m pip uninstall lmi`.

Your PATH is left alone on purpose — that Scripts directory is shared with every
other tool you install with `pip --user`, so removing it could break them.

---

## Troubleshooting

**`'lmi' is not recognized`** — open a **new** window. PATH changes do not reach
windows that were already open. If a new window still fails, run
`python -c "import sysconfig; print(sysconfig.get_path('scripts','nt_user'))"` and
check that folder is in your user Path.

**`UNC paths are not supported. Defaulting to Windows directory.`** — you started
`cmd` in a `\\wsl.localhost\...` folder. cmd.exe cannot hold a UNC working
directory. The installed `.exe` is immune to this, but `cmd` itself still is not,
so anything you type in that window runs from `C:\Windows`. Work from a local
drive, or map the share to a drive letter with `net use`.

**`the working directory is on a network share (UNC path)`** — by design.
The lock file goes beside the state file, and Windows cannot lock a file on a
share: the call fails with "Invalid argument", which is indistinguishable from
another run holding the lock. Before this was refused outright it surfaced as a
phantom exit 3, "another run is working on this state file", with nothing else
running.

The restriction is only on the state file, so you can keep working on the share:

```
lmi schedule "..." -s C:\lmi\run-claude-state.md
```

That puts the state file and its lock on a local drive; the log still goes to the
working directory. Verified: exit 0, with the working directory still the UNC
path.

**`the state file is on a network share (UNC path)`** — the same rule reached
through an explicit `-s`. Point it at a local drive.

**`This environment is externally managed`** — you are pointing at a distribution
Python, probably inside WSL rather than Windows. Use the WSL guide there
([linux.md](linux.md)).

**`ERROR: Can not perform a '--user' install`** — you are inside an activated
virtual environment. Run `deactivate` first. The install script catches this and
says so.

**`claude is not on PATH`** — see "First run".
