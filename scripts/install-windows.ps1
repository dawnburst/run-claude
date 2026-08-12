<#
Install the `lmi` CLI on Windows so that typing `lmi` works, in both cmd.exe and
PowerShell.

    .\scripts\install-windows.ps1
    .\install-windows.ps1 -Wheel lmi-0.1.0-py3-none-any.whl

It installs the wheel - one file, `lmi-<version>-py3-none-any.whl`, the same file
on every operating system - with `pip install --user`. pip then generates a real
`lmi.exe`, and that executable is the point of doing it this way:

  * It is a genuine PE binary with the interpreter path built in, so nothing has
    to find `python` on PATH at run time. That is what makes a Scheduled Task or
    a service-context run resolve `lmi` at all.

  * There is no `cmd.exe` anywhere in the chain. The previous installer shipped a
    two-line lmi.cmd shim, and cmd.exe cannot hold a UNC working directory: run
    from \\wsl.localhost\... it silently substitutes C:\Windows, so lmi aimed its
    state file, log and lock at C:\Windows and failed with Permission denied. The
    .exe keeps the real working directory. Measured, from the same UNC path:
        direct .exe  ->  \\wsl.localhost\Ubuntu-24.04\home\...
        via cmd      ->  C:\Windows

--user is deliberate: it needs no administrator rights and puts the command in a
directory this script can compute exactly, rather than depending on whether
Python was installed for one user or for all of them. The trade-off is that the
user Scripts directory is not on PATH by default, which is the trap that made
`pip install --user` appear to work and leave `lmi` unrecognised - so this script
adds it.

PowerShell owns the PATH edit for a concrete reason: `setx PATH` expands the
whole current PATH into the *user* variable and truncates at 1024 characters,
which can quietly corrupt a long PATH. SetEnvironmentVariable touches only the
user scope and has no such limit.

install-windows.cmd is a thin wrapper that calls this file, so there is one
implementation rather than two that must be kept in step.
#>
[CmdletBinding()]
param(
    [string] $Wheel,
    [switch] $Uninstall,
    [switch] $Help
)

$ErrorActionPreference = 'Stop'
$MinPy = [Version]'3.9'

# Where the previous installer put its zipapp and shim. Cleaned up on the way
# through, because .local\bin may well come before the user Scripts directory on
# PATH, in which case the old shim would shadow the new .exe and an upgrade
# would appear to do nothing.
$LegacyDir  = Join-Path $env:USERPROFILE '.local\bin'
$LegacyPyz  = Join-Path $LegacyDir 'lmi.pyz'
$LegacyShim = Join-Path $LegacyDir 'lmi.cmd'

# Run an external program, returning its combined output and exit code.
#
# This exists because `& $exe 2>&1` under $ErrorActionPreference = 'Stop' is a
# trap: PowerShell turns a native program's stderr into error *records*, and
# 'Stop' then makes the first one terminating. Anything that merely warns on
# stderr therefore kills the script even when it succeeded. The case that caught
# this: running the installer with a UNC working directory, where cmd.exe prints
# "UNC paths are not supported" to stderr, so verifying a freshly installed
# command aborted an install that had in fact worked.
function Invoke-Capture {
    param(
        [Parameter(Mandatory)] [string] $File,
        [string[]] $Arguments = @()
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        # @(...) is load-bearing: without it a single output line stays a
        # [string], and $lines[-1] then indexes its last CHARACTER rather than
        # its last line - so "3.13" became "3" and the version check failed.
        #
        # ErrorRecord is unwrapped rather than cast: 2>&1 turns a native
        # program's stderr into ErrorRecords, and [string] on one of those
        # yields the literal text "System.Management.Automation.RemoteException".
        # A failing pip therefore reported that instead of its own error, which
        # is worse than no message at all - it names a .NET type as the cause.
        $lines = @(& $File @Arguments 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message }
            else { [string] $_ }
        })
        return [pscustomobject]@{
            Text = ($lines -join "`n")
            Last = if ($lines.Count) { [string] $lines[-1] } else { '' }
            Code = $LASTEXITCODE
        }
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Step($m) { Write-Host "==> " -ForegroundColor White -NoNewline; Write-Host $m }
function Ok($m)   { Write-Host "    ok " -ForegroundColor Green -NoNewline; Write-Host $m }
function Warn($m) { Write-Host "    warning " -ForegroundColor Yellow -NoNewline; Write-Host $m }
function Die($m)  { Write-Host ""; Write-Host "error " -ForegroundColor Red -NoNewline; Write-Host $m; exit 1 }

