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

Every route below avoids it. Don't use `pip install --user` for this.

---

## Route A — the install script (recommended)

```bat
cd /d C:\
git clone https://github.com/dawnburst/run-claude.git C:\lmi
cd /d C:\lmi
scripts\install-windows.cmd
```

Then open a **new** Command Prompt:

```bat
lmi --version
```

That is the whole installation.

By default the script builds a **single self-contained executable** with the
standard library's `zipapp` module and installs two small files into
`%USERPROFILE%\.local\bin`:

| File | Why |
|---|---|
| `lmi.pyz` | The whole program, about 44 KB. |
| `lmi.cmd` | A two-line shim. **This is what makes the bare `lmi` work.** |

The shim is not optional. Windows has no file association for `.pyz` and does
not list `.PYZ` in `PATHEXT`, so a bare `lmi.pyz` does nothing at all — verified
on a stock install. The shim calls `python "%~dp0lmi.pyz" %*`, and `%~dp0` means
it finds its `.pyz` sibling wherever you put the pair.

Three things follow from this design:

- **It needs no pip, no setuptools, no wheel, no virtual environment and no
  network.** It therefore works on an air-gapped machine, and it sidesteps the
  trap below entirely.
- **The clone is disposable afterwards.** Those two files are the whole program.
- Re-running the script upgrades; `-Uninstall` reverses it.

### Options

Everything is passed straight through to the PowerShell installer:

| Option | Meaning |
|---|---|
| `-LinkDir DIR` | Where to put the two files. Default `%USERPROFILE%\.local\bin`. |
| `-Venv` | Traditional pip install into `.venv` instead. Needs pip, and network unless `setuptools` and `wheel` are already local. Keeps the clone load-bearing. |
| `-Editable` | `pip -e`, so `lmi` tracks your checkout. Implies `-Venv`. |
| `-Uninstall` | Remove both files, and `.venv` if there is one. Leaves the clone. |
| `-Help` | Show usage. |

```bat
scripts\install-windows.cmd -Uninstall
scripts\install-windows.cmd -Venv -Editable
scripts\install-windows.cmd -LinkDir C:\tools\bin
```

### Why the `.cmd` is a wrapper

`install-windows.cmd` is four useful lines around `install-windows.ps1`. The
logic lives in PowerShell for two concrete reasons, not preference:

- **PATH safety.** `setx PATH` expands the *whole* current PATH — system entries
  included — into the **user** variable, and truncates at 1024 characters, which
  can quietly corrupt a working PATH. PowerShell's `SetEnvironmentVariable`
  touches only the user scope and has no such limit.
- **One implementation.** Two installers in two languages would have to be kept
  in step by hand.

The wrapper passes `-ExecutionPolicy Bypass` for that single invocation, which
changes no machine setting. It is also why you should run the `.cmd` rather than
the `.ps1` directly from cmd.

### If it stops

It fails loudly rather than half-installing. It handles explicitly:

- **`python` opens the Microsoft Store** — you have the App Execution Alias stub,
  not Python. It says so.
- **Python older than 3.9** — names the requirement and stops.
- **`-Venv` with no network** — says that is expected and points at the default.
- **Something already at the target path it did not install** — refuses to touch
  it. It only removes a `.pyz` that really contains `lmi/cli.py`, or a shim that
  mentions `lmi.pyz`.
- **Run from outside a clone** — says so instead of leaving debris.

To uninstall:

```bat
cd /d C:\lmi
scripts\install-windows.cmd -Uninstall
```

---

## Manual installation

Route B is what the script does, step by step — use it if the script stopped, if
you want to see each command, or if you would rather not run a script.

---

### Route B — a self-contained executable by hand

Four steps, no pip and no network.

#### 1. Get the source onto the machine

```bat
git clone https://github.com/dawnburst/run-claude.git C:\lmi
cd /d C:\lmi
```

Air-gapped: copy the repository across instead. Nothing is fetched from here on.

#### 2. Stage just the package

`zipapp` packs a whole directory, so stage the `lmi` package alone — otherwise
the archive also carries the tests, the docs and any `.venv`.

```bat
mkdir build\stage
xcopy /e /i /q lmi build\stage\lmi
```

#### 3. Build the executable

```bat
python -m zipapp build\stage -m "lmi.cli:main" -p "/usr/bin/env python3" -o build\lmi.pyz
```

`-m` names the entry point, the same `lmi.cli:main` that `pyproject.toml`
declares. `-p` writes a shebang that Windows ignores — include it anyway and the
same file also runs directly on Linux and macOS.

**The output must not go inside `build\stage`.** The package being packed is
itself called `lmi`, so writing the archive there collides with it and `zipapp`
fails.

Check it:

```bat
python build\lmi.pyz --version
```

#### 4. Install both files and put them on PATH

```bat
mkdir "%USERPROFILE%\.local\bin" 2>nul
copy /y build\lmi.pyz "%USERPROFILE%\.local\bin\lmi.pyz"
> "%USERPROFILE%\.local\bin\lmi.cmd" echo @echo off
>> "%USERPROFILE%\.local\bin\lmi.cmd" echo python "%%~dp0lmi.pyz" %%*
```

The `%%` doubling is required inside a `.bat`; typed straight at the prompt it
would be `%~dp0` and `%*`.

Add the directory to your PATH **once**, preferring PowerShell over `setx` for
the reason given above:

```bat
powershell -NoProfile -Command "$b='%USERPROFILE%\.local\bin'; $p=[Environment]::GetEnvironmentVariable('Path','User'); if ($p -notlike \"*$b*\") { [Environment]::SetEnvironmentVariable('Path', \"$b;$p\", 'User') }"
```

Then open a **new** Command Prompt:

```bat
where lmi
lmi --version
```

To upgrade, repeat steps 2 to 4 after a `git pull`. To uninstall, delete
`lmi.pyz` and `lmi.cmd` from that directory.

---

### Route C — a virtual environment by hand

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

### Route D — pipx

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
scripts\install-windows.cmd
```

Re-running rebuilds the executable and replaces the installed one.

By hand: repeat Route B steps 2 to 4; or for Route C,
`.venv\Scripts\python -m pip install .`; or `pipx upgrade lmi` for Route D.

---

## Uninstalling

```bat
cd /d C:\lmi
scripts\install-windows.cmd -Uninstall
rmdir /s /q C:\lmi
```

The script removes only what it recognises as its own — a `.pyz` containing
`lmi/cli.py`, or a shim mentioning `lmi.pyz` — and refuses to touch anything
else at that path.

By hand: delete `lmi.pyz` and `lmi.cmd` from `%USERPROFILE%\.local\bin`.
With pipx: `pipx uninstall lmi`. The PATH entry can stay harmlessly, or be
removed through **Settings → System → About → Advanced system settings →
Environment Variables**.

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
