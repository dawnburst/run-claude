<#
Install the `lmi` CLI on Windows so that typing `lmi` works, in both cmd.exe and
PowerShell.

    .\scripts\install-windows.ps1

By default it builds a single self-contained executable with the standard
library's zipapp module and installs it with a two-line .cmd shim beside it.
That needs no pip, no setuptools, no wheel, no virtual environment and no
network - so it works on an air-gapped machine, and it sidesteps the trap that a
Microsoft Store Python's script directory is not on PATH, which makes
`pip install --user` appear to succeed while `lmi` stays unrecognised.

Why a .cmd shim rather than the .pyz alone: Windows has no association for .pyz
and does not list .PYZ in PATHEXT, so a bare `lmi.pyz` does nothing. The shim
is what makes `lmi` work as a plain command in both shells.

Pass -Venv for the traditional pip install instead; that is the right choice if
you intend to edit the source, since -Editable needs it.

This is the real installer. install-windows.cmd is a thin wrapper that calls it,
so there is one implementation rather than two that must be kept in step.
PowerShell also owns the PATH edit for a concrete reason: `setx PATH` expands the
whole current PATH into the *user* variable and truncates at 1024 characters,
which can quietly corrupt a long PATH. SetEnvironmentVariable touches only the
user scope and has no such limit.
#>
[CmdletBinding()]
param(
    [string] $LinkDir = "$env:USERPROFILE\.local\bin",
    [switch] $Venv,
    [switch] $Editable,
    [switch] $Uninstall,
    [switch] $Help
)

$ErrorActionPreference = 'Stop'
$MinPy = [Version]'3.9'

function Step($m) { Write-Host "==> " -ForegroundColor White -NoNewline; Write-Host $m }
function Ok($m)   { Write-Host "    ok " -ForegroundColor Green -NoNewline; Write-Host $m }
function Warn($m) { Write-Host "    warning " -ForegroundColor Yellow -NoNewline; Write-Host $m }
function Die($m)  { Write-Host ""; Write-Host "error " -ForegroundColor Red -NoNewline; Write-Host $m; exit 1 }

if ($Help) {
    @'
Install the lmi CLI on Windows.

    .\scripts\install-windows.ps1 [options]

Options:
  -LinkDir DIR   where to put the command (default: %USERPROFILE%\.local\bin)
  -Venv          install into a virtual environment with pip instead.
                 Needs pip, and network unless setuptools and wheel are local.
  -Editable      install in editable mode so lmi tracks this checkout.
                 Implies -Venv.
  -Uninstall     remove the installed command, and .venv if there is one
  -Help          show this help

Run it from inside a clone of the repository. It needs no administrator rights.
'@ | Write-Host
    exit 0
}

if ($Editable) { $Venv = $true }

# --- locate the clone we live in -------------------------------------------
$Repo    = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$VenvDir = Join-Path $Repo '.venv'
$Pyz     = Join-Path $LinkDir 'lmi.pyz'
$Shim    = Join-Path $LinkDir 'lmi.cmd'

if (-not (Test-Path (Join-Path $Repo 'pyproject.toml'))) {
    Die "$Repo does not look like the repository (no pyproject.toml).
    Run this from inside a clone, as .\scripts\install-windows.ps1"
}
if (-not (Test-Path (Join-Path $Repo 'lmi'))) { Die "$Repo has no lmi\ package directory." }

# Only ever remove something we installed: a zipapp that really contains
# lmi/cli.py, or a shim that mentions lmi.pyz.
function Test-OurPyz([string] $Path) {
    if (-not (Test-Path $Path)) { return $false }
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop
        $zip = [System.IO.Compression.ZipFile]::OpenRead($Path)
        try   { return [bool]($zip.Entries | Where-Object { $_.FullName -eq 'lmi/cli.py' }) }
        finally { $zip.Dispose() }
    } catch { return $false }
}
function Test-OurShim([string] $Path) {
    if (-not (Test-Path $Path)) { return $false }
    return (Get-Content -Raw -LiteralPath $Path) -match 'lmi\.pyz'
}

