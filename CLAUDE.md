# run-claude.bat - project context and handoff

You are picking up development of `run-claude.bat`, a Windows batch script that
runs the Claude Code CLI unattended. This file is the complete handoff: the spec,
the current state, the architecture, the cmd.exe landmines that are already
solved, and how to test. Read it fully before editing the script.

The previous session developed and tested the script from WSL by driving
`cmd.exe` over interop. You are running inside Windows cmd directly, which makes
testing easier: run `.bat` files natively instead of through interop.

---

## 1. What the script is for

The user schedules long-running Claude Code work on Windows and wants it to
survive unattended: start at a chosen time, repeat on an interval, carry progress
across iterations through a state file, log everything, and never die because a
single `claude` call failed (quota limits in particular).

Command line:

```
run-claude.bat "<prompt or prompt-file>" [-t "YYYY-MM-DD HH:MM"] [-i minutes]
               [-c count] [-d workdir] [-f "flags"] [-l logfolder]
               [-s statefile] [-r]
```

The original requirements, all implemented:

| Param | Meaning |
|---|---|
| positional | **Mandatory.** The prompt text itself, or the path of a file containing the prompt. The only mandatory parameter. |
| `-t` | Target start time, format `YYYY-MM-DD HH:MM`. Omitted = start immediately. |
| `-i` | Minutes between loop iterations. **Requires `-c`.** `-i 0` runs the iterations back to back. Omitted (with `-c` also omitted) = run once. |
| `-c` | Total iterations when looping. **Requires `-i`.** If given, must be > 0. |
| `-d` | Working directory for claude. Omitted = the directory `run-claude.bat` was invoked from. |
| `-f` | Extra claude CLI flags. `--allowed-tools=Edit,Write` is always on by default; `-f` is appended after it. |
| `-l` | Log destination. Accepts a folder (gets `run-claude-<timestamp>.log`) or a full file path. Omitted = `<workdir>\run-claude-<timestamp>.log`. Captures all claude output plus every runner action. |
| `-s` | State file. Omitted = `<workdir>\run-claude-state.md`. A new run backs up an existing state file and starts clean. Must not sit inside a `.claude` folder - see landmine 13. |
| `-r` | **Added by the previous session, not in the original spec.** Resume: keep the existing state file instead of backing it up. Without it there was no way to continue an existing task, since the spec mandates a clean state per new run. |

**`-i` and `-c` are mutually required** (user request, 2026-07-30). Either both or
neither; each alone exits 2. This deliberately removed the old unlimited-loop
mode, where `-i` without `-c` looped until Ctrl+C - an unattended runner with no
stop condition was judged not worth keeping. `MAX_RUNS=0` still means unlimited
inside the loop, but nothing can set it now; the normalisation line that did so
is left in place as a defensive no-op.

Hard requirements from the user, treat these as invariants:

1. **Iterations must never overlap.** Satisfied structurally: the script is
   sequential, and the interval wait starts only after `claude` exits. A second
   *instance* is blocked by a lock (section 3).
2. **A failing claude call must never fail the script.** The error, its exit
   code, and its output are printed and logged; the loop continues. Quota and
   rate-limit wording is specifically detected and flagged `[QUOTA]`, because the
   user hits plan limits and needs to notice.
3. **Nothing may ever wait for a keypress.** No `pause`, no bare `timeout`; the
   prompt is fed via stdin redirection; waits use PowerShell `Start-Sleep`.

---

## 2. Current state

- `run-claude.bat` - 797 lines, complete and tested. **CRLF line endings, keep them.**
- `runner-test-task.md` - a deliberately 5-step task file used to exercise the
  loop (see section 6).
- `test\bin\claude.cmd` and `test\run-tests.bat` - the stub and the 40 case
  regression suite. Free and fast; run it after every edit (section 6b).
- Nothing is broken or half-finished. Any work you do is enhancement.

Environment as last verified:

- Claude Code native install, **v2.1.220**, at `%USERPROFILE%\.local\bin\claude.exe`.
- That folder was appended to the **user** PATH (`HKCU\Environment\Path`),
  preserving its `REG_EXPAND_SZ` type. A fresh cmd window resolves `claude`.
