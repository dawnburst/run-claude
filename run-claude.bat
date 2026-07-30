@echo off
setlocal DisableDelayedExpansion
rem ===========================================================================
rem  run-claude.bat - unattended runner for the Claude Code CLI (claude -p)
rem
rem    run-claude.bat "<prompt or prompt-file>" [-t "YYYY-MM-DD HH:MM"]
rem                   [-i minutes] [-c count] [-d workdir] [-f "flags"]
rem                   [-l logfolder] [-s statefile] [-r]
rem
rem  Run  run-claude.bat -h  for the full option list.
rem ===========================================================================

set "SCRIPT_NAME=run-claude.bat"
set "INVOKE_DIR=%CD%"

rem --- defaults -------------------------------------------------------------
set "PROMPT_ARG="
set "TARGET_TIME="
set "INTERVAL_MIN=0"
set "INTERVAL_GIVEN="
set "MAX_RUNS="
set "WORK_DIR="
set "USER_FLAGS="
set "LOG_ARG="
set "STATE_ARG="
set "RESUME_STATE=0"
set "DEFAULT_FLAGS=--allowed-tools=Edit,Write"

set "EXIT_CODE=0"
set "LOG="
set "LOCK_FILE="
set "TMP_DIR="

rem ===========================================================================
rem  1. Parse arguments   (goto based - a parenthesised block would expand
rem     variables too early)
rem ===========================================================================
:parse
if "%~1"=="" goto parse_done
set "A=%~1"

if /i "%A%"=="-h"     goto usage
if /i "%A%"=="--help" goto usage
if /i "%A%"=="/?"     goto usage
if /i "%A%"=="-t"     goto opt_t
if /i "%A%"=="-i"     goto opt_i
if /i "%A%"=="-c"     goto opt_c
if /i "%A%"=="-d"     goto opt_d
if /i "%A%"=="-f"     goto opt_f
if /i "%A%"=="-l"     goto opt_l
if /i "%A%"=="-s"     goto opt_s
if /i "%A%"=="-r"     goto opt_r
goto opt_prompt

:opt_t
if "%~2"=="" goto err_missing_value
set "TARGET_TIME=%~2"
shift
shift
rem tolerate an unquoted   -t 2026-08-01 09:30
call :is_date_only "%TARGET_TIME%"
if errorlevel 1 goto parse
call :is_hhmm "%~1"
if errorlevel 1 goto parse
call :append_time "%~1"
shift
goto parse

:opt_i
if "%~2"=="" goto err_missing_value
set "INTERVAL_MIN=%~2"
rem  a separate flag, not a test on the value: -i 0 is legal and 0 is also the
rem  default, so the value alone cannot say whether the user passed -i
set "INTERVAL_GIVEN=1"
shift
shift
goto parse

:opt_c
if "%~2"=="" goto err_missing_value
set "MAX_RUNS=%~2"
shift
shift
goto parse

:opt_d
if "%~2"=="" goto err_missing_value
set "WORK_DIR=%~2"
shift
shift
goto parse

:opt_f
if "%~2"=="" goto err_missing_value
set "USER_FLAGS=%~2"
shift
shift
goto parse

:opt_l
if "%~2"=="" goto err_missing_value
set "LOG_ARG=%~2"
shift
shift
goto parse

:opt_s
if "%~2"=="" goto err_missing_value
set "STATE_ARG=%~2"
shift
shift
goto parse

:opt_r
set "RESUME_STATE=1"
shift
goto parse

:opt_prompt
if defined PROMPT_ARG goto err_extra_arg
set "PROMPT_ARG=%A%"
shift
goto parse

:parse_done

rem ===========================================================================
rem  2. Validate arguments
rem ===========================================================================
if not defined PROMPT_ARG (
    echo [ERROR] Missing mandatory parameter: the prompt text, or the path of a
    echo         file that contains the prompt.
    goto usage_err
)

call :is_number "%INTERVAL_MIN%"
if errorlevel 1 goto err_interval

if defined MAX_RUNS call :check_count
if errorlevel 1 goto err_count

rem --- -i and -c are only meaningful together ------------------------------
if defined INTERVAL_GIVEN if not defined MAX_RUNS goto err_i_needs_c
if defined MAX_RUNS if not defined INTERVAL_GIVEN goto err_c_needs_i

rem --- PowerShell is used for time handling and safe text writing -----------
set "PS="
where powershell.exe >nul 2>&1 && set "PS=powershell.exe"
if not defined PS where pwsh.exe >nul 2>&1 && set "PS=pwsh.exe"
if not defined PS (
    echo [ERROR] Neither powershell.exe nor pwsh.exe was found on PATH.
    echo         %SCRIPT_NAME% needs one of them to handle times and waits.
    endlocal & exit /b 2
)