# --- uninstall -------------------------------------------------------------
if ($Uninstall) {
    Step "Removing the lmi command"
    foreach ($pair in @(@{P=$Shim; Check={Test-OurShim $Shim}}, @{P=$Pyz; Check={Test-OurPyz $Pyz}})) {
        if (-not (Test-Path $pair.P)) { Ok "nothing at $($pair.P)" }
        elseif (& $pair.Check)        { Remove-Item -Force $pair.P; Ok "removed $($pair.P)" }
        else { Die "$($pair.P) was not installed by this script - leaving it alone.
    Remove it yourself if you are sure, or use -LinkDir." }
    }
    Step "Removing the virtual environment, if there is one"
    if (Test-Path $VenvDir) { Remove-Item -Recurse -Force $VenvDir; Ok "removed $VenvDir" }
    else { Ok "none" }
    Write-Host ""
    Write-Host "Uninstalled." -ForegroundColor White -NoNewline
    Write-Host " The clone itself is untouched; delete $Repo to remove it too."
    exit 0
}

# --- 1. Python -------------------------------------------------------------
Step "Checking Python"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) {
    Die "python is not on PATH. Install Python $MinPy or newer.
    If typing python opens the Microsoft Store you have the App Execution Alias
    stub rather than Python itself - install it from the Store, or from
    python.org ticking 'Add python.exe to PATH'."
}
$PyExe = $py.Source
$verText = (& $PyExe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>&1) | Select-Object -Last 1
try { $ver = [Version]$verText } catch { Die "could not read the Python version (got '$verText')." }
if ($ver -lt $MinPy) { Die "Python $ver is too old; $MinPy or newer is required." }
Ok "python is $ver at $PyExe"