- `claude doctor` reported `No installation issues found.`
- Auth **is** done: `%USERPROFILE%\.claude\.credentials.json` exists and a real
  end-to-end run went through with no sign-in error. If that ever regresses, the
  user must run `claude auth login` once in a Windows cmd window; WSL credentials
  do not carry over to the Windows install.

Testing status, be precise about this with the user:

- All runner mechanics were verified on Windows against a **stub** `claude.cmd`:
  single run, back-to-back and timed loops (interval timing exact), future and
  past `-t` (quoted and unquoted), every validation error, `-l` as folder and as
  file, `-f` pass-through, state backup and `-r`, early completion stop,
  unlimited loop (that mode has since been removed), lock contention, lock
  release after a hard kill, and paths containing spaces, `&`, and `(x86)`.
- The exact invocation form was verified against the **real** CLI, but on Linux:
  `claude -p --allowed-tools=Edit,Write --add-dir <dir> < promptfile` gave exit 0
  with the prompt correctly read from redirected stdin.
- **A real single-iteration end-to-end run against the real Windows `claude.exe`
  now passes** (2026-07-30): exit 0, the requested file created, full claude
  output captured in the log, temp workspace cleaned up. That run is what exposed
  landmine 13 - the state file default had to move out of `.claude\`.
- **Real multi-iteration loops now pass too** (2026-07-30): `-i 1 -c 2` and
  `-i 0 -c 2` against `runner-test-task.md`, both with the real CLI. State
  genuinely carries across iterations - iteration 2 continued at step 2 and even
  acted on environment notes iteration 1 left for it. Interval measured from the
  *end* of the previous iteration: iteration 1 ended 13:35:52, iteration 2 began
  13:36:53. `-i 0` gave a zero-second gap. That test run is what exposed
  landmine 14.
- Still not exercised against the real CLI: a full 5-iteration run to
  `TASK_STATUS: COMPLETE`, `-r` resume, and a real quota/failure path. The stub
  covers all three.

---

## 3. Architecture

Sections in the file, in order:

1. **Parse arguments** (line ~34) - `goto`-based dispatch, one label per option.
2. **Validate arguments** (~124) - numeric checks, PowerShell presence, claude
   presence, work directory, `-t` format, prompt is file vs text.
3. **Resolve state file, log file, temp workspace** (~184).
4. **Single-instance lock** (~211) - wraps the whole run:
   ```bat
   set "MAIN_STARTED="
   set "ERR_FILE=%TMP_DIR%\rc-runner-stderr.txt"
   2>"%ERR_FILE%" ( 9>"%LOCK_FILE%" call :main_body )
   if not defined MAIN_STARTED goto err_locked
   ```
   Handle 9 is held open on `<stateDir>\run-claude.lock` for the whole run. A
   second instance cannot open it, so its `call :main_body` never executes and
   `MAIN_STARTED` stays undefined. Windows releases the handle when the process
   dies, so a crash can never leave a stale lock. `:main_body` sets
   `MAIN_STARTED=1` as its first statement and always returns `exit /b 0`; the
   real result travels in `EXIT_CODE`.
5. **Run header + state file preparation** (~228).
6. **Wait for the target start time** (~261).
7. **Main loop** (~266) - `:loop` through `:loop_done`. `MAX_RUNS=0` means
   unlimited.

Then about 55 subroutines. The ones worth knowing:

| Label | Purpose |
|---|---|
| `:run_once` | Builds the prompt, invokes claude, captures output, detects quota wording |
| `:build_prompt`, `:write_prompt_head`, `:write_prompt_tail`, `:bp_file` | Compose the per-iteration prompt file |
| `:prepare_state`, `:write_state_template` | Create / back up / resume the state file |
| `:wait_target`, `:sleep`, `:next_run_time`, `:now`, `:timestamp` | All time handling, via PowerShell |
| `:log` | Print one line to console **and** append to the log |
| `:log_var` | Same, but takes a **variable name** for values that may contain quotes or `&` |
| `:say` | Console-only safe print, used by early error paths before the log exists |
| `:resolve_log`, `:rl_folder`, `:rl_file` | `-l` may be a folder or a file path |
| `:flush_stderr`, `:cleanup_tmp` | Post-run reporting and temp cleanup |
| `:check_complete` | Is line 1 of the state file `TASK_STATUS: COMPLETE`? Exit 0 = yes. First line only, on purpose - landmine 14 |
| `:warn_prompt_encoding` | Logs `[WARN]` when the prompt file has a UTF-16 BOM - landmine 15 |
| `:is_number`, `:check_count`, `:check_target`, `:is_date_only`, `:is_hhmm` | Predicates, return via `exit /b` |
| `:err_*` | One label per error message, each ends `endlocal & exit /b <code>` |

**The claude invocation** - the single most delicate line in the file:

```bat
pushd "%WORK_DIR%"
cmd /c %CLAUDE_EXE% -p %DEFAULT_FLAGS% --add-dir "%STATE_DIR%" %USER_FLAGS% < "%PROMPT_BUILD%" > "%OUT_FILE%" 2>&1
set "CLAUDE_RC=%ERRORLEVEL%"
popd
```

Every part of that shape is deliberate; see section 5 before changing it.

**State protocol.** Each iteration's prompt contains: a header saying the run is
unattended and questions are forbidden, the iteration number, the state-file
path, a numbered protocol, the **current contents of the state file** inline
under `## CURRENT STATE`, then the user's task under `## TASK`. Claude is told to
keep this layout in the state file:

