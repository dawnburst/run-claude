@echo off
setlocal EnableDelayedExpansion
rem ===========================================================================
rem  claude.cmd - a FAKE Claude Code CLI. Used only by run-tests.bat.
rem
rem  It never contacts anything and costs nothing. It records how it was called
rem  and then behaves exactly as the current STUB_* environment variables say,
rem  which lets the suite provoke situations the real CLI cannot be asked for on
rem  demand - a nonzero exit, quota wording, a slow call that holds the lock.
rem
rem  Defensive rules from CLAUDE.md section 6b. Do not relax them: more than one
rem  false alarm during development came from a careless stub, not the runner.
rem    * never  echo %CD%  and never  echo %*  - a path holding & is executed
rem    * never  set "X=%*"
rem    * print every value through a variable, under delayed expansion
rem    * redirect before echo, so a message ending in a digit is not read as a
rem      handle redirect  (landmine 5)
rem
rem  Inputs, all optional:
rem    STUB_DIR          where to record the calls   default %TEMP%\rc-stub
rem    STUB_COUNT_FILE   file holding the call counter
rem    STUB_STATE_FILE   the state file this stub is allowed to write
rem    STUB_RC           exit code to return         default 0
rem    STUB_OUT          one extra line to print
rem    STUB_SLEEP        seconds to stay alive, to hold the lock
rem    STUB_STATE        append a progress line to the state file
rem    STUB_COMPLETE     write a state file whose FIRST line is COMPLETE
rem    STUB_COMPLETE_AT  do that only on this call number
rem    STUB_PROSE        write a state file that says IN_PROGRESS on line 1 but
rem                      mentions TASK_STATUS: COMPLETE further down. This is
rem                      the landmine 14 fixture - the runner must NOT stop.
rem
rem  Outputs, inside STUB_DIR:
rem    args-N.txt        the argument list of call N
rem    prompt-N.txt      the prompt the runner composed for call N, from stdin
rem ===========================================================================

if not defined STUB_DIR set "STUB_DIR=%TEMP%\rc-stub"
if not exist "!STUB_DIR!\." mkdir "!STUB_DIR!" 2>nul

rem --- which call is this one? ---------------------------------------------
set "N=1"
if defined STUB_COUNT_FILE if exist "!STUB_COUNT_FILE!" (
    set /p N=<"!STUB_COUNT_FILE!"
    set /a N+=1
)
if defined STUB_COUNT_FILE >"!STUB_COUNT_FILE!" echo(!N!

rem --- record the arguments, one bracketed token each -----------------------
rem     %* is avoided on purpose, see the header
set "ARGS="
:cap
if "%~1"=="" goto cap_done
set "ARGS=!ARGS! [%~1]"
shift
goto cap
:cap_done
>"!STUB_DIR!\args-!N!.txt" echo(!ARGS!

rem  args-N.txt is per token and therefore LIES about tokens holding = or , :
rem  batch splits %1 on space, comma, semicolon AND equals, so the real
rem  --allowed-tools=Edit,Write arrives here as [--allowed-tools] [Edit] [Write].
rem  A real .exe receives it as one argument. So the raw command line is
rem  recorded too, and that is what a test should assert on.
set "RAW=!CMDCMDLINE!"
>"!STUB_DIR!\cmdline-!N!.txt" echo(!RAW!

rem --- record the composed prompt that arrived on stdin ---------------------
findstr "^" > "!STUB_DIR!\prompt-!N!.txt"

rem --- say something, the runner captures and logs it ------------------------
set "LINE=stub claude call !N!"
echo(!LINE!
if defined STUB_OUT echo(!STUB_OUT!

rem --- optionally act on the state file --------------------------------------
if not defined STUB_STATE_FILE goto after_state
if defined STUB_STATE >>"!STUB_STATE_FILE!" echo(- stub call !N! recorded some progress

set "DO_COMPLETE="
if defined STUB_COMPLETE set "DO_COMPLETE=1"
if defined STUB_COMPLETE_AT (
    set "DO_COMPLETE="
    if "!STUB_COMPLETE_AT!"=="!N!" set "DO_COMPLETE=1"
)
if defined DO_COMPLETE call :write_complete
if defined STUB_PROSE call :write_prose
:after_state

rem --- optionally stay alive, so another run meets the lock ------------------
if defined STUB_SLEEP powershell.exe -NoProfile -NonInteractive -Command "Start-Sleep -Seconds !STUB_SLEEP!" <nul

set "RC=0"
if defined STUB_RC set "RC=!STUB_RC!"
endlocal & exit /b %RC%

rem ===========================================================================
:write_complete
>"!STUB_STATE_FILE!"  echo(TASK_STATUS: COMPLETE
>>"!STUB_STATE_FILE!" echo(
>>"!STUB_STATE_FILE!" echo(## Completed
>>"!STUB_STATE_FILE!" echo(
>>"!STUB_STATE_FILE!" echo(- the stub declared the task finished on call !N!
goto :eof

rem  Line 1 says IN_PROGRESS, but the words TASK_STATUS: COMPLETE appear lower
rem  down, exactly the way real claude restates the protocol back into its own
rem  state file. A whole file search matches this and stops the loop after one
rem  iteration while four fifths of the work is still outstanding.
:write_prose
>"!STUB_STATE_FILE!"  echo(TASK_STATUS: IN_PROGRESS
>>"!STUB_STATE_FILE!" echo(
>>"!STUB_STATE_FILE!" echo(## Goal
>>"!STUB_STATE_FILE!" echo(
>>"!STUB_STATE_FILE!" echo(Five steps, one per run. Only after step 5 is written
>>"!STUB_STATE_FILE!" echo(may the first line of this file become
>>"!STUB_STATE_FILE!" echo(TASK_STATUS: COMPLETE.
>>"!STUB_STATE_FILE!" echo(
>>"!STUB_STATE_FILE!" echo(## Completed
>>"!STUB_STATE_FILE!" echo(
>>"!STUB_STATE_FILE!" echo(- stub call !N!
goto :eof
