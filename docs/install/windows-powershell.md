# Installing `lmi` on Windows (PowerShell)

Goal: type `lmi` in a PowerShell prompt and have it run. No `python -m`, no
activating anything.

Verified on Windows with Python 3.13.14 (Microsoft Store install): a full
`lmi schedule` run completed, wrote its log and state file, and the
single-instance lock correctly refused a second concurrent run.

For `cmd.exe` instead, see [windows-cmd.md](windows-cmd.md).

---

## Before you start

Open **PowerShell** and check:

```powershell
python --version
git --version
```

You need **Python 3.9 or newer**.

**If `python` opens the Microsoft Store**, you have the App Execution Alias stub
and no real Python. Install it from the Store, or from
[python.org](https://www.python.org/downloads/windows/) — ticking
**"Add python.exe to PATH"** if you use the installer.

---

## The one thing that trips people up

`pip install --user .` will appear to succeed and then `lmi` will still be
unrecognised, because a Store Python puts its scripts somewhere that is *not*
on your PATH:

```
$env:LOCALAPPDATA\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts
```

Every route below avoids it. Don't use `pip install --user` for this.

---

## Route A — the install script (recommended)

```powershell
git clone https://github.com/dawnburst/run-claude.git C:\lmi
Set-Location C:\lmi
.\scripts\install-windows.cmd
```

Then open a **new** PowerShell window:

```powershell
lmi --version
```

That is the whole installation.

### Run the .cmd, not the .ps1 — and why

`install-windows.ps1` is the real installer, but calling it directly fails on a
default Windows:

```
install-windows.ps1 cannot be loaded because running scripts is disabled
on this system.
```

That is the execution policy, and it is the out-of-the-box state — I hit it
here. `install-windows.cmd` is a four-line wrapper that invokes the `.ps1` with
`-ExecutionPolicy Bypass` for that **single invocation**, changing no machine
setting. So run the `.cmd` even from PowerShell.

If you would rather not, either of these works instead:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
```

or relax the policy for your account once, which is a real machine change and
your call:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\scripts\install-windows.ps1
```

### What it installs

By default it builds a **single self-contained executable** with the standard
library's `zipapp` module and installs two small files into
`$env:USERPROFILE\.local\bin`:

| File | Why |
|---|---|
| `lmi.pyz` | The whole program, about 44 KB. |
| `lmi.cmd` | A two-line shim. **This is what makes the bare `lmi` work.** |

The shim is not optional. Windows has no association for `.pyz` and does not
list `.PYZ` in `PATHEXT`, so a bare `.\lmi.pyz` does nothing — verified on a
stock install. A `.cmd` is used rather than a `.ps1` shim precisely so that
PowerShell runs it with no execution-policy prompt, and so the same file works
from `cmd` too.

Three consequences:

- **No pip, no setuptools, no wheel, no virtual environment, no network.** It
  works air-gapped, and sidesteps the Store-Python PATH trap entirely.
- **The clone is disposable afterwards** — those two files are the whole program.
- Re-running upgrades; `-Uninstall` reverses it.

### Options

| Option | Meaning |
|---|---|
| `-LinkDir DIR` | Where to put the two files. Default `$env:USERPROFILE\.local\bin`. |
| `-Venv` | Traditional pip install into `.venv` instead. Needs pip, and network unless `setuptools` and `wheel` are already local. Keeps the clone load-bearing. |
| `-Editable` | `pip -e`, so `lmi` tracks your checkout. Implies `-Venv`. |
| `-Uninstall` | Remove both files, and `.venv` if there is one. Leaves the clone. |
| `-Help` | Show usage. |

```powershell
.\scripts\install-windows.cmd -Uninstall
.\scripts\install-windows.cmd -Venv -Editable
.\scripts\install-windows.cmd -LinkDir C:\tools\bin
```

### How it edits PATH, and why not setx

It adds the link directory to your **user** PATH with
`[Environment]::SetEnvironmentVariable(..., 'User')`, and skips the edit if the
entry is already there.

It deliberately does not use `setx`. `setx PATH` expands the *whole* current
PATH — system entries included — into the **user** variable and truncates at
1024 characters, which can quietly corrupt a working PATH.

The change does not affect the window you ran it in. Open a new one.

### If it stops

It fails loudly rather than half-installing. It handles explicitly:

- **`python` opens the Microsoft Store** — the App Execution Alias stub, not
  Python. It says so.
- **Python older than 3.9** — names the requirement and stops.
- **`-Venv` with no network** — says that is expected and points at the default.
- **Something already at the target path it did not install** — refuses to touch
  it. It only removes a `.pyz` that really contains `lmi/cli.py`, or a shim that
  mentions `lmi.pyz`.
- **Run from outside a clone** — says so instead of leaving debris.

To uninstall:

```powershell
Set-Location C:\lmi
.\scripts\install-windows.cmd -Uninstall
```

---

## Manual installation

Route B is what the script does, step by step — use it if the script stopped, if
you want to see each command, or if you would rather not run a script.

---

### Route B — a self-contained executable by hand

Four steps, no pip and no network.

#### 1. Get the source onto the machine

```powershell
git clone https://github.com/dawnburst/run-claude.git C:\lmi
Set-Location C:\lmi
```

Air-gapped: copy the repository across instead. Nothing is fetched from here on.

#### 2. Stage just the package

`zipapp` packs a whole directory, so stage the `lmi` package alone — otherwise
the archive also carries the tests, the docs and any `.venv`.

```powershell
New-Item -ItemType Directory -Force -Path build\stage | Out-Null
Copy-Item -Recurse -Force lmi build\stage\lmi
Get-ChildItem -Recurse -Force -Directory build\stage |
    Where-Object Name -eq '__pycache__' | Remove-Item -Recurse -Force
```

#### 3. Build the executable

```powershell
python -m zipapp build\stage -m "lmi.cli:main" -p "/usr/bin/env python3" -o build\lmi.pyz
python build\lmi.pyz --version
```

`-m` names the entry point, the same `lmi.cli:main` that `pyproject.toml`
declares. `-p` writes a shebang Windows ignores — include it anyway and the same
file also runs directly on Linux and macOS.

**The output must not go inside `build\stage`.** The package being packed is
itself called `lmi`, so writing the archive there collides with it and `zipapp`
fails.

#### 4. Install both files and put them on PATH

```powershell
$bin = "$env:USERPROFILE\.local\bin"
New-Item -ItemType Directory -Force -Path $bin | Out-Null
Copy-Item -Force build\lmi.pyz "$bin\lmi.pyz"

# ASCII with CRLF: cmd.exe is the interpreter and a BOM would be echoed.
[System.IO.File]::WriteAllText("$bin\lmi.cmd",
    "@echo off`r`npython `"%~dp0lmi.pyz`" %*`r`n",
    [System.Text.Encoding]::ASCII)