```
TASK_STATUS: IN_PROGRESS
## Goal
## Completed
## In progress
## Next steps
## Notes and blockers
```

After each iteration `:check_complete` tests **the first line of the state file
only** for `TASK_STATUS: COMPLETE` and stops the loop early if it matches. It
must stay first-line-only - see landmine 14. This is why a trivial test prompt
only ever runs one iteration.

**Exit codes:** `0` all iterations fine, `1` at least one claude call failed,
`2` bad parameters, `3` another run holds the lock.

---

## 4. Rules for editing this script

1. **Keep CRLF.** If your editor writes LF, cmd may misparse the file. Verify
   after editing and re-run the tests.
2. **Preserve the three user invariants** in section 1 (no overlap, claude
   failure never fails the runner, no keypresses).
3. **Delayed expansion is globally OFF** (`setlocal DisableDelayedExpansion`).
   Subroutines that need it turn it on and `endlocal` before returning. The known
   cost: a literal `!` inside a logged message or a path gets eaten. Accepted.
4. **Control flow uses `goto`, not parenthesized blocks**, wherever a variable is
   set and then read. See landmine 1.
5. **Re-run `test\run-tests.bat` after any change**, and say in your report that
   you did. It is free and takes 15 seconds. Several of these bugs only appear
   with awkward paths, or only when a claude call fails.
6. Do not add features the user did not ask for. `-r` was added because the spec
   was otherwise unusable for continuing a task; that bar is the bar.

---

## 5. cmd.exe landmines already hit and solved - do not regress these

Each of these was a real bug found during testing. The symptom is listed so you
can recognise a regression.

1. **Parenthesized blocks expand variables at block-parse time.**
   `if X ( set "A=1" & if "%A%"=="1" ... )` reads the *old* `A`. Symptom:
   options silently ignored. Fix: `goto`-based flow, which is why argument
   parsing looks the way it does.

2. **User text in an unquoted `echo` executes.** `echo Prompt: %PROMPT_ARG%`
   where the prompt contains `<`, `>`, `|` or `&` runs it as a metacharacter.
   Symptom: `the was unexpected at this time.` and the script dying during
   validation. Fix: all user-supplied values are printed through `:say`,
   `:log` or `:log_var`, which re-emit them under delayed expansion.

3. **Only one `%VAR%` reference per line for risky values, always inside
   quotes.** Two references to a value containing `%` on one line mangle each
   other. That is why the header prints the flags on separate lines.

4. **Never store quotes in a variable and expand it into a command line.**
   `set "FLAGS=--add-dir "%STATE_DIR%""` followed by `claude %FLAGS%` flips the
   quote state, so an `&` in the path becomes a command separator. Symptom:
   `dir was unexpected at this time.`, run dies mid-iteration. Fix: the flags are
   written out literally on the invocation line; there is no `CLAUDE_FLAGS`
   variable. `:log_var` exists to log such values by name instead.

