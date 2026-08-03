"""The iteration loop and the claude invocation."""

import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

from ...core.errors import EXIT_OK, EXIT_USAGE, LmiError
from ...core.lock import LockBusy, LockUnusable, single_instance_lock
from ...core.log import Logger
from . import paths, prompt, state
from .config import build_config
from .exit_codes import EXIT_CALL_FAILED, EXIT_INTERNAL, EXIT_LOCKED

DEFAULT_FLAGS = ["--allowed-tools=Edit,Write"]

# What an iteration that never reached claude is recorded as. Same number
# run-claude.bat's :run_once uses when it cannot build the prompt, so the two
# tools' logs stay comparable.
ITERATION_ERROR_RC = 90

QUOTA_RE = re.compile(
    r"usage limit|rate.?limit|quota|credit balance|insufficient credit"
    r"|too many requests|overloaded|exceeded your",
    re.IGNORECASE,
)


def run(args):
    cfg = build_config(args)
    run_ts = paths.timestamp()
    state_path = paths.resolve_state(cfg)
    log_path = paths.resolve_log(cfg, run_ts)
    log = Logger(log_path)

    claude = shutil.which("claude")
    if claude is None:
        raise LmiError("claude is not on PATH", EXIT_USAGE)

    lock_path = state_path.parent / "run-claude.lock"
    try:
        with single_instance_lock(lock_path):
            return _run_locked(cfg, log, state_path, run_ts, claude)
    except LockBusy:
        print(
            "[ERROR] another run is working on this state file: %s" % state_path,
            file=sys.stderr,
        )
        return EXIT_LOCKED
    except LockUnusable as exc:
        # The lock lives next to the state file, so an unwritable state
        # directory fails here first. That is the user's path being wrong,
        # exit 2 - not a bug in lmi, which is what exit 4 would claim.
        message = "cannot create the lock file %s: %s" % (lock_path, exc)
        log.error(message)
        raise LmiError(message, EXIT_USAGE)
    except LmiError as exc:
        # Design 8.2: nothing the runner reports is lost from the log. cli.py
        # prints this on stderr, which for a Task Scheduler or cron run goes
        # nowhere, and the log would otherwise just stop mid-run with no
        # reason. The exit code is unchanged - the error is only copied.
        log.error(str(exc))
        raise
    except Exception:
        # Everything the runner itself reports must reach the log, not just the
        # terminal. run-claude.bat gets this by capturing its own stderr to a
        # file and appending it under [WARN]; here the traceback goes straight
        # into the log so a crashed unattended run is diagnosable afterwards.
        log.error("the runner itself failed - this is a bug in lmi:")
        for line in traceback.format_exc().rstrip().splitlines():
            log.error("  " + line)
        return EXIT_INTERNAL


def _claude_argv(cfg, state_path, claude):
    return [claude, "-p"] + DEFAULT_FLAGS + \
        ["--add-dir", str(state_path.parent)] + cfg.user_flags


def _log_header(cfg, log, state_path, argv, claude):
    log.line("=" * 75)
    log.line("lmi schedule starting at " + paths.now_str())
    log.line("Working directory: " + str(cfg.work_dir))
    # The resolved configuration, which README's Logging section promises and
    # the .bat's header prints: where the prompt came from, which claude is
    # being run, and the complete flag list including the defaults and -f.
    if cfg.prompt_file is not None:
        log.line("Prompt    : file " + str(cfg.prompt_file))
    else:
        log.line("Prompt    : inline text: " + (cfg.prompt_text or ""))
    log.line("claude    : " + str(claude))
    log.line("Flags     : " + " ".join(argv[1:]))
    log.line("State file: " + str(state_path))
    log.line("Log file  : " + str(log.path))
    log.line("Iterations: %d" % cfg.max_runs)
    log.line("Interval  : %d minute/s" % cfg.interval_min)
    if cfg.at is not None:
        log.line("Start time: " + cfg.at.strftime("%Y-%m-%d %H:%M"))
    log.line("=" * 75)


def _log_iteration_result(log, label, rc, duration):
    """Record how one iteration ended. Returns True if it succeeded.

    Both shapes carry the four facts run-claude.bat's :iter_ok and :iter_failed
    do - which iteration, when it ended, claude's exit code, how long it took -
    because the log is an unattended run's only record and the duration is what
    reveals a hung or slowing iteration.
    """
    finished = paths.now_str()
    if rc == 0:
        log.line(
            "=== Iteration %s finished %s - exit code 0 - %ds ==="
            % (label, finished, duration)
        )
        return True
    what = (
        "the iteration was skipped"
        if rc == ITERATION_ERROR_RC
        else "claude exit code %d" % rc
    )
    log.error(
        "=== Iteration %s FAILED at %s - %s - %ds ==="
        % (label, finished, what, duration)
    )
    log.error("The runner is NOT stopping. The output above holds the reason.")
    return False


