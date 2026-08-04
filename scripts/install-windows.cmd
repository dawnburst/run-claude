@echo off
rem ===========================================================================
rem  Install the `lmi` CLI on Windows, from cmd.exe.
rem
rem      scripts\install-windows.cmd
rem
rem  This is a thin wrapper. The installer itself is install-windows.ps1, in
rem  this same directory, and every option is passed straight through:
rem
rem      scripts\install-windows.cmd -Uninstall
rem      scripts\install-windows.cmd -Venv -Editable
rem      scripts\install-windows.cmd -LinkDir C:\tools\bin
rem
rem  Two reasons the logic lives in PowerShell rather than here:
rem
rem    * PATH. `setx PATH` expands the whole current PATH - system entries
rem      included - into the *user* variable, and truncates at 1024 characters,
rem      which can quietly corrupt a working PATH. PowerShell's
rem      SetEnvironmentVariable touches only the user scope and has no limit.
rem
rem    * One implementation. Two installers written in two languages would have
rem      to be kept in step by hand, and would drift.
rem
rem  -ExecutionPolicy Bypass applies to this one invocation only. It changes no
rem  machine setting, and is what lets the installer run on a default Windows
rem  where the policy would otherwise block a local script.
rem ===========================================================================

setlocal
set "PS_SCRIPT=%~dp0install-windows.ps1"

if not exist "%PS_SCRIPT%" (
    echo error install-windows.ps1 is missing from %~dp0
    echo        Both files ship together; re-clone or restore it.
    exit /b 1
)

where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo error powershell.exe is not on PATH.
    echo        It ships with every supported version of Windows; if it is
    echo        genuinely absent, follow the manual steps in
    echo        docs\install\windows-cmd.md instead.
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" %*
exit /b %ERRORLEVEL%