5. **`echo message>>file` breaks when the message ends in a digit** - `0>>` is
   parsed as a handle redirect. Fix: redirect first, `>>"%F%" echo(message`.
   Every write in this script does that.

6. **`if exist "name\."` is TRUE for plain files** on this Windows build, so it
   cannot test "is a directory". Symptom: a prompt *file* rejected as a
   directory. Fix: file attributes - `for %%F in ("%X%") do set "A=%%~aF"` then
   test `"%A:~0,1%"=="d"`. Used for the prompt argument and for `-l`.

7. **A PID-based lock cannot work here.** Getting "my" PID via
   `for /f ... powershell ... ParentProcessId` returns the transient `cmd` that
   the pipe spawned, which is already dead, so every lock looked stale. Symptom:
   two runs happily clobbering one state file. Fix: the handle-9 exclusive lock
   in section 3. Do not replace it with a PID or timestamp scheme.

8. **A block redirect holds its target file open.** `2>>"%LOG%" ( ... )` made
   every `>>"%LOG%"` append inside the run fail with "The process cannot access
   the file because it is being used by another process", filling the log with
   that message and losing all real output. Fix: block stderr goes to
   `rc-runner-stderr.txt`, which `:flush_stderr` appends to the log afterwards.

9. **Do not pipe the prompt into claude.** `type promptfile | claude ...` hands
   the command to a second `cmd` that re-parses it and breaks on `&` inside
   quoted paths. Fix: `< "%PROMPT_BUILD%"`. This also keeps `%ERRORLEVEL%` as
   claude's own exit code. Verified against the real CLI: `-p` reads the prompt
   from redirected stdin.

10. **Invoke claude through `cmd /c`, never bare and never via `call`.** `claude`
    may be a `.cmd` shim; running a batch file without isolation transfers
    control and never returns, and a fatal parse error inside it kills the whole
    runner silently - which violates invariant 2. With `cmd /c` the damage stays
    in the child and the real exit code still comes back. This was proven: a stub
    that crashed fatally produced `exit code 255`, a logged `[ERROR]`, and a
    runner that kept going.

11. **PowerShell does all time handling.** Date arithmetic in pure batch is
    locale-dependent and unreliable. `:now`, `:timestamp`, `:sleep`,
    `:next_run_time` and `:wait_target` all shell out. The script fails early
    with a clear message if neither `powershell.exe` nor `pwsh.exe` is on PATH.

12. **Prompt text delivery avoids cmd entirely.** For an inline prompt,
    PowerShell reads `$env:PROMPT_ARG` and appends it to the composed prompt
    file, so the text never survives another round of cmd quoting.

13. **The state file must not live under `.claude\`.** The original default was
    `<workdir>\.claude\state.md`. The CLI treats everything in a `.claude` folder
    as sensitive and refuses to Write or Edit it; in a `-p` run there is nobody to
    approve, so the write just fails. Symptom, and it is a quiet one: the runner
    exits 0 and the iteration is counted as a success, but the state file is still
    the untouched template, so a loop repeats iteration 1 forever and can never
    see `TASK_STATUS: COMPLETE`. Found by the first real end-to-end run on
    2026-07-30. Fix: the default is now `<workdir>\run-claude-state.md`. A `-s`
    path inside a `.claude` folder still hits this - do not do it.

14. **The completion check must look at the first line only.** It used to be
    `findstr /i /c:"TASK_STATUS: COMPLETE" "%STATE_FILE%"` over the whole file.
    But the protocol the runner sends says *"write TASK_STATUS: COMPLETE on the
    first line only when ..."*, and claude reliably restates that sentence inside
    the state file - under `## Goal`, or as a note to its future self. The search
    matched that prose. Symptom, silent and expensive: a `-c 2` run did iteration
    1, stopped, and reported `1 run, 1 succeeded, 0 failed` with exit 0 - looking
    entirely healthy - while line 1 still said `IN_PROGRESS` and four of the five
    steps were abandoned. Found by the first real loop test,
    2026-07-30. Fix: `:check_complete` reads line 1 with PowerShell
    `Get-Content -TotalCount 1` and matches `^\s*TASK_STATUS:\s*COMPLETE\b`.
    Do not "optimise" it back into a batch `findstr` over the file. It is
    PowerShell rather than batch for a second reason: `findstr /b` on line 1 is
    defeated by a UTF-8 BOM, which would flip the failure to a loop that never
    stops. Both directions were unit tested.