$p = [Environment]::GetEnvironmentVariable('Path','User')
if ($p -notlike "*$bin*") {
    [Environment]::SetEnvironmentVariable('Path', "$bin;$p", 'User')
}
```

Then open a **new** PowerShell window:

```powershell
Get-Command lmi | Select-Object -ExpandProperty Source
lmi --version
```

To upgrade, repeat steps 2 to 4 after a `git pull`. To uninstall, delete
`lmi.pyz` and `lmi.cmd` from that directory.

---

### Route C — a virtual environment by hand

#### 1. Clone the repository

```powershell
git clone https://github.com/dawnburst/run-claude.git C:\lmi
Set-Location C:\lmi
```

Pick a **permanent** location — the launcher points back at this path.

### 2. Create a virtual environment

```powershell
python -m venv .venv
```

### 3. Install `lmi` into it

```powershell
.\.venv\Scripts\python -m pip install .
```

Use `pip install -e .` if you want the command to track your checkout.

### 4. Confirm it works by full path

```powershell
.\.venv\Scripts\lmi --version
```

Expect `lmi 0.1.0`. If this fails, stop here — the remaining steps only make
this same launcher reachable by name.

### 5. Add a shim directory to your PATH

Create a directory for your own commands, add it to your user PATH, and drop a
one-line shim in it:

```powershell
$bin = "$env:USERPROFILE\.local\bin"
New-Item -ItemType Directory -Force -Path $bin | Out-Null

$user = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($user -notlike "*$bin*") {
    [Environment]::SetEnvironmentVariable('Path', "$bin;$user", 'User')
}

Set-Content -Path "$bin\lmi.cmd" -Encoding ASCII -Value @(
    '@echo off',
    '"C:\lmi\.venv\Scripts\lmi.exe" %*'
)
```

A `.cmd` shim is used rather than a PowerShell script because PowerShell will
run it without any execution-policy prompt, and it works in `cmd` too.

`SetEnvironmentVariable` writes the change permanently but **does not affect the
session you typed it in**.

### 6. Open a NEW PowerShell window and verify

```powershell
Get-Command lmi | Select-Object -ExpandProperty Source
lmi --version
lmi schedule --help
```

A new window is required for the PATH change to take effect.

---

### Route D — pipx

```powershell
python -m pip install --user pipx
python -m pipx ensurepath
```

**Close this window and open a new one**, then:

```powershell
pipx install C:\lmi
lmi --version
```

Or straight from GitHub without cloning:

```powershell
pipx install "git+https://github.com/dawnburst/run-claude.git"
```

---

---

## Do not run from a `\\wsl.localhost\...` path

If your files live in WSL, it is natural to `cd` to them in Windows and run
`lmi` there. **That does not work**, and the reason is not obvious.

`lmi.cmd` goes through `cmd.exe`, and **cmd.exe cannot hold a UNC working
directory**. It says so and silently substitutes `C:\Windows`:

```
'\\wsl.localhost\Ubuntu-24.04\home\you\project'
CMD.EXE was started with the above path as the current directory.
UNC paths are not supported.  Defaulting to Windows directory.
```

Measured: launched through the shim from a UNC directory, Python sees
`C:\Windows` as its working directory. `lmi` then aims its state file, log and
lock at `C:\Windows` and is refused:

```
[ERROR] cannot write to the working directory C:\Windows (Permission denied).
    That is where the state file would go. Pass -d with a directory you can
    write to, for example: lmi schedule "..." -d C:\work