if ($Help) {
    @'
Install the lmi CLI on Windows.

    .\scripts\install-windows.ps1 [options]

Options:
  -Wheel PATH    the wheel to install. Default: the newest lmi-*.whl beside
                 this script or in dist\, else built from the checkout.
  -Uninstall     remove lmi with pip
  -Help          show this help

Needs no administrator rights. Re-run it to upgrade.
'@ | Write-Host
    exit 0
}

# ProviderPath, not .Path. When the current location is a UNC share, .Path comes
# back provider-qualified - literally
#     Microsoft.PowerShell.Core\FileSystem::\\wsl.localhost\Ubuntu\home\...
# PowerShell's own cmdlets accept that form, so Test-Path and Join-Path kept
# working and hid it; pip cannot open it, so building the wheel from a checkout
# on a share failed. ProviderPath is always the plain filesystem path.
# GetFullPath collapses the trailing "\scripts\.." that Join-Path leaves and
# Resolve-Path -LiteralPath does not, so messages name the checkout rather than
# a path with a ".." in the middle of it.
$Repo = [System.IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath)

# --- the old installer's leftovers ------------------------------------------
# Only ever remove what we recognise: a zipapp that really contains lmi/cli.py,
# and a shim that really mentions lmi.pyz.
function Test-LegacyPyz {
    if (-not (Test-Path $LegacyPyz)) { return $false }
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop
        $zip = [System.IO.Compression.ZipFile]::OpenRead($LegacyPyz)
        try   { return [bool]($zip.Entries | Where-Object { $_.FullName -eq 'lmi/cli.py' }) }
        finally { $zip.Dispose() }
    } catch { return $false }
}
function Test-LegacyShim {
    if (-not (Test-Path $LegacyShim)) { return $false }
    return (Get-Content -Raw -LiteralPath $LegacyShim) -match 'lmi\.pyz'
}
function Remove-Legacy {
    $removed = $false
    if (Test-LegacyShim) { Remove-Item -Force $LegacyShim; Ok "removed the old shim $LegacyShim"; $removed = $true }
    if (Test-LegacyPyz)  { Remove-Item -Force $LegacyPyz;  Ok "removed the old $LegacyPyz";       $removed = $true }
    return $removed
}

# --- 1. Python -------------------------------------------------------------
# python and python3 first, then the py launcher. py.exe is worth trying last
# rather than not at all: an all-users python.org install puts it in C:\Windows,
# which is on the *machine* PATH, so it resolves in contexts where the per-user
# python does not.
Step "Checking Python"
$PyExe = $null
$PyArgs = @()
foreach ($cand in @(@{N='python'; A=@()}, @{N='python3'; A=@()}, @{N='py'; A=@('-3')})) {
    $found = Get-Command $cand.N -ErrorAction SilentlyContinue
    if (-not $found) { continue }
    $probe = Invoke-Capture $found.Source ($cand.A + @('-c', "import sys; print('%d.%d' % sys.version_info[:2])"))
    if ($probe.Code -ne 0) { continue }
    $parsed = $null
    try { $parsed = [Version] $probe.Last } catch { continue }
    if ($parsed -lt $MinPy) { continue }
    $PyExe = $found.Source; $PyArgs = $cand.A; $PyVer = $parsed
    break
}
if (-not $PyExe) {
    Die "no Python $MinPy or newer was found on your PATH.

    Install it from python.org and tick 'Add python.exe to PATH'.
    If typing python opens the Microsoft Store you have the App Execution Alias
    stub rather than Python itself - a 0-byte placeholder, not an interpreter."
}
Ok "python is $PyVer at $PyExe"