15. **A prompt file must be UTF-8, and only half of the alternative is
    detectable.** `:bp_file` copies the prompt file into the composed prompt with
    `type`. For UTF-8 that is a byte for byte copy and everything survives. For a
    **UTF-16** file cmd converts it to the *console* codepage on the way in, so
    on a Hebrew console every non ASCII character reaches claude as CP862 bytes -
    silently, exit 0, iteration counted as a success. **ANSI-1255** is worse: the
    raw 1255 bytes are copied straight through and nothing can tell them apart
    from UTF-8, because ANSI text carries no byte order mark. Fix, 2026-07-30:
    `:warn_prompt_encoding` detects a UTF-16 BOM and logs `[WARN]`; `-h` asks for
    UTF-8. ANSI stays undetectable by construction - do not try to guess it.

    Measured with the stub, both codepages, and the results **differ by
    codepage**, which is the trap: at CP65001 the UTF-16 case looks fine, because
    the console codepage the conversion targets happens to be UTF-8. Test at 862
    or the bug hides. What *is* safe at 862, verified: a UTF-8 prompt file, an
    inline Hebrew prompt (it travels cmd argument to env var to PowerShell
    `AppendAllText`, never through a codepage), a Hebrew state file round-tripped
    into the next iteration's prompt, and a Hebrew working directory name.

    Related, and safe only by luck: `:check_complete` reads line 1 with
    `Get-Content`, which defaults to **ANSI** on PowerShell 5.1. It works because
    `TASK_STATUS: COMPLETE` is pure ASCII and ASCII is identical across 862, 1255
    and UTF-8. **Never localise that status line** - detection would break in
    exactly the silent way landmine 14 did.

Known residual limitation, documented in `-h`: an inline prompt containing a
double quote, or a `%` when the script is called from another `.bat`, is mangled
by cmd before the script ever sees it. The supported workaround is a prompt
file. Do not try to "fix" this in batch; it is not fixable.

---

## 6. How to test

### 6a. First priority: the real end-to-end run

The single-run half of this **passes** as of 2026-07-30. In a Windows cmd window:

```bat
mkdir C:\claude-test && cd /d C:\claude-test
copy <path>\run-claude.bat .
run-claude.bat "Create a file named hello.txt containing the single word OK"
echo exit=%ERRORLEVEL%
```

Expect `exit=0`, `hello.txt`, `run-claude-<timestamp>.log`, and
`run-claude-state.md` **that claude has actually rewritten** - if it still reads
like the blank template, the state write was blocked and you are looking at
landmine 13 again. The lock file `run-claude.lock` sits next to it in the work
directory and staying behind between runs is normal.

The loop half is **still unverified against the real CLI**. Run it with the
5-step task file:

```bat
copy <path>\runner-test-task.md .
for /f "usebackq delims=" %A in (`powershell -NoProfile -Command "(Get-Date).AddMinutes(5).ToString('yyyy-MM-dd HH:mm')"`) do @set "T=%A"
run-claude.bat runner-test-task.md -t "%T%" -i 1 -c 5
```

In a `.bat` file write `%%A` instead of `%A`. Success = `runner-test.txt` has 5
lines, one per iteration, and the state file ends at `TASK_STATUS: COMPLETE`.

### 6b. Stub-based testing - the suite exists now, run it after every edit

```bat
cd test
run-tests.bat          rem 38 cases, about 15 seconds
run-tests.bat -full    rem 40 cases, adds the two slow timing ones, ~2.5 minutes
```