rem --- claude CLI present? --------------------------------------------------
set "CLAUDE_EXE="
where claude.exe >nul 2>&1 && set "CLAUDE_EXE=claude.exe"
if not defined CLAUDE_EXE where claude.cmd >nul 2>&1 && set "CLAUDE_EXE=claude.cmd"
if not defined CLAUDE_EXE where claude.bat >nul 2>&1 && set "CLAUDE_EXE=claude.bat"
if not defined CLAUDE_EXE where claude >nul 2>&1 && set "CLAUDE_EXE=claude"
if not defined CLAUDE_EXE (
    echo [ERROR] The 'claude' CLI was not found on PATH.
    endlocal & exit /b 2
)

rem --- working directory ----------------------------------------------------
if not defined WORK_DIR set "WORK_DIR=%INVOKE_DIR%"
if not exist "%WORK_DIR%\." goto err_workdir
pushd "%WORK_DIR%" 2>nul
if errorlevel 1 goto err_workdir
set "WORK_DIR=%CD%"
popd

rem --- target start time ----------------------------------------------------
if defined TARGET_TIME call :check_target
if errorlevel 1 goto err_target

rem --- prompt: an existing file, or literal text ---------------------------
rem     file attributes are used on purpose: if exist "name\." is also true
rem     for plain files on some Windows versions
set "PROMPT_FILE="
set "PROMPT_ATTR="
if not exist "%PROMPT_ARG%" goto prompt_is_text
for %%F in ("%PROMPT_ARG%") do set "PROMPT_ATTR=%%~aF"
if not defined PROMPT_ATTR goto prompt_is_text
if /i "%PROMPT_ATTR:~0,1%"=="d" goto err_prompt_dir
for %%F in ("%PROMPT_ARG%") do set "PROMPT_FILE=%%~fF"
:prompt_is_text

rem ===========================================================================
rem  3. Resolve the state file, the log file and the temp workspace
rem ===========================================================================
call :timestamp
set "RUN_TS=%TS_FILE%"

rem  The default state file deliberately does NOT live under .claude\ : the CLI
rem  treats everything in that folder as sensitive and refuses to Write or Edit
rem  it in a non-interactive run, which silently breaks the whole state protocol.
if not defined STATE_ARG set "STATE_ARG=%WORK_DIR%\run-claude-state.md"
for %%F in ("%STATE_ARG%") do (
    set "STATE_FILE=%%~fF"
    set "STATE_DIR=%%~dpF"
)
if not exist "%STATE_DIR%." mkdir "%STATE_DIR%." 2>nul
if not exist "%STATE_DIR%." goto err_state_dir
if "%STATE_DIR:~-1%"=="\" set "STATE_DIR=%STATE_DIR:~0,-1%"

if not defined LOG_ARG set "LOG=%WORK_DIR%\run-claude-%RUN_TS%.log"
if defined LOG_ARG call :resolve_log "%LOG_ARG%"
for %%F in ("%LOG%") do set "LOG_PARENT=%%~dpF"
if not exist "%LOG_PARENT%." mkdir "%LOG_PARENT%." 2>nul
if not exist "%LOG_PARENT%." goto err_log_dir
>>"%LOG%" echo. 2>nul
if errorlevel 1 goto err_log_file

set "TMP_DIR=%TEMP%\run-claude-%RUN_TS%"
if not exist "%TMP_DIR%." mkdir "%TMP_DIR%." 2>nul
if not exist "%TMP_DIR%." set "TMP_DIR=%STATE_DIR%"

rem ===========================================================================
rem  4. Single instance lock, so two runs cannot fight over the same state
rem     file. Handle 9 is held open on the lock file for the whole run: a
rem     second run cannot open it and stops. The operating system releases it
rem     when this process ends, so a crash can never leave a stale lock.
rem ===========================================================================
set "LOCK_FILE=%STATE_DIR%\run-claude.lock"
rem  Runner stderr goes to its own file, not to the log: the block redirect
rem  would hold the log open and every append inside the run would fail.
set "MAIN_STARTED="
set "ERR_FILE=%TMP_DIR%\rc-runner-stderr.txt"
2>"%ERR_FILE%" ( 9>"%LOCK_FILE%" call :main_body )
if not defined MAIN_STARTED goto err_locked
call :flush_stderr
call :cleanup_tmp
endlocal & exit /b %EXIT_CODE%

rem ===========================================================================
rem  5. Run header, then prepare the state file
rem ===========================================================================
:main_body
set "MAIN_STARTED=1"
>&9 echo run-claude.bat holds this lock while it runs. Started %RUN_TS%.