# A --user install is refused inside an active virtual environment, and would be
# the wrong thing anyway - it would install into the venv's user base rather
# than yours. Catch it here with a clear message instead of a pip traceback.
$inVenv = Invoke-Capture $PyExe ($PyArgs + @('-c', 'import sys; sys.exit(1 if sys.prefix != sys.base_prefix else 0)'))
if ($inVenv.Code -ne 0) {
    # No backticks in this message: in a double-quoted PowerShell string the
    # backtick is the escape character, so it would silently vanish.
    Die "that Python is inside an active virtual environment, where a --user
    install is not allowed. Run 'deactivate' first, then re-run this script."
}

# --- uninstall -------------------------------------------------------------
if ($Uninstall) {
    Step "Removing lmi"
    $u = Invoke-Capture $PyExe ($PyArgs + @('-m','pip','uninstall','--yes','--quiet','lmi'))
    if ($u.Code -ne 0) { Die "pip uninstall failed:`n    $($u.Text)" }
    Ok "pip uninstalled lmi"
    Step "Removing the old installer's files, if any"
    if (-not (Remove-Legacy)) { Ok "none" }
    Write-Host ""
    Write-Host "Uninstalled." -ForegroundColor White
    Write-Host "  Your PATH is left as it is: the Scripts directory that was added"
    Write-Host "  is shared with every other tool you install with pip --user."
    exit 0
}

# --- 2. the wheel ----------------------------------------------------------
function Get-NewestWheel([string] $Dir) {
    if (-not (Test-Path $Dir)) { return $null }
    $w = Get-ChildItem -LiteralPath $Dir -Filter 'lmi-*.whl' -File -ErrorAction SilentlyContinue |
         Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($w) { return $w.FullName }
    return $null
}

Step "Finding the wheel"
if ($Wheel) {
    if (-not (Test-Path -LiteralPath $Wheel)) { Die "no such wheel: $Wheel" }
    # ProviderPath for the same reason as $Repo above: this path is handed to pip.
    $Wheel = (Resolve-Path -LiteralPath $Wheel).ProviderPath
} else {
    # Beside the script first: that is the shape of a machine with no git, where
    # the script and the wheel were downloaded into the same folder.
    $Wheel = Get-NewestWheel $PSScriptRoot
    if (-not $Wheel) { $Wheel = Get-NewestWheel (Join-Path $Repo 'dist') }
}
if (-not $Wheel) {
    if (-not (Test-Path (Join-Path $Repo 'pyproject.toml'))) {
        Die "no wheel found, and no checkout to build one from.

    Either download lmi-<version>-py3-none-any.whl next to this script, or
    pass it explicitly:

        .\install-windows.ps1 -Wheel C:\path\to\lmi-0.1.0-py3-none-any.whl"
    }
    Step "Building the wheel from $Repo"
    # Needs setuptools, which pip fetches unless it is already local - so this is
    # the one step that wants a network. An air-gapped machine should carry the
    # built wheel in instead; installing it needs nothing.
    $b = Invoke-Capture $PyExe ($PyArgs + @('-m','pip','wheel','--no-deps','--quiet','--wheel-dir',(Join-Path $Repo 'dist'),$Repo))
    if ($b.Code -ne 0) {
        Die "could not build the wheel:`n    $($b.Text)`n
    On a machine with no network that is expected: pip fetches setuptools to
    build. Carry the built wheel in and pass it with -Wheel."
    }
    $Wheel = Get-NewestWheel (Join-Path $Repo 'dist')
    if (-not $Wheel) { Die "pip reported success but no wheel appeared in $Repo\dist." }
}
Ok (Split-Path -Leaf $Wheel)

