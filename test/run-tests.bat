@echo off
setlocal EnableDelayedExpansion
rem ===========================================================================
rem  run-tests.bat - regression suite for run-claude.bat
rem
rem    run-tests.bat          fast cases only, about 15 seconds
rem    run-tests.bat -full    adds the slow timing cases, about 2.5 minutes
rem
rem  Everything here runs against test\bin\claude.cmd, the stub. No real claude
rem  call is ever made, so the suite is free and can be run after every edit.
rem  What a stub can NOT prove is how the real CLI behaves - landmines 13 and 14
rem  were both found by real runs. Keep doing those too, see CLAUDE.md 6a.
rem
rem  Exit code: 0 all passed, 1 at least one failed, 9 the suite could not start.
rem ===========================================================================

set "SUITE=%~dp0"
set "SCRIPT=%SUITE%..\run-claude.bat"
if not exist "%SCRIPT%" (
    echo [FATAL] run-claude.bat was not found next to the test folder.
    exit /b 9
)

set "FULL="
if /i "%~1"=="-full" set "FULL=1"

rem --- PATH is rebuilt from scratch on purpose ------------------------------
rem  run-claude.bat looks for claude.exe BEFORE claude.cmd, so simply putting
rem  the stub first is not enough: a real claude.exe anywhere on PATH would win
rem  and the suite would quietly spend real quota. A minimal PATH removes it.
set "PATH=%SUITE%bin;%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\WindowsPowerShell\v1.0"

where claude.cmd >nul 2>&1 || (echo [FATAL] the stub test\bin\claude.cmd is not reachable. & exit /b 9)
where claude.exe >nul 2>&1 && (echo [FATAL] a real claude.exe is still on PATH - refusing to run. & exit /b 9)
where powershell.exe >nul 2>&1 || (echo [FATAL] powershell.exe is not on the minimal PATH. & exit /b 9)

for /f "usebackq delims=" %%A in (`powershell.exe -NoProfile -Command "(Get-Date).ToString('yyyyMMdd-HHmmss')"`) do set "TS=%%A"
set "ROOT=%TEMP%\rc-suite-!TS!"
mkdir "!ROOT!" 2>nul

set "PASS=0"
set "FAIL=0"
set "CASE=0"
set "FAILED="