call :now
call :log "==========================================================================="
call :log "run-claude.bat started at %NOW_STR%"
call :log "==========================================================================="
if defined PROMPT_FILE call :log "Prompt source    : file - %PROMPT_FILE%"
if not defined PROMPT_FILE call :log "Prompt source    : inline text"
if defined PROMPT_FILE call :warn_prompt_encoding
call :log "Working directory: %WORK_DIR%"
call :log "State file       : %STATE_FILE%"
call :log "Log file         : %LOG%"
call :log "Claude executable: %CLAUDE_EXE%"
call :log "Claude flags     : -p %DEFAULT_FLAGS%"
call :log "                   --add-dir %STATE_DIR%"
if defined USER_FLAGS call :log_var "                   your -f flags: " USER_FLAGS
if defined TARGET_TIME     call :log "Target start time: %TARGET_TIME%"
if not defined TARGET_TIME call :log "Target start time: none - starting immediately"

if "%INTERVAL_MIN%"=="0" call :log_loop_off
if not "%INTERVAL_MIN%"=="0" call :log_loop_on

rem normalise the iteration budget: MAX_RUNS=0 means unlimited
if not "%INTERVAL_MIN%"=="0" if not defined MAX_RUNS set "MAX_RUNS=0"
if "%INTERVAL_MIN%"=="0" if not defined MAX_RUNS set "MAX_RUNS=1"

call :prepare_state
call :log "---------------------------------------------------------------------------"

rem ===========================================================================
rem  6. Wait for the target start time
rem ===========================================================================
if defined TARGET_TIME call :wait_target

rem ===========================================================================
rem  7. Main loop - strictly sequential, one iteration can never overlap the
rem     next one because the interval only starts after claude has exited
rem ===========================================================================
set "ITER=0"
set "OK_COUNT=0"
set "FAIL_COUNT=0"

:loop
set /a ITER+=1
if not "%MAX_RUNS%"=="0" if %ITER% GTR %MAX_RUNS% goto loop_done

set "ITER_LABEL=%ITER%"
if not "%MAX_RUNS%"=="0" set "ITER_LABEL=%ITER% of %MAX_RUNS%"

call :now
set "ITER_START_STR=%NOW_STR%"
set "ITER_START_EPOCH=%NOW_EPOCH%"
call :log ""
call :log "=== Iteration %ITER_LABEL% - started %ITER_START_STR% ==="

call :run_once

call :now
set /a DURATION=%NOW_EPOCH%-%ITER_START_EPOCH%
if "%CLAUDE_RC%"=="0" call :iter_ok
if not "%CLAUDE_RC%"=="0" call :iter_failed

rem --- has claude declared the whole task finished? ------------------------
call :check_complete
if not errorlevel 1 (
    call :log ""
    call :log "State file reports TASK_STATUS: COMPLETE - stopping the loop."
    goto loop_done
)

rem --- another iteration? --------------------------------------------------
if not "%MAX_RUNS%"=="0" if %ITER% GEQ %MAX_RUNS% goto loop_done
if "%INTERVAL_MIN%"=="0" goto loop

set /a WAIT_SECS=%INTERVAL_MIN%*60
call :next_run_time %WAIT_SECS%
call :log "Waiting %INTERVAL_MIN% minutes - next iteration at about %NEXT_RUN%"
call :sleep %WAIT_SECS%
goto loop

:loop_done
set /a TOTAL=%OK_COUNT%+%FAIL_COUNT%
call :now
call :log ""
call :log "---------------------------------------------------------------------------"
call :log "run-claude.bat finished at %NOW_STR%"
call :log "Iterations: %TOTAL% run, %OK_COUNT% succeeded, %FAIL_COUNT% failed"
call :log "State file: %STATE_FILE%"
call :log "Log file  : %LOG%"
call :log "==========================================================================="
if not "%FAIL_COUNT%"=="0" call :log "[ERROR] %FAIL_COUNT% iteration/s failed - search the log for [ERROR] and [QUOTA]."
rem back to the lock block, which releases the lock. EXIT_CODE carries the result.
exit /b 0


rem ===========================================================================
rem  Subroutines
rem ===========================================================================

rem --- one claude execution -------------------------------------------------
:run_once
set "CLAUDE_RC=0"
set "PROMPT_BUILD=%TMP_DIR%\rc-prompt-%ITER%.txt"
set "OUT_FILE=%TMP_DIR%\rc-out-%ITER%.txt"
call :build_prompt "%PROMPT_BUILD%"
if errorlevel 1 (
    call :log "[ERROR] Could not build the prompt for this iteration - it was skipped."
    set "CLAUDE_RC=90"
    goto :eof
)

