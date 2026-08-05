# Installing `lmi` on Windows (PowerShell)

Goal: type `lmi` at a PowerShell prompt and have it run. No `python -m`, no
activating anything.

Verified on Windows with Python 3.13 (Microsoft Store install): install,
uninstall, re-install, cleanup of the previous installer's files, exit codes
coming back correctly through the `.exe`, a full `lmi schedule` run, and a bare
`lmi` resolving in a new window.

> Using `cmd.exe` instead? See [windows-cmd.md](windows-cmd.md). The installer is
> the same file; only how you launch it differs.

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

```powershell
python --version
```

You need **Python 3.9 or newer**. Install it from
[python.org](https://www.python.org/downloads/windows/) and tick **"Add python.exe
to PATH"**.

If typing `python` opens the Microsoft Store, what you have is the App Execution
Alias — a 0-byte placeholder, not an interpreter. Install Python properly. (A real
Store install works fine; that is what this was verified against.)

No administrator rights are needed, and the install itself needs no network.

## Getting the files

You need the wheel and the installer. **git is not installed on a stock Windows**,
so the likely route is a download: put `lmi-0.1.0-py3-none-any.whl` and
`install-windows.ps1` in the same folder. The installer looks for the wheel beside
itself first, precisely so that this works.

With git available:

```powershell
git clone https://github.com/dawnburst/run-claude.git C:\lmi
Set-Location C:\lmi
```

---

## Route A — the install script (recommended)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
```

Then open a **new** PowerShell window:

```powershell
lmi --version
```

That is the whole installation. No administrator rights, and re-running it is how
you upgrade.

### Why not just `.\scripts\install-windows.ps1`

You can, if your execution policy allows it. On a default Windows it does not, and
you get:

```
.\install-windows.ps1 cannot be loaded because running scripts is disabled on
this system.
```

The command above is the fix, and it is the *right* fix: `-ExecutionPolicy Bypass`
applies to that one invocation only. It changes no machine setting and needs no
administrator rights, unlike `Set-ExecutionPolicy RemoteSigned`, which changes
the policy for everything you ever run.

If the file came from a browser, Windows may also have marked it blocked. Clear
that with:

```powershell
Unblock-File .\scripts\install-windows.ps1
```

### Options

| Option | Meaning |
|---|---|
| `-Wheel PATH` | the wheel to install. Default: the newest `lmi-*.whl` beside the script or in `dist\`, else built from the checkout. |
| `-Uninstall` | remove `lmi` with pip. |
| `-Help` | show usage. |

```powershell
.\scripts\install-windows.ps1 -Wheel C:\downloads\lmi-0.1.0-py3-none-any.whl
.\scripts\install-windows.ps1 -Uninstall
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
5. Deletes `lmi.pyz` and `lmi.cmd` from `$env:USERPROFILE\.local\bin` if the
   previous installer left them — otherwise the old shim could shadow the new
   `.exe` and an upgrade would appear to do nothing.
6. Adds that Scripts directory to your **user** PATH if it is missing, with
   `[Environment]::SetEnvironmentVariable`. Deliberately not `setx`, which folds
   the whole system PATH into your user variable and truncates it at 1024
   characters.
7. Runs the installed `lmi.exe` to prove it works.

### Why `--user`

It needs no administrator rights and puts the command in a directory the script
can compute exactly, rather than depending on whether Python was installed for one
user or for all of them. The trade-off is that the user Scripts directory is not
on PATH by default — the trap where `pip install --user` appears to succeed and
`lmi` is still unrecognised — so the script adds it.

### Air-gapped machines

Carry in the wheel. Installing it needs no network: the install command passes
`--no-index`, and a wheel needs no build backend. You also need an
already-authenticated Claude Code CLI — `claude auth login` is browser-based and
cannot be automated.

---

## Route B — by hand

```powershell
python -m pip install --user .\lmi-0.1.0-py3-none-any.whl
$scripts = python -c "import sysconfig; print(sysconfig.get_path('scripts','nt_user'))"
$scripts
```

`$scripts` now holds the folder containing your new `lmi.exe`. Add it to your user
PATH and open a new window:

```powershell
$user = [Environment]::GetEnvironmentVariable('Path','User')
[Environment]::SetEnvironmentVariable('Path', "$scripts;$user", 'User')
```

Use `sysconfig`, not `$env:APPDATA\Python\PythonXX\Scripts` — the answer differs
between installs. A Microsoft Store Python puts it under
`$env:LOCALAPPDATA\Packages\PythonSoftwareFoundation...\LocalCache\local-packages\Python313\Scripts`.

Verify in a new window:

```powershell
(Get-Command lmi).Source
lmi --version
```

---

## Route C — pipx

If you already have pipx:

```powershell
pipx install .\lmi-0.1.0-py3-none-any.whl
```

Same result; one more tool to install first, which is why it is not the default.

---

## First run

```powershell
New-Item -ItemType Directory -Force C:\work | Out-Null
Set-Location C:\work
lmi schedule "Create a file named hello.txt containing the single word OK"
$LASTEXITCODE
```

Expect `0`, a `hello.txt`, a `run-claude-<timestamp>.log`, and a
`run-claude-state.md` that Claude has actually rewritten. A `run-claude.lock` sits
alongside them; that is normal.

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

```powershell
.\scripts\install-windows.ps1
```

Re-running is the upgrade. It uses `--force-reinstall` on purpose: the version
number does not change on every source change, and without it pip treats
reinstalling 0.1.0 over 0.1.0 as nothing to do, so an "upgrade" would silently
keep the old code.

---

## Uninstalling

```powershell
.\scripts\install-windows.ps1 -Uninstall
```

Or by hand: `python -m pip uninstall lmi`.

Your PATH is left alone on purpose — that Scripts directory is shared with every
other tool you install with `pip --user`, so removing it could break them.

---

## Troubleshooting

**`The term 'lmi' is not recognized`** — open a **new** window. PATH changes do
not reach windows that were already open. If a new window still fails:

```powershell
python -c "import sysconfig; print(sysconfig.get_path('scripts','nt_user'))"
([Environment]::GetEnvironmentVariable('Path','User')) -split ';'
```

The first path should appear in the second list.

**`running scripts is disabled on this system`** — see "Why not just
`.\scripts\install-windows.ps1`" above.

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
