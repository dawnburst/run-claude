# Installing `lmi` on Windows (cmd.exe)

Goal: type `lmi` in a `cmd` window and have it run. No `python -m`, no
activating anything.

Verified on Windows with Python 3.13.14 (Microsoft Store install): a full
`lmi schedule` run completed, wrote its log and state file, and the
single-instance lock correctly refused a second concurrent run.

For PowerShell instead, see [windows-powershell.md](windows-powershell.md).

---

## Before you start

Open **Command Prompt** and check:

```bat
python --version
git --version
```

You need **Python 3.9 or newer**.

**If `python` opens the Microsoft Store**, you have the App Execution Alias
stub and no real Python. Install Python either from the Store, or from
[python.org](https://www.python.org/downloads/windows/) — and if you use the
python.org installer, tick **"Add python.exe to PATH"** on the first screen.

---

## The one thing that trips people up

`pip install --user .` will appear to succeed and then `lmi` will still say
**"'lmi' is not recognized"**. That is because a Store Python puts its scripts
in a directory that is *not* on your PATH:

```
%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts
```

Both routes below avoid that trap. Don't use `pip install --user` for this.

---

## Route A — virtual environment plus a shim (recommended)

Nothing extra to install. Six steps.

### 1. Clone the repository

```bat
cd /d C:\
git clone https://github.com/dawnburst/run-claude.git C:\lmi
cd /d C:\lmi
```

Pick a **permanent** location. The launcher created in step 4 points back at
this path.

### 2. Create a virtual environment

```bat
python -m venv .venv
```

### 3. Install `lmi` into it

```bat
.venv\Scripts\python -m pip install .
```

Use `pip install -e .` instead if you want the command to track your checkout.

### 4. Confirm it works by full path

```bat
.venv\Scripts\lmi --version
```

Expect `lmi 0.1.0`. If this fails, stop here — the later steps only make this
same launcher reachable by name.

### 5. Create a `lmi.bat` shim on your PATH

Make a small directory for your own commands and add it to your PATH once:

```bat
mkdir "%USERPROFILE%\.local\bin" 2>nul
setx PATH "%USERPROFILE%\.local\bin;%PATH%"
```

`setx` writes the change permanently but **does not affect the window you typed
it in**. Then create the shim:

```bat
> "%USERPROFILE%\.local\bin\lmi.bat" echo @echo off
>> "%USERPROFILE%\.local\bin\lmi.bat" echo "C:\lmi\.venv\Scripts\lmi.exe" %%*
```

The `%%*` forwards every argument you type. Inside a `.bat` file it must be
doubled; typed directly at the prompt it would be `%*`.

### 6. Open a NEW Command Prompt and verify

```bat
where lmi
lmi --version
lmi schedule --help
```

`where lmi` should print your shim's path. A new window is required because
`setx` only applies to shells started afterwards.

---

## Route B — pipx

`pipx` isolates each tool and fixes PATH for you.

```bat
python -m pip install --user pipx
python -m pipx ensurepath
```

**Close the window and open a new one**, then:

```bat
pipx install C:\lmi
lmi --version
```

Or straight from GitHub without cloning:

```bat
pipx install "git+https://github.com/dawnburst/run-claude.git"
```

---

## First run

```bat
mkdir C:\work && cd /d C:\work
lmi schedule "Create a file named hello.txt containing the single word OK"
echo exit=%ERRORLEVEL%
```

Expect `exit=0`, a `hello.txt`, a `run-claude-<timestamp>.log`, and a
`run-claude-state.md` that Claude has actually rewritten. A `run-claude.lock`
file sits alongside them; that is normal and it may stay between runs.

`lmi` needs the Claude Code CLI on your PATH. Check with `claude --version`. If
it is missing, install it and run `claude auth login` once in a `cmd` window —
`lmi` cannot perform the interactive sign-in, and WSL credentials do not carry
over to a Windows install.

**Quote arguments containing spaces**, and note that `-t` must be quoted as one
value:

```bat
lmi schedule "my prompt" -t "2026-08-05 22:00" -i 30 -c 5
```

---

## Scheduled (unattended) runs — read this first

Running `lmi` from **Task Scheduler** is **not yet verified**. The risk is
specific: a Store-installed Python is reached through a per-user App Execution
Alias, and whether that resolves under "Run whether user is logged on or not"
is untested.

If you need scheduled runs today, either:

- point the scheduled task at the **full launcher path**
  (`C:\lmi\.venv\Scripts\lmi.exe`) rather than the bare name, since that skips
  PATH resolution entirely; or
- use `run-claude.bat` from this repository, which depends only on `cmd` and
  PowerShell and has no Python dependency at all.

---

## Updating

```bat
cd /d C:\lmi
git pull
.venv\Scripts\python -m pip install .
```

With pipx: `pipx upgrade lmi`.

---

## Uninstalling

```bat
del "%USERPROFILE%\.local\bin\lmi.bat"
rmdir /s /q C:\lmi
```

With pipx: `pipx uninstall lmi`. Remove the PATH entry through
**Settings → System → About → Advanced system settings → Environment
Variables** if you no longer want it.

---

## Troubleshooting

**`'lmi' is not recognized`** — you are in the window where you ran `setx`.
Open a new one. If it still fails, run `where lmi`; if that prints nothing, the
shim is missing or your PATH edit did not apply.

**`python` opens the Microsoft Store** — you have the alias stub, not Python.
See "Before you start".

**`error: externally-managed-environment`** — you are installing outside the
venv. Use `.venv\Scripts\python -m pip`.

**Nothing happens, or a Store page opens, when the shim runs** — check the path
inside `lmi.bat` matches where you actually cloned the repository.

**`claude is not on PATH`** — see "First run".