call :log "--- claude output ---"
rem  The flags are written out in full here on purpose. Storing them in one
rem  variable would embed quotes in its value, and expanding that value on a
rem  command line breaks as soon as a path contains a space or an ampersand.
rem  The prompt is fed in with < instead of "type ... |" for the same reason:
rem  a pipe would hand the quoted paths to a second cmd, which re-parses them.
rem  Redirection also keeps ERRORLEVEL as the exit code of claude itself.
rem  claude runs inside its own cmd on purpose. It is often a .cmd shim, and a
rem  batch file started from here without that isolation could take this script
rem  down with it. cmd /c keeps the damage inside the child and still gives back
rem  the real exit code.
pushd "%WORK_DIR%"
cmd /c %CLAUDE_EXE% -p %DEFAULT_FLAGS% --add-dir "%STATE_DIR%" %USER_FLAGS% < "%PROMPT_BUILD%" > "%OUT_FILE%" 2>&1
set "CLAUDE_RC=%ERRORLEVEL%"
popd

if exist "%OUT_FILE%" (
    type "%OUT_FILE%"
    type "%OUT_FILE%" >> "%LOG%"
)
call :log "--- end of claude output ---"

rem --- make quota / rate limit / overload trouble impossible to miss -------
if not exist "%OUT_FILE%" goto :eof
findstr /i /c:"usage limit" /c:"rate limit" /c:"rate_limit" /c:"quota" /c:"credit balance" /c:"insufficient credit" /c:"too many requests" /c:"overloaded" /c:"exceeded your" "%OUT_FILE%" >nul 2>&1
if errorlevel 1 goto :eof
call :log "[QUOTA] *** Possible quota, rate limit or overload problem in the claude output above."
call :log "[QUOTA] *** Check your usage before trusting the result of this iteration."
goto :eof

rem --- is the task finished? FIRST LINE of the state file only -------------
rem     A whole file search is wrong here. The protocol sent to claude says
rem     "write TASK_STATUS: COMPLETE on the first line only when ...", so claude
rem     routinely restates that sentence inside the state file - under ## Goal,
rem     or in a note to its future self. A file wide findstr matches that prose
rem     and stops the loop after one iteration while line 1 still says
rem     IN_PROGRESS, and the runner then exits 0 as if all was well. Observed on
rem     2026-07-30. for /f skips blank lines, so this reads the first non-empty
rem     line, and /b anchors the match to the start of it.
rem     PowerShell does the reading, for the same reason it does the time
rem     handling: Get-Content -TotalCount 1 gives exactly line 1 and transparently
rem     eats a UTF-8 BOM. A batch "findstr /b" on the first line is defeated by a
rem     BOM - the three BOM bytes sit before the T, so the anchor never matches
rem     and the loop would then never stop. Verified both ways on 2026-07-30.
:check_complete
set "RC_STATE=%STATE_FILE%"
%PS% -NoProfile -NonInteractive -Command "$l = Get-Content -LiteralPath $env:RC_STATE -TotalCount 1; if ($l -match '^\s*TASK_STATUS:\s*COMPLETE\b') { exit 0 } else { exit 1 }" <nul
exit /b %ERRORLEVEL%

:iter_ok
set /a OK_COUNT+=1
call :log "=== Iteration %ITER_LABEL% finished %NOW_STR% - exit code 0 - %DURATION%s ==="
goto :eof

:iter_failed
set /a FAIL_COUNT+=1
set "EXIT_CODE=1"
call :log "[ERROR] === Iteration %ITER_LABEL% FAILED at %NOW_STR% - claude exit code %CLAUDE_RC% - %DURATION%s ==="
call :log "[ERROR] The runner is NOT stopping. The claude output above holds the reason."
goto :eof

rem --- build the prompt that is piped into claude --------------------------
:build_prompt
set "CP=%~1"
call :write_prompt_head
if not exist "%CP%" exit /b 1
type "%STATE_FILE%" >> "%CP%" 2>nul
call :write_prompt_tail
if defined PROMPT_FILE goto bp_file
set "RC_COMPOSED=%CP%"
rem  PowerShell reads both values straight out of the environment, so no prompt
rem  text ever has to survive another round of cmd quoting.
%PS% -NoProfile -NonInteractive -Command "[System.IO.File]::AppendAllText($env:RC_COMPOSED, $env:PROMPT_ARG + [Environment]::NewLine)"
if errorlevel 1 exit /b 1
exit /b 0
:bp_file
type "%PROMPT_FILE%" >> "%CP%"
if errorlevel 1 exit /b 1
exit /b 0