Exit 0 all passed, 1 something failed, 9 the suite could not start. Artefacts of
every case are kept under `%TEMP%\rc-suite-<timestamp>\caseN\` - console output,
the log, the state file, and the stub's record of how it was called.

Two files, both **CRLF**, both to be kept that way:

- `test\bin\claude.cmd` - the stub. A fake CLI that costs nothing and can be told
  to misbehave on demand through `STUB_RC`, `STUB_OUT`, `STUB_SLEEP`,
  `STUB_STATE`, `STUB_COMPLETE`, `STUB_COMPLETE_AT`, `STUB_PROSE`. It records
  each call under `STUB_DIR`: `args-N.txt`, `cmdline-N.txt`, and `prompt-N.txt`,
  which is the fully composed prompt the runner built - the only way to inspect
  it, since `:cleanup_tmp` deletes the real one.
- `test\run-tests.bat` - the driver.

Things about the suite that are deliberate, do not "fix" them:

- **It rebuilds `PATH` from scratch.** Prepending the stub is not enough:
  `run-claude.bat` looks for `claude.exe` before `claude.cmd`, so a real
  `claude.exe` anywhere on PATH would win and the suite would quietly spend real
  quota. The suite aborts with exit 9 if it can still see a real one.
- **`args-N.txt` lies about tokens containing `=` or `,`.** Batch splits `%1` on
  space, comma, semicolon *and* equals, so `--allowed-tools=Edit,Write` is
  recorded as three tokens. A real `.exe` gets one argument. Assert such flags
  against `cmdline-N.txt`, which is `%CMDCMDLINE%`. This cost a false failure the
  first time the suite ran.
- **`STUB_PROSE` is the landmine 14 fixture.** It writes a state file that says
  `IN_PROGRESS` on line 1 while mentioning `TASK_STATUS: COMPLETE` further down,
  which is what real claude does. Re-introducing the old whole-file `findstr` was
  tried on purpose on 2026-07-30 and the suite caught it - `the stub ran 1 times,
  wanted 3`. That is the case that proves the suite is not vacuous.

**Write the stub defensively. Several false alarms during development came from a
buggy stub, not from the runner:**

- `echo %CD%` is fatal if the test path contains `&`. Assign to a variable and
  echo it under delayed expansion.
- `set "ALL=%*"` and `echo %*` break the same way. Avoid `%*` entirely.
- A fatal parse error in the stub used to kill the runner; that is now contained
  by `cmd /c`, but it will still make the iteration fail and confuse you.

Covered by the 40 cases: every validation error and its exit code 2, including
`-i` without `-c` and `-c` without `-i`; `-h`; single run inline and from a file;
an inline prompt holding `& | < > ( )`; the composed prompt's contents; `-i 0 -c N`
back to back; early `TASK_STATUS: COMPLETE` stop; the landmine 14 prose case;
`-c 1 -i 5` not waiting after the last iteration; claude exiting nonzero (runner
survives, exit 1, `[ERROR]`); quota wording (`[QUOTA]`); `-l` as folder and as
file; `-s`; `-f` pass-through; the default flags reaching the CLI; state backup
and `-r`; paths containing spaces, `&` and `(x86)`; lock contention (exit 3) and
the lock being free afterwards; `-t` in the past and unquoted; and with `-full`,
`-t` in the future and a real `-i 1 -c 2` interval.

Not covered, and a stub can never cover it: anything about how the real CLI
behaves. Landmines 13 and 14 were both found by real runs, not here. Keep doing
section 6a as well.

### 6c. Debugging technique that worked

Copy the script to `dbg.bat` with `@echo off` changed to `@echo on` and run that.
The trace stops at the offending line. Remember that runner stderr goes to
`%TEMP%\run-claude-<timestamp>\rc-runner-stderr.txt`, and that the temp folder
survives a crash, so read it when a run dies quietly.

---

## 7. Possible next work

Nothing here is requested; confirm with the user before building any of it.

- Real **multi-iteration** validation against the Windows CLI (section 6a) - the
  actual open item. The single-run case already passes.
- Per-iteration timeout, so a hung claude call cannot stall the loop forever.
- Retry with backoff when the output matches quota wording, instead of consuming
  an iteration.
- `--output-format json` parsing to log cost and duration per iteration.
- Log rotation, or a `-l` append-to-single-file mode across runs.
- A Task Scheduler registration helper (`schtasks` wrapper). Note credentials are
  per-user: the scheduled task must run as the user who did `claude auth login`.