def _log_summary(log, state_path, runs, fails):
    log.line("")
    log.line("=" * 75)
    log.line("lmi schedule finished at " + paths.now_str())
    log.line("%d run/s, %d succeeded, %d failed." % (runs, runs - fails, fails))
    log.line("State file: " + str(state_path))
    log.line("Log file  : " + str(log.path))
    log.line("=" * 75)
    if fails:
        log.error(
            "%d iteration/s failed - search the log for [ERROR] and [QUOTA]." % fails
        )


def _run_locked(cfg, log, state_path, run_ts, claude):
    # Fixed for the whole run, so built once rather than per iteration.
    argv = _claude_argv(cfg, state_path, claude)
    _log_header(cfg, log, state_path, argv, claude)

    state.prepare(state_path, cfg.resume, run_ts, log)
    # The task text never changes, so it is read and decoded once instead of on
    # every iteration. Doing it here also means an undecodable prompt file ends
    # the run before the first iteration is announced, rather than part-way in.
    task = prompt.read_prompt_source(cfg)
    _wait_until(cfg.at, log)

    tmp_dir = Path(tempfile.mkdtemp(prefix="lmi-schedule-"))
    exit_code = EXIT_OK
    runs = fails = 0
    try:
        for iteration in range(1, cfg.max_runs + 1):
            label = "%d of %d" % (iteration, cfg.max_runs)
            started = paths.now_str()
            start_clock = time.time()
            log.line("")
            log.line("--- iteration %s started %s ---" % (label, started))

            try:
                rc = _one_iteration(
                    cfg, log, state_path, argv, task, tmp_dir, iteration,
                    label, started
                )
            except LmiError:
                # A usage error is deterministic - a prompt file that is not
                # UTF-8 would fail identically on every remaining iteration -
                # so it ends the run (logged, exit 2) rather than burning the
                # whole loop. Everything else below is treated as transient.
                raise
            except Exception:
                # Invariant 2, the exception half of it: a failure to even
                # build the prompt, a transient OSError out of subprocess.run,
                # a full disk. run-claude.bat's :run_once logs "[ERROR] Could
                # not build the prompt for this iteration - it was skipped.",
                # sets CLAUDE_RC=90 and keeps looping; so does this. Without
                # it, one bad iteration abandoned every iteration after it.
                rc = ITERATION_ERROR_RC
                log.error(
                    "could not run iteration %s - it was skipped:" % label
                )
                for line in traceback.format_exc().rstrip().splitlines():
                    log.error("  " + line)
            runs += 1
            if not _log_iteration_result(
                log, label, rc, int(time.time() - start_clock)
            ):
                fails += 1
                exit_code = EXIT_CALL_FAILED

            if state.check_complete(state_path):
                log.line(
                    "State file line 1 says TASK_STATUS: COMPLETE - stopping early."
                )
                break
            if iteration >= cfg.max_runs:
                break
            if cfg.interval_min > 0:
                secs = cfg.interval_min * 60
                nxt = datetime.fromtimestamp(time.time() + secs)
                log.line("Next iteration at " + paths.now_str(nxt))
                time.sleep(secs)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    _log_summary(log, state_path, runs, fails)
    return exit_code


def _one_iteration(cfg, log, state_path, argv, task, tmp_dir, n, label, started):
    body = state.read_body(state_path)
    composed = prompt.compose(cfg, state_path, label, started, body, task)

    prompt_path = tmp_dir / ("prompt-%d.txt" % n)
    # open(), not Path.write_text(..., newline=...): that keyword arrived in
    # Python 3.10 and pyproject declares >=3.9, so on the 3.9.6 that macOS
    # ships every run died at iteration 1 with a TypeError.
    with open(str(prompt_path), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(composed)
    out_path = tmp_dir / ("out-%d.txt" % n)

    log.line("--- claude output ---")
    with open(prompt_path, "rb") as stdin_fh, \
            open(out_path, "wb") as out_fh:
        # check=False by default: a non-zero exit must be returned, never
        # raised. That is invariant 2 - a failing call must not end the run.
        completed = subprocess.run(
            argv, stdin=stdin_fh, stdout=out_fh,
            stderr=subprocess.STDOUT, cwd=str(cfg.work_dir),
        )
    output = out_path.read_text(encoding="utf-8", errors="replace")
    for line in output.splitlines():
        log.line(line)
    log.line("--- end of claude output ---")

    if QUOTA_RE.search(output):
        # Tagged inline: [QUOTA] is this command's vocabulary, not something
        # the shared Logger should know about.
        log.line(
            "[QUOTA] *** Possible quota, rate limit or overload problem in the "
            "claude output above."
        )
        log.line(
            "[QUOTA] *** Check your usage before trusting the result of this "
            "iteration."
        )
    return completed.returncode


def _wait_until(target, log):
    if target is None:
        return
    secs = (target - datetime.now()).total_seconds()
    if secs <= 0:
        log.line(
            "Start time %s has already passed - starting now."
            % target.strftime("%Y-%m-%d %H:%M")
        )
        return
    log.line(
        "Waiting until %s (%d seconds)."
        % (target.strftime("%Y-%m-%d %H:%M"), int(secs))
    )
    time.sleep(secs)