echo(===========================================================================
echo( run-tests.bat - stub suite for run-claude.bat
if defined FULL echo( mode: -full, slow timing cases included
if not defined FULL echo( mode: fast, run with -full to add the slow timing cases
echo( work area: !ROOT!
echo(===========================================================================
echo(
echo(-- argument validation, nothing should reach the stub --

call :case "no arguments at all"
call "%SCRIPT%" >"!OUT!" 2>&1
call :rc & call :want_rc 2 & call :want_calls 0 & call :done

call :case "-i without -c"
call "%SCRIPT%" "p" -i 5 >"!OUT!" 2>&1
call :rc & call :want_rc 2 & call :want_in "!OUT!" "-i requires -c" & call :done

call :case "-c without -i"
call "%SCRIPT%" "p" -c 3 >"!OUT!" 2>&1
call :rc & call :want_rc 2 & call :want_in "!OUT!" "-c requires -i" & call :done

call :case "-i 0 without -c - the value must not look like 'not given'"
call "%SCRIPT%" "p" -i 0 >"!OUT!" 2>&1
call :rc & call :want_rc 2 & call :done

call :case "-i not a number"
call "%SCRIPT%" "p" -i abc -c 2 >"!OUT!" 2>&1
call :rc & call :want_rc 2 & call :done

call :case "-c zero"
call "%SCRIPT%" "p" -i 1 -c 0 >"!OUT!" 2>&1
call :rc & call :want_rc 2 & call :done

call :case "-c not a number"
call "%SCRIPT%" "p" -i 1 -c abc >"!OUT!" 2>&1
call :rc & call :want_rc 2 & call :done

call :case "-t malformed"
call "%SCRIPT%" "p" -t "yesterday" >"!OUT!" 2>&1
call :rc & call :want_rc 2 & call :done

call :case "-t with no value"
call "%SCRIPT%" "p" -t >"!OUT!" 2>&1
call :rc & call :want_rc 2 & call :done

call :case "-d that does not exist"
call "%SCRIPT%" "p" -d "!ROOT!\nope\nope" >"!OUT!" 2>&1
call :rc & call :want_rc 2 & call :done

call :case "prompt argument is a directory - landmine 6"
call "%SCRIPT%" "!ROOT!" -d "!DIR!" >"!OUT!" 2>&1
call :rc & call :want_rc 2 & call :want_in "!OUT!" "is a directory" & call :done

call :case "two positional arguments"
call "%SCRIPT%" "one" "two" >"!OUT!" 2>&1
call :rc & call :want_rc 2 & call :want_in "!OUT!" "Unexpected argument" & call :done

call :case "-h exits 0 and prints usage"
call "%SCRIPT%" -h >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_in "!OUT!" "Usage:" & call :want_calls 0 & call :done

echo(
echo(-- a single run --

call :case "single run, inline prompt"
call "%SCRIPT%" "do a thing" -d "!DIR!" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_calls 1
call :want_file "!DIR!\run-claude-state.md"
call :find_log "!DIR!" & call :want_in "!LOGF!" "stub claude call 1"
call :done

call :case "the composed prompt carries the protocol and the task"
call "%SCRIPT%" "MAGICTASKTEXT" -d "!DIR!" >"!OUT!" 2>&1
call :rc & call :want_rc 0
call :want_in "!STUB_DIR!\prompt-1.txt" "## CURRENT STATE"
call :want_in "!STUB_DIR!\prompt-1.txt" "## TASK"
call :want_in "!STUB_DIR!\prompt-1.txt" "MAGICTASKTEXT"
call :want_in "!STUB_DIR!\prompt-1.txt" "TASK_STATUS: IN_PROGRESS"
call :done

call :case "prompt read from a file"
>"!DIR!\task.md" echo(MAGICFILETEXT
call "%SCRIPT%" "!DIR!\task.md" -d "!DIR!" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_in "!STUB_DIR!\prompt-1.txt" "MAGICFILETEXT" & call :done

call :case "inline prompt containing ^& ^| ^< ^> ( ) - landmine 2"
call "%SCRIPT%" "keep a & b, pipe | this, less < more, paren ( ) ok" -d "!DIR!" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_calls 1 & call :want_in "!STUB_DIR!\prompt-1.txt" "pipe | this" & call :done

echo(
echo(-- loops --

call :case "-i 0 -c 3 runs three times"
call "%SCRIPT%" "p" -d "!DIR!" -i 0 -c 3 >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_calls 3 & call :done

call :case "early stop when line 1 becomes COMPLETE"
set "STUB_COMPLETE_AT=2"
call "%SCRIPT%" "p" -d "!DIR!" -i 0 -c 5 >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_calls 2
call :find_log "!DIR!" & call :want_in "!LOGF!" "stopping the loop"
call :done

call :case "landmine 14 - COMPLETE in prose must NOT stop the loop"
set "STUB_PROSE=1"
call "%SCRIPT%" "p" -d "!DIR!" -i 0 -c 3 >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_calls 3
call :find_log "!DIR!" & call :want_notin "!LOGF!" "stopping the loop"
call :done

call :case "-c 1 with -i 5 must not wait after the only iteration"
call "%SCRIPT%" "p" -d "!DIR!" -i 5 -c 1 >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_calls 1
call :find_log "!DIR!" & call :want_notin "!LOGF!" "Waiting 5 minutes"
call :done

echo(
echo(-- a failing claude must never fail the runner, invariant 2 --

call :case "claude exits 7 - runner survives, keeps looping, exits 1"
set "STUB_RC=7"
call "%SCRIPT%" "p" -d "!DIR!" -i 0 -c 2 >"!OUT!" 2>&1
call :rc & call :want_rc 1 & call :want_calls 2
call :find_log "!DIR!" & call :want_in "!LOGF!" "[ERROR]" & call :want_in "!LOGF!" "exit code 7"
call :done

call :case "quota wording is flagged [QUOTA]"
set "STUB_OUT=Claude usage limit reached, try again later"
call "%SCRIPT%" "p" -d "!DIR!" >"!OUT!" 2>&1
call :rc & call :want_rc 0
call :find_log "!DIR!" & call :want_in "!LOGF!" "[QUOTA]"
call :done

echo(
echo(-- log, state and flag plumbing --

call :case "-l pointing at a folder"
mkdir "!DIR!\logs" 2>nul
call "%SCRIPT%" "p" -d "!DIR!" -l "!DIR!\logs" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :find_log "!DIR!\logs" & call :done

call :case "-l pointing at a file"
call "%SCRIPT%" "p" -d "!DIR!" -l "!DIR!\my.log" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_file "!DIR!\my.log" & call :done

call :case "-s a custom state file"
set "STUB_STATE_FILE=!DIR!\custom-state.md"
call "%SCRIPT%" "p" -d "!DIR!" -s "!DIR!\custom-state.md" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_file "!DIR!\custom-state.md" & call :want_nofile "!DIR!\run-claude-state.md" & call :done

call :case "-f flags reach the CLI"
call "%SCRIPT%" "p" -d "!DIR!" -f "--verbose" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_in "!STUB_DIR!\args-1.txt" "[--verbose]" & call :done

call :case "the default flags and --add-dir reach the CLI"
rem  asserted against the raw command line, not the per token file: batch splits
rem  %1 on = and , so --allowed-tools=Edit,Write is three tokens in args-N.txt
call "%SCRIPT%" "p" -d "!DIR!" >"!OUT!" 2>&1
call :rc & call :want_rc 0
call :want_in "!STUB_DIR!\args-1.txt" "[-p]"
call :want_in "!STUB_DIR!\cmdline-1.txt" "--allowed-tools=Edit,Write"
call :want_in "!STUB_DIR!\cmdline-1.txt" "--add-dir"
call :done

echo(
echo(-- prompt file encoding, landmine 15 --

call :case "a UTF-8 prompt file is carried through byte for byte"
set "TF=!DIR!\task8.md"
powershell.exe -NoProfile -NonInteractive -Command "[IO.File]::WriteAllText($env:TF,'MAGICUTF8 task',(New-Object System.Text.UTF8Encoding $false))" <nul
call "%SCRIPT%" "!TF!" -d "!DIR!" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_in "!STUB_DIR!\prompt-1.txt" "MAGICUTF8"
call :find_log "!DIR!" & call :want_notin "!LOGF!" "[WARN]"
call :done

call :case "a UTF-16 prompt file is reported with [WARN]"
set "TF=!DIR!\task16.md"
powershell.exe -NoProfile -NonInteractive -Command "[IO.File]::WriteAllText($env:TF,'MAGICUTF16 task',[Text.Encoding]::Unicode)" <nul
call "%SCRIPT%" "!TF!" -d "!DIR!" >"!OUT!" 2>&1
call :rc & call :want_rc 0
call :find_log "!DIR!" & call :want_in "!LOGF!" "UTF-16 byte order mark"
call :done

call :case "an inline prompt never triggers the encoding warning"
call "%SCRIPT%" "plain inline task" -d "!DIR!" >"!OUT!" 2>&1
call :rc & call :want_rc 0
call :find_log "!DIR!" & call :want_notin "!LOGF!" "[WARN]"
call :done

echo(
echo(-- state file lifecycle --

call :case "a second run without -r backs the state up and starts clean"
set "STUB_STATE=1"
call "%SCRIPT%" "p" -d "!DIR!" >"!OUT!" 2>&1
call "%SCRIPT%" "p" -d "!DIR!" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_bak "!DIR!" & call :done

call :case "-r keeps the existing state file"
set "STUB_STATE=1"
call "%SCRIPT%" "p" -d "!DIR!" >"!OUT!" 2>&1
call "%SCRIPT%" "p" -d "!DIR!" -r >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_nobak "!DIR!"
call :want_in "!DIR!\run-claude-state.md" "stub call 1 recorded some progress"
call :done

echo(
echo(-- awkward paths, landmines 2 and 4 --

call :case "working directory containing a space"
set "W=!DIR!\dir with space"
mkdir "!W!" 2>nul
set "STUB_STATE_FILE=!W!\run-claude-state.md"
call "%SCRIPT%" "p" -d "!W!" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_calls 1 & call :find_log "!W!" & call :done

call :case "working directory containing an ampersand"
set "W=!DIR!\amp & dir"
mkdir "!W!" 2>nul
set "STUB_STATE_FILE=!W!\run-claude-state.md"
call "%SCRIPT%" "p" -d "!W!" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_calls 1 & call :find_log "!W!" & call :done

call :case "working directory containing (x86)"
set "W=!DIR!\progs (x86)"
mkdir "!W!" 2>nul
set "STUB_STATE_FILE=!W!\run-claude-state.md"
call "%SCRIPT%" "p" -d "!W!" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_calls 1 & call :find_log "!W!" & call :done

call :case "state file and log in a path containing an ampersand"
set "W=!DIR!\a & b"
mkdir "!W!" 2>nul
set "STUB_STATE_FILE=!W!\st.md"
call "%SCRIPT%" "p" -d "!DIR!" -s "!W!\st.md" -l "!W!\out.log" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_file "!W!\st.md" & call :want_file "!W!\out.log" & call :done

echo(
echo(-- the single instance lock --

call :case "a second run on the same state file is refused with exit 3"
>"!DIR!\holder.bat"  echo(@echo off
>>"!DIR!\holder.bat" echo(set "STUB_SLEEP=8"
>>"!DIR!\holder.bat" echo(set "STUB_DIR=!STUB_DIR!"
>>"!DIR!\holder.bat" echo(set "STUB_COUNT_FILE=!STUB_COUNT_FILE!"
>>"!DIR!\holder.bat" echo(call "!SCRIPT!" "hold the lock" -d "!DIR!" ^> "!DIR!\holder-out.txt" 2^>^&1
start "" /b cmd /c "!DIR!\holder.bat" >nul 2>&1
powershell.exe -NoProfile -NonInteractive -Command "Start-Sleep -Seconds 3" <nul
call "%SCRIPT%" "second run" -d "!DIR!" >"!OUT!" 2>&1
call :rc & call :want_rc 3 & call :want_in "!OUT!" "already running"
powershell.exe -NoProfile -NonInteractive -Command "Start-Sleep -Seconds 7" <nul
call :done

call :case "the lock is free again once the holder has finished"
call "%SCRIPT%" "p" -d "!DIR!" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_calls 1 & call :done

echo(
echo(-- start time --

call :case "-t in the past starts immediately"
call "%SCRIPT%" "p" -d "!DIR!" -t "2020-01-01 00:00" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_calls 1
call :find_log "!DIR!" & call :want_in "!LOGF!" "already in the past"
call :done

call :case "-t given unquoted as two tokens"
call "%SCRIPT%" "p" -d "!DIR!" -t 2020-01-01 00:00 >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_calls 1 & call :done

if not defined FULL goto summary

echo(
echo(-- slow timing cases, -full only --

call :case "-t about one minute ahead really waits"
for /f "usebackq delims=" %%A in (`powershell.exe -NoProfile -Command "(Get-Date).AddSeconds(75).ToString('yyyy-MM-dd HH:mm')"`) do set "T=%%A"
call "%SCRIPT%" "p" -d "!DIR!" -t "!T!" >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_calls 1
call :find_log "!DIR!" & call :want_in "!LOGF!" "Woke up at"
call :done

call :case "-i 1 -c 2 waits a minute measured from the end of iteration 1"
call "%SCRIPT%" "p" -d "!DIR!" -i 1 -c 2 >"!OUT!" 2>&1
call :rc & call :want_rc 0 & call :want_calls 2
call :find_log "!DIR!" & call :want_in "!LOGF!" "Waiting 1 minutes"
call :done

:summary
echo(
echo(===========================================================================
set /a TOTAL=!PASS!+!FAIL!
echo( !TOTAL! cases: !PASS! passed, !FAIL! failed
if not "!FAIL!"=="0" echo( failed: !FAILED!
echo( artefacts kept in: !ROOT!
echo(===========================================================================
if not "!FAIL!"=="0" endlocal & exit /b 1
endlocal & exit /b 0


rem ===========================================================================
rem  helpers
rem ===========================================================================

rem --- start a case: fresh directory, fresh stub state ----------------------
:case
set /a CASE+=1
set "NAME=%~1"
set "DIR=!ROOT!\case!CASE!"
mkdir "!DIR!" 2>nul
set "OUT=!DIR!\console.txt"
set "OK=1"
set "WHY="
set "LOGF="
set "STUB_RC="
set "STUB_OUT="
set "STUB_SLEEP="
set "STUB_STATE="
set "STUB_COMPLETE="
set "STUB_COMPLETE_AT="
set "STUB_PROSE="
set "STUB_DIR=!DIR!\stub"
set "STUB_COUNT_FILE=!DIR!\stub\count.txt"
set "STUB_STATE_FILE=!DIR!\run-claude-state.md"
mkdir "!STUB_DIR!" 2>nul
goto :eof

rem --- capture the exit code of the run just made ---------------------------
rem     a separate label so the test lines can read  call :rc & call :want_rc N
:rc
set "RC=%ERRORLEVEL%"
goto :eof

:want_rc
if not "!RC!"=="%~1" call :flag "exit code !RC!, wanted %~1"
goto :eof

:want_calls
set "GOT=0"
if exist "!STUB_COUNT_FILE!" set /p GOT=<"!STUB_COUNT_FILE!"
if not "!GOT!"=="%~1" call :flag "the stub ran !GOT! times, wanted %~1"
goto :eof

:want_file
if not exist "%~1" call :flag "missing file: %~1"
goto :eof

:want_nofile
if exist "%~1" call :flag "this file should not exist: %~1"
goto :eof

:want_in
if not exist "%~1" call :flag "cannot search a missing file: %~1"
if not exist "%~1" goto :eof
findstr /i /c:"%~2" "%~1" >nul 2>&1
if errorlevel 1 call :flag "not found in %~nx1: %~2"
goto :eof

:want_notin
if not exist "%~1" goto :eof
findstr /i /c:"%~2" "%~1" >nul 2>&1
if not errorlevel 1 call :flag "should not appear in %~nx1: %~2"
goto :eof

:find_log
set "LOGF="
for /f "delims=" %%F in ('dir /b /o-d "%~1\run-claude-*.log" 2^>nul') do if not defined LOGF set "LOGF=%~1\%%F"
if not defined LOGF call :flag "no run-claude log was written in %~1"
goto :eof

:want_bak
set "GOTBAK="
for /f "delims=" %%F in ('dir /b "%~1\*.bak" 2^>nul') do set "GOTBAK=1"
if not defined GOTBAK call :flag "no state backup was made in %~1"
goto :eof

:want_nobak
set "GOTBAK="
for /f "delims=" %%F in ('dir /b "%~1\*.bak" 2^>nul') do set "GOTBAK=1"
if defined GOTBAK call :flag "a state backup was made even though -r was given"
goto :eof

:flag
set "OK="
set "WHY=!WHY! / %~1"
goto :eof

:done
if defined OK (
    set /a PASS+=1
    echo(  [PASS] !NAME!
) else (
    set /a FAIL+=1
    echo(  [FAIL] !NAME! !WHY!
    set "FAILED=!FAILED![!CASE!] "
)
goto :eof
