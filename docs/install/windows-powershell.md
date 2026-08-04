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

Both routes below avoid that. Don't use `pip install --user` for this.

---

## Route A — virtual environment plus a PATH entry (recommended)

Nothing extra to install. Six steps.

### 1. Clone the repository

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

## Route B — pipx

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
.\.venv\Scripts\python -m pip install .
```

With pipx: `pipx upgrade lmi`.

---

## Uninstalling

```powershell
Remove-Item "$env:USERPROFILE\.local\bin\lmi.cmd"
Remove-Item -Recurse -Force C:\lmi
```

With pipx: `pipx uninstall lmi`. Remove the PATH entry with
`[Environment]::SetEnvironmentVariable('Path', <value without the entry>, 'User')`
or through the Environment Variables dialog.

---

## Troubleshooting

**`lmi : The term 'lmi' is not recognized`** — you are in the window where you
edited PATH. Open a new one. If it persists, run
`[Environment]::GetEnvironmentVariable('Path','User')` and confirm your shim
directory is listed.

**`python` opens the Microsoft Store** — you have the alias stub, not Python.

**`error: externally-managed-environment`** — you are installing outside the
venv. Use `.\.venv\Scripts\python -m pip`.

**`... cannot be loaded because running scripts is disabled`** — you tried
`Activate.ps1`. You do not need to activate anything with this setup; use the
shim, or call the launcher by full path.

**`claude is not on PATH`** — see "First run".