:write_prompt_head
setlocal EnableDelayedExpansion
>  "!CP!" echo(# Unattended automated run
>> "!CP!" echo(
>> "!CP!" echo(You were started by the script run-claude.bat with the -p flag.
>> "!CP!" echo(Nobody is watching the terminal: never ask a question and never wait for
>> "!CP!" echo(confirmation. Decide on your own and write down what you decided.
>> "!CP!" echo(
>> "!CP!" echo(Iteration: !ITER_LABEL!
>> "!CP!" echo(Started: !ITER_START_STR!
>> "!CP!" echo(Working directory: !WORK_DIR!
>> "!CP!" echo(State file: !STATE_FILE!
>> "!CP!" echo(
>> "!CP!" echo(## State protocol - read this first
>> "!CP!" echo(
>> "!CP!" echo(The state file above is the only memory shared between iterations. Its
>> "!CP!" echo(current contents are copied under CURRENT STATE below.
>> "!CP!" echo(
>> "!CP!" echo(1. Start from CURRENT STATE. Continue where the previous iteration stopped
>> "!CP!" echo(   and never redo work that is already listed as completed.
>> "!CP!" echo(2. Whenever you make progress, update the state file with Write or Edit.
>> "!CP!" echo(   Do it as you go, not only at the end, so an interrupted run is not lost.
>> "!CP!" echo(3. Keep the state file factual, self contained and under about 200 lines.
>> "!CP!" echo(   A fresh session must be able to continue from it alone.
>> "!CP!" echo(4. Keep this layout in the state file:
>> "!CP!" echo(      TASK_STATUS: IN_PROGRESS
>> "!CP!" echo(      ## Goal
>> "!CP!" echo(      ## Completed
>> "!CP!" echo(      ## In progress
>> "!CP!" echo(      ## Next steps
>> "!CP!" echo(      ## Notes and blockers
>> "!CP!" echo(5. Write TASK_STATUS: COMPLETE on the first line only when the whole task is
>> "!CP!" echo(   really finished. The runner stops looping as soon as it sees COMPLETE, so
>> "!CP!" echo(   never write it while work remains.
>> "!CP!" echo(6. If you are blocked, keep TASK_STATUS: IN_PROGRESS, describe the blocker
>> "!CP!" echo(   under Notes and blockers and record the smallest useful next step.
>> "!CP!" echo(7. Work in sensible chunks. Stopping this iteration once a meaningful piece
>> "!CP!" echo(   of work is done is fine, as long as the state file is up to date first.
>> "!CP!" echo(
>> "!CP!" echo(## CURRENT STATE - !STATE_FILE!
>> "!CP!" echo(
>> "!CP!" echo(```markdown
endlocal
goto :eof

:write_prompt_tail
setlocal EnableDelayedExpansion
>> "!CP!" echo(```
>> "!CP!" echo(
>> "!CP!" echo(## TASK
>> "!CP!" echo(
endlocal
goto :eof

rem --- warn when the prompt file is not UTF-8 ------------------------------
rem     :bp_file copies the prompt file into the composed prompt with type,
rem     which is a byte for byte copy for UTF-8 - good - but for a UTF-16 file
rem     cmd converts it to the console codepage instead. On a Hebrew console
rem     (862) every non ASCII character then reaches claude as mojibake while
rem     the run still reports exit 0. Measured on 2026-07-30, see landmine 15.
rem     A UTF-16 BOM is detectable so it is reported. ANSI text carries no BOM
rem     and cannot be told apart from UTF-8, which is why -h asks for UTF-8.
:warn_prompt_encoding
set "RC_PFILE=%PROMPT_FILE%"
%PS% -NoProfile -NonInteractive -Command "try { $b = [IO.File]::ReadAllBytes($env:RC_PFILE) } catch { exit 0 }; if ($b.Length -ge 2 -and (($b[0] -eq 255 -and $b[1] -eq 254) -or ($b[0] -eq 254 -and $b[1] -eq 255))) { exit 1 }; exit 0" <nul
if not errorlevel 1 goto :eof
call :log "[WARN] The prompt file begins with a UTF-16 byte order mark."
call :log "[WARN] cmd converts UTF-16 to the console codepage on the way in, so every"
call :log "[WARN] non ASCII character will reach claude corrupted. Save it as UTF-8."
goto :eof

rem --- create the state file, or back up the old one and start clean -------
:prepare_state
if not exist "%STATE_FILE%" (
    call :log "State file       : created new"
    call :write_state_template
    goto :eof
)
if "%RESUME_STATE%"=="1" (
    call :log "State file       : keeping the existing file, -r was given"
    goto :eof
)
set "STATE_BACKUP=%STATE_FILE%.%RUN_TS%.bak"
move /y "%STATE_FILE%" "%STATE_BACKUP%" >nul 2>&1
if errorlevel 1 (
    call :log "[WARN] Could not back up the existing state file - it is reused as is."
    goto :eof
)
call :log "State file       : old state backed up to %STATE_BACKUP%"
call :log "                   a new run starts clean - pass -r to continue an old task"
call :write_state_template
goto :eof

:write_state_template
setlocal EnableDelayedExpansion
>  "!STATE_FILE!" echo(TASK_STATUS: IN_PROGRESS
>> "!STATE_FILE!" echo(
>> "!STATE_FILE!" echo(## Goal
>> "!STATE_FILE!" echo(
>> "!STATE_FILE!" echo(See the TASK section of the prompt supplied by run-claude.bat.
>> "!STATE_FILE!" echo(Restate it here in your own words during the first iteration.
>> "!STATE_FILE!" echo(
>> "!STATE_FILE!" echo(## Completed
>> "!STATE_FILE!" echo(
>> "!STATE_FILE!" echo(- nothing yet
>> "!STATE_FILE!" echo(
>> "!STATE_FILE!" echo(## In progress
>> "!STATE_FILE!" echo(
>> "!STATE_FILE!" echo(- nothing yet
>> "!STATE_FILE!" echo(
>> "!STATE_FILE!" echo(## Next steps
>> "!STATE_FILE!" echo(
>> "!STATE_FILE!" echo(- read the task and plan the first chunk of work
>> "!STATE_FILE!" echo(
>> "!STATE_FILE!" echo(## Notes and blockers
>> "!STATE_FILE!" echo(
>> "!STATE_FILE!" echo(- state file created by run-claude.bat on !NOW_STR!
endlocal
goto :eof

rem --- wait until the requested start time ---------------------------------
:wait_target
set "RC_TARGET=%TARGET_TIME%"
set "WAIT_SECS=0"
for /f "usebackq tokens=* delims=" %%A in (`%PS% -NoProfile -NonInteractive -Command "[math]::Max(0,[math]::Ceiling(([datetime]::ParseExact($env:RC_TARGET,'yyyy-MM-dd HH:mm',$null) - (Get-Date)).TotalSeconds))"`) do set "WAIT_SECS=%%A"
if "%WAIT_SECS%"=="0" (
    call :log "Target start time %TARGET_TIME% is already in the past - starting now."
    goto :eof
)
call :log "Waiting %WAIT_SECS% seconds until %TARGET_TIME% before the first iteration."
call :sleep %WAIT_SECS%
call :now
call :log "Woke up at %NOW_STR% - starting."
goto :eof

rem --- sleep, with no keypress and no prompt ------------------------------
:sleep
if "%~1"=="" goto :eof
if %~1 LEQ 0 goto :eof
%PS% -NoProfile -NonInteractive -Command "Start-Sleep -Seconds %~1" <nul
goto :eof

rem --- NEXT_RUN = now + N seconds ------------------------------------------
:next_run_time
set "NEXT_RUN=unknown"
for /f "usebackq tokens=* delims=" %%A in (`%PS% -NoProfile -NonInteractive -Command "(Get-Date).AddSeconds(%~1).ToString('yyyy-MM-dd HH:mm:ss')"`) do set "NEXT_RUN=%%A"
goto :eof

rem --- NOW_STR and NOW_EPOCH ----------------------------------------------
:now
set "NOW_STR=unknown"
set "NOW_EPOCH=0"
for /f "usebackq tokens=1,2,3 delims= " %%A in (`%PS% -NoProfile -NonInteractive -Command "(Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' ' + [DateTimeOffset]::Now.ToUnixTimeSeconds()"`) do (
    set "NOW_STR=%%A %%B"
    set "NOW_EPOCH=%%C"
)
goto :eof

rem --- TS_FILE: a timestamp that is safe inside a file name ---------------
:timestamp
set "TS_FILE="
for /f "usebackq tokens=* delims=" %%A in (`%PS% -NoProfile -NonInteractive -Command "(Get-Date).ToString('yyyyMMdd-HHmmss')"`) do set "TS_FILE=%%A"
if not defined TS_FILE set "TS_FILE=run"
goto :eof

rem --- write one line to the console and append it to the log -------------
:log
setlocal EnableDelayedExpansion
set "MSG=%~1"
if "!MSG!"=="" (
    echo(
    >> "!LOG!" echo(
    endlocal & goto :eof
)
echo(!MSG!
>> "!LOG!" echo(!MSG!
endlocal
goto :eof

rem --- log a label plus the value of a variable ---------------------------
rem     Used when the value may contain quotes or ampersands: passing it on a
rem     call line would break the quoting, so only the variable NAME travels.
:log_var
setlocal EnableDelayedExpansion
set "LBL=%~1"
set "VAL=!%~2!"
echo(!LBL!!VAL!
>> "!LOG!" echo(!LBL!!VAL!
endlocal
goto :eof

:log_loop_off
if not defined MAX_RUNS call :log "Loop             : off - one single execution"
if defined MAX_RUNS if "%MAX_RUNS%"=="1" call :log "Loop             : off - one single execution"
if defined MAX_RUNS if not "%MAX_RUNS%"=="1" call :log "Loop             : %MAX_RUNS% iterations back to back, -i is 0 so there is no wait"
goto :eof

:log_loop_on
if defined MAX_RUNS call :log "Loop             : every %INTERVAL_MIN% minutes, %MAX_RUNS% iterations"
if not defined MAX_RUNS call :log "Loop             : every %INTERVAL_MIN% minutes, unlimited - stop with Ctrl+C"
goto :eof

rem --- -l may be a folder or a full file path -----------------------------
:resolve_log
set "LV=%~1"
set "LV_ATTR="
for %%F in ("%LV%") do set "LV_ATTR=%%~aF"
rem an existing directory: the log file goes inside it
if defined LV_ATTR if /i "%LV_ATTR:~0,1%"=="d" goto rl_folder
rem a trailing backslash: a folder that does not exist yet
if "%LV:~-1%"=="\" goto rl_folder
rem it has an extension: use it as the log file itself
set "LV_EXT="
for %%F in ("%LV%") do set "LV_EXT=%%~xF"
if defined LV_EXT goto rl_file
:rl_folder
for %%F in ("%LV%\.") do set "LOG=%%~fF\run-claude-%RUN_TS%.log"
goto :eof
:rl_file
for %%F in ("%LV%") do set "LOG=%%~fF"
goto :eof

rem --- report anything the runner itself wrote to stderr ------------------
:flush_stderr
if not defined ERR_FILE goto :eof
if not exist "%ERR_FILE%" goto :eof
for %%Z in ("%ERR_FILE%") do if %%~zZ EQU 0 goto :eof
call :log "[WARN] The runner itself reported these messages on stderr:"
type "%ERR_FILE%"
type "%ERR_FILE%" >> "%LOG%"
goto :eof

:cleanup_tmp
if not defined TMP_DIR goto :eof
if not exist "%TMP_DIR%\." goto :eof
del /q "%TMP_DIR%\rc-*" >nul 2>&1
rmdir "%TMP_DIR%" >nul 2>&1
goto :eof

rem --- small predicates ---------------------------------------------------
:is_number
echo %~1| findstr /r /c:"^[0-9][0-9]*$" >nul 2>&1
exit /b %ERRORLEVEL%

:check_count
call :is_number "%MAX_RUNS%"
if errorlevel 1 exit /b 1
if %MAX_RUNS% LEQ 0 exit /b 1
exit /b 0

:check_target
set "RC_TARGET=%TARGET_TIME%"
%PS% -NoProfile -NonInteractive -Command "try { [void][datetime]::ParseExact($env:RC_TARGET,'yyyy-MM-dd HH:mm',$null); exit 0 } catch { exit 1 }"
exit /b %ERRORLEVEL%

:is_date_only
echo %~1| findstr /r /c:"^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$" >nul 2>&1
exit /b %ERRORLEVEL%

:is_hhmm
echo %~1| findstr /r /c:"^[0-9][0-9]*:[0-9][0-9]$" >nul 2>&1
exit /b %ERRORLEVEL%

:append_time
set "TARGET_TIME=%TARGET_TIME% %~1"
goto :eof

rem --- print one line safely, whatever characters it contains -------------
rem     User supplied text must never reach an unquoted echo: a < > | or &
rem     inside it would be executed instead of printed.
:say
setlocal EnableDelayedExpansion
set "M=%~1"
if "!M!"=="" (
    echo(
) else (
    echo(!M!
)
endlocal
goto :eof

rem --- errors and usage ---------------------------------------------------
:err_missing_value
call :say "[ERROR] This option requires a value:"
call :say "        %A%"
endlocal & exit /b 2

:err_extra_arg
call :say "[ERROR] Unexpected argument:"
call :say "        %A%"
call :say "        The prompt is one single argument - quote it if it has spaces."
endlocal & exit /b 2

:err_interval
call :say "[ERROR] -i must be a whole number of minutes. Got:"
call :say "        %INTERVAL_MIN%"
endlocal & exit /b 2

:err_count
call :say "[ERROR] -c must be a whole number greater than 0. Got:"
call :say "        %MAX_RUNS%"
endlocal & exit /b 2

:err_i_needs_c
call :say "[ERROR] -i requires -c. -i only says how long to wait between"
call :say "        iterations, so on its own it never says when to stop."
call :say "        Add -c with an iteration count, or drop -i for a single run."
endlocal & exit /b 2

:err_c_needs_i
call :say "[ERROR] -c requires -i. -c only says how many iterations to run, so"
call :say "        on its own it never says how long to wait between them."
call :say "        Add -i with a minute count - use -i 0 to run them back to"
call :say "        back - or drop -c for a single run."
endlocal & exit /b 2

:err_target
call :say "[ERROR] -t must look like YYYY-MM-DD HH:MM and be quoted. Got:"
call :say "        %TARGET_TIME%"
endlocal & exit /b 2

:err_workdir
call :say "[ERROR] Cannot use this working directory, -d:"
call :say "        %WORK_DIR%"
endlocal & exit /b 2

:err_prompt_dir
call :say "[ERROR] The prompt argument is a directory. Give the prompt text or the"
call :say "        path of a file that contains it. Got:"
call :say "        %PROMPT_ARG%"
endlocal & exit /b 2

:err_state_dir
call :say "[ERROR] Cannot create the directory of the state file, -s:"
call :say "        %STATE_DIR%"
endlocal & exit /b 2

:err_log_dir
call :say "[ERROR] Cannot create the log directory, -l:"
call :say "        %LOG_PARENT%"
endlocal & exit /b 2

:err_log_file
call :say "[ERROR] Cannot write to the log file, -l:"
call :say "        %LOG%"
endlocal & exit /b 2

:err_locked
call :say "[ERROR] Another run-claude.bat is already running on this state file, so"
call :say "        this one refuses to start. Two runs would overwrite each other."
call :say "        State file: %STATE_FILE%"
call :say "        Lock file : %LOCK_FILE%"
call :say "        Use a different -s state file to run a second task in parallel."
call :cleanup_tmp
endlocal & exit /b 3

:usage_err
call :print_usage
endlocal & exit /b 2

:usage
call :print_usage
endlocal & exit /b 0

:print_usage
echo.
echo run-claude.bat - run the Claude Code CLI unattended, once or in a loop.
echo.
echo Usage:
echo   run-claude.bat "<prompt or prompt-file>" [options]
echo.
echo Mandatory:
echo   ^<prompt^>               The task for claude: either the prompt text itself,
echo                          quoted, or the path of a file holding the prompt.
echo.
echo Options:
echo   -t "YYYY-MM-DD HH:MM"  Start at this time. Omitted = start immediately.
echo   -i ^<minutes^>           Minutes to wait between iterations. Requires -c.
echo                          Use -i 0 to run the iterations back to back. The
echo                          wait starts only after an iteration has ended, so
echo                          iterations never overlap.
echo   -c ^<count^>             Total number of iterations, must be greater than 0.
echo                          Requires -i. Omit both -i and -c for a single run.
echo   -d ^<dir^>               Working directory for claude. Default: the directory
echo                          run-claude.bat was invoked from.
echo   -f "<flags>"           Extra claude CLI flags, appended after the default
echo                          --allowed-tools=Edit,Write
echo   -l ^<folder or file^>    Log destination. A folder receives
echo                          run-claude-^<timestamp^>.log; a path with an extension
echo                          is used as the log file itself. Default:
echo                          ^<workdir^>\run-claude-^<timestamp^>.log
echo   -s ^<file^>              State file. Default: ^<workdir^>\run-claude-state.md
echo                          A new run backs up an existing state file and starts
echo                          from a clean one. Do not put it inside a .claude
echo                          folder: the CLI refuses to write there unattended.
echo   -r                     Resume: keep the existing state file instead of
echo                          backing it up and starting clean.
echo   -h                     Show this help.
echo.
echo Behaviour:
echo   * Every iteration receives the current state file inside its prompt and is
echo     told to update it, so a loop keeps making progress on one single task.
echo   * The loop stops early when the state file says TASK_STATUS: COMPLETE.
echo   * A failing claude call never stops the runner. Its exit code, its output
echo     and any quota or rate limit wording are printed and written to the log,
echo     marked with [ERROR] and [QUOTA].
echo   * Everything claude prints plus every runner action goes to the log file.
echo   * Nothing ever waits for a keypress.
echo   * A lock file next to the state file prevents a second run from working on
echo     the same state at the same time. It stays on disk between runs, which is
echo     normal, and it can never go stale: Windows releases it when the run ends.
echo   * Exit code: 0 all iterations fine, 1 at least one claude call failed,
echo     2 wrong parameters, 3 another run holds the lock.
echo.
echo Quoting, the cmd.exe facts of life:
echo   * An inline prompt may contain ^& ^| ^< ^> ^( ^) and ^!. A prompt that contains
echo     double quotes, or a ^%% sign while you call this script from another .bat,
echo     is safer in a prompt FILE - cmd mangles those before the script sees them.
echo   * -t always needs its quotes: -t "2026-08-01 22:00"
echo   * Save a prompt FILE as UTF-8. It is copied into the composed prompt as
echo     raw bytes, which is right for UTF-8, but cmd converts UTF-16 to the
echo     console codepage on the way in, so non ASCII text would reach claude
echo     corrupted. A UTF-16 byte order mark is detected and reported as [WARN].
echo     ANSI text carries no mark and cannot be detected at all - if your task
echo     file has Hebrew or any accented character in it, save it as UTF-8.
echo.
echo Examples:
echo   run-claude.bat "Add unit tests for the parser module"
echo   run-claude.bat task.md -i 30 -c 8 -d C:\work\myrepo -l C:\logs
echo   run-claude.bat task.md -t "2026-08-01 22:00" -i 60 -c 12 -f "--model opus"
echo   run-claude.bat task.md -i 20 -c 5 -r
echo.
goto :eof
