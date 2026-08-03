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
from ...core.lock import LockBusy, single_instance_lock
from ...core.log import Logger
from . import paths, prompt, state
from .config import build_config
from .exit_codes import EXIT_CALL_FAILED, EXIT_INTERNAL, EXIT_LOCKED

DEFAULT_FLAGS = ["--allowed-tools=Edit,Write"]

QUOTA_RE = re.compile(
    r"usage limit|rate.?limit|quota|credit balance|insufficient credit"
    r"|too many requests|overloaded|exceeded your",
    re.IGNORECASE,
)


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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
    except LmiError:
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


def _run_locked(cfg, log, state_path, run_ts, claude):
    log.line("=" * 75)
    log.line("lmi schedule starting at " + _now_str())
    log.line("Working directory: " + str(cfg.work_dir))
    log.line("State file: " + str(state_path))
    log.line("Log file  : " + str(log.path))
    log.line("Iterations: %d" % cfg.max_runs)
    log.line("Interval  : %d minute/s" % cfg.interval_min)
    if cfg.at is not None:
        log.line("Start time: " + cfg.at.strftime("%Y-%m-%d %H:%M"))
    log.line("=" * 75)

    state.prepare(state_path, cfg.resume, run_ts, log)
    _wait_until(cfg.at, log)

    tmp_dir = Path(tempfile.mkdtemp(prefix="lmi-schedule-"))
    exit_code = EXIT_OK
    runs = fails = 0
    try:
        for iteration in range(1, cfg.max_runs + 1):
            label = "%d of %d" % (iteration, cfg.max_runs)
            started = _now_str()
            start_clock = time.time()
            log.line("")
            log.line("--- iteration %s started %s ---" % (label, started))

            rc = _one_iteration(
                cfg, log, state_path, claude, tmp_dir, iteration, label, started
            )
            runs += 1
            finished = _now_str()
            duration = int(time.time() - start_clock)
            if rc == 0:
                log.line(
                    "=== Iteration %s finished %s - exit code 0 - %ds ==="
                    % (label, finished, duration)
                )
            else:
                fails += 1
                exit_code = EXIT_CALL_FAILED
                log.error(
                    "=== Iteration %s FAILED at %s - claude exit code %d - %ds ==="
                    % (label, finished, rc, duration)
                )
                log.error(
                    "The runner is NOT stopping. The claude output above holds "
                    "the reason."
                )

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
                log.line("Next iteration at " + nxt.strftime("%Y-%m-%d %H:%M:%S"))
                time.sleep(secs)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    log.line("")
    log.line("=" * 75)
    log.line("lmi schedule finished at " + _now_str())
    log.line("%d run/s, %d succeeded, %d failed." % (runs, runs - fails, fails))
    log.line("State file: " + str(state_path))
    log.line("Log file  : " + str(log.path))
    log.line("=" * 75)
    if fails:
        log.error(
            "%d iteration/s failed - search the log for [ERROR] and [QUOTA]." % fails
        )
    return exit_code


def _one_iteration(cfg, log, state_path, claude, tmp_dir, n, label, started):
    try:
        body = state_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        body = ""
    composed = prompt.compose(cfg, state_path, label, started, body)

    prompt_path = tmp_dir / ("prompt-%d.txt" % n)
    prompt_path.write_text(composed, encoding="utf-8", newline="\n")
    out_path = tmp_dir / ("out-%d.txt" % n)

    argv = [claude, "-p"] + DEFAULT_FLAGS + \
        ["--add-dir", str(state_path.parent)] + cfg.user_flags

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
        log.quota(
            "*** Possible quota, rate limit or overload problem in the claude "
            "output above."
        )
        log.quota(
            "*** Check your usage before trusting the result of this iteration."
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