```

`lmi` detects this and stops with that one message rather than failing three
times over. Two ways forward:

- **Pass `-d` with a real drive path**, which is where `claude` will then run:

  ```bat
  lmi schedule "your prompt" -d C:\work
  ```

- **Better, if the files are in WSL: run `lmi` inside WSL.** That is where those
  files live, there is no UNC problem at all, and see
  [linux.md](linux.md) for the install.

The same applies to any mapped network path. A local drive letter is always
safe.

## First run

```powershell
New-Item -ItemType Directory -Force -Path C:\work | Out-Null
Set-Location C:\work
lmi schedule "Create a file named hello.txt containing the single word OK"
"exit=$LASTEXITCODE"
```

Expect `exit=0`, a `hello.txt`, a `run-claude-<timestamp>.log`, and a
`run-claude-state.md` that Claude has actually rewritten. A `run-claude.lock`
sits alongside; that is normal and may persist between runs.

`lmi` needs the Claude Code CLI on your PATH — check `claude --version`. If it
is missing, install it and run `claude auth login` once; `lmi` cannot do the
interactive sign-in, and WSL credentials do not carry over to a Windows install.

### PowerShell quoting

PowerShell parses your line before `lmi` sees it, so quote anything with spaces,
and quote `-t` as a single value:

```powershell
lmi schedule "my prompt" -t "2026-08-05 22:00" -i 30 -c 5
```

If a prompt itself contains double quotes, put it in a file and pass the path —
that is the supported route on every platform:

```powershell
lmi schedule C:\work\task.md -i 30 -c 5
```

Use a **single-quoted** PowerShell string when your prompt contains `$`, so
PowerShell does not expand it as a variable:

```powershell
lmi schedule 'explain what $PATH does'
```

---

## Scheduled (unattended) runs — read this first

Running `lmi` from **Task Scheduler** is **not yet verified**. A Store-installed
Python is reached through a per-user App Execution Alias, and whether that
resolves under "Run whether user is logged on or not" is untested.

If you need scheduled runs today, either point the task at the **full launcher
path** (`C:\lmi\.venv\Scripts\lmi.exe`), which skips PATH resolution entirely,
or use `run-claude.bat` from this repository, which needs only `cmd` and
PowerShell and has no Python dependency.

---

## Updating

```powershell
Set-Location C:\lmi
git pull
.\scripts\install-windows.cmd
```

Re-running rebuilds the executable and replaces the installed one.

By hand: repeat Route B steps 2 to 4; or for Route C,
`.\.venv\Scripts\python -m pip install .`; or `pipx upgrade lmi` for Route D.

---

## Uninstalling

```powershell
Set-Location C:\lmi
.\scripts\install-windows.cmd -Uninstall
Remove-Item -Recurse -Force C:\lmi
```

The script removes only what it recognises as its own — a `.pyz` containing
`lmi/cli.py`, or a shim mentioning `lmi.pyz` — and refuses to touch anything
else at that path.

By hand, delete `lmi.pyz` and `lmi.cmd` from `$env:USERPROFILE\.local\bin`.
With pipx: `pipx uninstall lmi`. The PATH entry can stay harmlessly, or:

```powershell
$bin = "$env:USERPROFILE\.local\bin"
$p = ([Environment]::GetEnvironmentVariable('Path','User') -split ';' |
      Where-Object { $_ -and ($_.TrimEnd('\') -ine $bin.TrimEnd('\')) }) -join ';'
[Environment]::SetEnvironmentVariable('Path', $p, 'User')
```

---

## Troubleshooting

**`lmi : The term 'lmi' is not recognized`** — you are in the window where you
edited PATH. Open a new one. If it persists, run
`[Environment]::GetEnvironmentVariable('Path','User')` and confirm your shim
directory is listed.

**`python` opens the Microsoft Store** — you have the alias stub, not Python.

**`error: externally-managed-environment`** — you are installing outside the
venv. Use `.\.venv\Scripts\python -m pip`.

**`... cannot be loaded because running scripts is disabled`** — the execution
policy. Run `.\scripts\install-windows.cmd` rather than the `.ps1`; the wrapper
passes `-ExecutionPolicy Bypass` for that one invocation. You never need to
activate anything with this setup either.

**`claude is not on PATH`** — see "First run".