# --- 2. build or install ---------------------------------------------------
if (-not $Venv) {
    Step "Building a self-contained executable"
    $work  = Join-Path ([System.IO.Path]::GetTempPath()) ("lmi-build-" + [guid]::NewGuid().ToString('N'))
    # The staged package and the built file must not share a directory: the
    # package is itself named lmi, so writing the archive into the staging
    # directory collides with it and zipapp fails.
    $stage = Join-Path $work 'stage'
    $built = Join-Path $work 'lmi.pyz'
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    try {
        Copy-Item -Recurse (Join-Path $Repo 'lmi') $stage
        Get-ChildItem -Recurse -Force -Directory $stage |
            Where-Object { $_.Name -eq '__pycache__' } |
            Remove-Item -Recurse -Force
        # The shebang is written for portability - Windows ignores it, and the
        # same file then also runs directly on Linux and macOS.
        & $PyExe -m zipapp $stage -m 'lmi.cli:main' -p '/usr/bin/env python3' -o $built
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $built)) { Die "zipapp failed to build the executable." }
        $builtVer = (& $PyExe $built --version 2>&1) | Select-Object -Last 1
        if ($LASTEXITCODE -ne 0) { Die "the built executable does not run: $builtVer" }
        $kb = [int]((Get-Item $built).Length / 1KB)
        Ok "built ${kb}K - $builtVer"

        Step "Installing it onto your PATH"
        New-Item -ItemType Directory -Force -Path $LinkDir | Out-Null
        if ((Test-Path $Pyz)  -and -not (Test-OurPyz  $Pyz))  { Die "$Pyz already exists and was not installed by this script.`n    Move it aside, or choose another directory with -LinkDir." }
        if ((Test-Path $Shim) -and -not (Test-OurShim $Shim)) { Die "$Shim already exists and was not installed by this script.`n    Move it aside, or choose another directory with -LinkDir." }
        Copy-Item -Force $built $Pyz
        # %~dp0 makes the shim find its .pyz sibling wherever the pair is put.
        # ASCII with CRLF: cmd.exe is the interpreter, and a BOM would be echoed.
        $shimText = "@echo off`r`npython `"%~dp0lmi.pyz`" %*`r`n"
        [System.IO.File]::WriteAllText($Shim, $shimText, [System.Text.Encoding]::ASCII)
        Ok "installed $Pyz"
        Ok "installed $Shim (this is what makes the bare `lmi` work)"
        Ok "the clone is no longer needed - these two files are the whole program"
    } finally {
        if (Test-Path $work) { Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue }
    }
} else {
    Step "Preparing the virtual environment"
    $venvPy = Join-Path $VenvDir 'Scripts\python.exe'
    # Probed in two statements: PowerShell cannot take a ;-separated sequence
    # inside a parenthesised condition.
    $venvUsable = $false
    if (Test-Path $venvPy) {
        & $venvPy -c "" 2>$null
        $venvUsable = ($LASTEXITCODE -eq 0)
    }
    if ($venvUsable) {
        Ok "reusing $VenvDir"
    } else {
        if (Test-Path $VenvDir) { Warn "existing $VenvDir is not usable, rebuilding it"; Remove-Item -Recurse -Force $VenvDir }
        & $PyExe -m venv $VenvDir
        if ($LASTEXITCODE -ne 0) { Die "python -m venv failed. Drop -Venv to use the default mode, which needs no virtual environment." }
        Ok "created $VenvDir"
    }
    Step "Installing lmi into it"
    $pipArgs = @('-m','pip','install','--quiet','--upgrade')
    if ($Editable) { $pipArgs += '--editable' }
    & $venvPy @pipArgs $Repo
    if ($LASTEXITCODE -ne 0) {
        Die "pip failed. If this machine has no network that is expected: pip
    fetches setuptools to build the package. Drop -Venv to use the default
    mode, which needs nothing:

        .\scripts\install-windows.ps1"
    }
    $venvLmi = Join-Path $VenvDir 'Scripts\lmi.exe'
    if (-not (Test-Path $venvLmi)) { Die "pip reported success but $venvLmi is missing." }
    Ok ("installed" + $(if ($Editable) { " (editable)" } else { "" }))

    Step "Putting it on your PATH"
    New-Item -ItemType Directory -Force -Path $LinkDir | Out-Null
    if ((Test-Path $Shim) -and -not (Test-OurShim $Shim)) { Die "$Shim already exists and was not installed by this script." }
    $shimText = "@echo off`r`n`"$venvLmi`" %*`r`n"
    [System.IO.File]::WriteAllText($Shim, $shimText, [System.Text.Encoding]::ASCII)
    Ok "installed $Shim -> $venvLmi"
    Warn "this mode needs the clone to stay where it is"
}

# --- 3. PATH ---------------------------------------------------------------
Step "Checking PATH"
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($null -eq $userPath) { $userPath = '' }
$already = ($userPath -split ';' | Where-Object { $_ -and ($_.TrimEnd('\') -ieq $LinkDir.TrimEnd('\')) })
if ($already) {
    Ok "$LinkDir is already on your user PATH"
} else {
    # Only the user scope, and only prepending our directory. Deliberately not
    # setx, which folds the system PATH into the user variable and truncates at
    # 1024 characters.
    [Environment]::SetEnvironmentVariable('Path', "$LinkDir;$userPath", 'User')
    Ok "added $LinkDir to your user PATH"
    Warn "this does not affect the window you are in - open a new one"
}
$env:Path = "$LinkDir;$env:Path"

# --- 4. verify -------------------------------------------------------------
Step "Verifying"
$version = (& $Shim --version 2>&1) | Select-Object -Last 1
if ($LASTEXITCODE -ne 0) { Die "$Shim did not run: $version" }
Ok $version

Write-Host ""
Write-Host "Installed." -ForegroundColor White
Write-Host "  Open a NEW cmd or PowerShell window, then run: lmi --version"
Write-Host ""
Write-Host "  lmi needs the Claude Code CLI on PATH: claude --version"
Write-Host "  If it is missing, install it and run claude auth login once -"
Write-Host "  the sign-in is interactive and lmi cannot do it for you."
Write-Host ""
Write-Host "  Re-run this script to upgrade. Uninstall with -Uninstall."