# --- 3. install ------------------------------------------------------------
Step "Installing it"
# --no-index: never reach for the network. Safe because lmi declares no
# dependencies, which tests/test_packaging.py exists to keep true.
# --force-reinstall: the version does not change on every source change, and
# without it pip treats reinstalling 0.1.0 over 0.1.0 as nothing to do - so an
# upgrade would silently keep the old code.
# --no-warn-script-location: we check the location ourselves, and fix PATH.
$pip = Invoke-Capture $PyExe ($PyArgs + @(
    '-m','pip','install','--user','--no-index','--force-reinstall','--quiet',
    '--no-warn-script-location',$Wheel))
if ($pip.Code -ne 0) { Die "pip install failed:`n    $($pip.Text)" }

# Ask that same Python where its user Scripts directory is, rather than guessing
# %APPDATA%\Python\PythonXY\Scripts - the answer differs between installs.
#
# sysconfig, deliberately not os.path.join(site.getuserbase(), 'Scripts'), which
# looks equivalent and is wrong for a Microsoft Store Python: it inserts a
# version level, so the real directory is <userbase>\Python313\Scripts and the
# simpler form pointed one level too high. Measured on Store Python 3.13.
# get_preferred_scheme is 3.10+, hence the fallback to the 3.9 name.
#
# The Python snippet quotes with SINGLE quotes on purpose. PowerShell 5.1 mangles
# embedded double quotes when it builds the command line for a native
# executable, so a "Scripts" here reached python unquoted and died with a
# NameError - which surfaced as "could not work out the user Scripts directory".
$dirProbe = Invoke-Capture $PyExe ($PyArgs + @('-c', "import sys, sysconfig; s = sysconfig.get_preferred_scheme('user') if hasattr(sysconfig, 'get_preferred_scheme') else 'nt_user'; sys.stdout.write(sysconfig.get_path('scripts', s))"))
if ($dirProbe.Code -ne 0 -or -not $dirProbe.Last) { Die "could not work out the user Scripts directory." }
$ScriptsDir = $dirProbe.Last
$Exe = Join-Path $ScriptsDir 'lmi.exe'
if (-not (Test-Path $Exe)) {
    Die "pip reported success but $Exe is missing.
    That means the wheel has no console script - check [project.scripts]."
}
Ok "installed $Exe"

Step "Removing the old installer's files, if any"
if (-not (Remove-Legacy)) { Ok "none" }

# --- 4. PATH ---------------------------------------------------------------
Step "Checking PATH"
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($null -eq $userPath) { $userPath = '' }
$already = ($userPath -split ';' | Where-Object { $_ -and ($_.TrimEnd('\') -ieq $ScriptsDir.TrimEnd('\')) })
if ($already) {
    Ok "$ScriptsDir is already on your user PATH"
} else {
    # Only the user scope, and only prepending our directory. Deliberately not
    # setx, which folds the system PATH into the user variable and truncates at
    # 1024 characters.
    [Environment]::SetEnvironmentVariable('Path', "$ScriptsDir;$userPath", 'User')
    Ok "added $ScriptsDir to your user PATH"
    Warn "this does not affect the window you are in - open a new one"
}

# --- 5. verify -------------------------------------------------------------
Step "Verifying"
$verify = Invoke-Capture $Exe @('--version')
if ($verify.Code -ne 0) { Die "$Exe did not run:`n    $($verify.Text)" }
Ok $verify.Last

Write-Host ""
Write-Host "Installed." -ForegroundColor White
Write-Host "  Open a NEW cmd or PowerShell window, then run: lmi --version"
Write-Host ""
Write-Host "  lmi needs the Claude Code CLI on PATH: claude --version"
Write-Host "  If it is missing, install it and run claude auth login once -"
Write-Host "  the sign-in is interactive and lmi cannot do it for you."
Write-Host ""
Write-Host "  lmi install claude does both: it installs the Claude Code CLI and"
Write-Host "  sets up the Claude Agent SDK backend that lmi schedule uses by"
Write-Host "  default. This script deliberately installs neither - it reads no"
Write-Host "  config file, so it has no registry, no package index and no CA file."
Write-Host ""
Write-Host "  Re-run this script to upgrade. Uninstall with -Uninstall."
