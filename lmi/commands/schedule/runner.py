"""The iteration loop and the claude invocation."""

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
from . import backend, paths, prompt, sdk, session, state
from .config import AT_FORMAT, build_config
from .stream import Renderer
from .exit_codes import EXIT_CALL_FAILED, EXIT_INTERNAL, EXIT_LOCKED

# Built from backend.ALLOWED_TOOLS rather than spelled out, so the flag the CLI
# backend passes and the list the SDK backend passes cannot drift apart. The
# value is unchanged: "--allowed-tools=Edit,Write".
DEFAULT_FLAGS = ["--allowed-tools=" + ",".join(backend.ALLOWED_TOOLS)]

# What -v adds. --output-format stream-json is what makes claude emit an event
# per step instead of one block of text at the end, which is the whole of how a
# running iteration becomes watchable; --verbose is passed alongside it because
# stream-json in -p mode has historically required it, and a duplicate boolean
# costs nothing if it turns out not to. config._reject_output_format refuses a
# user --output-format in -f, because -f is appended last and would win.
VERBOSE_FLAGS = ["--output-format", "stream-json", "--verbose"]

# The rule that opens and closes the header and the summary block.
RULE = "=" * 75

# What an iteration that never reached claude is recorded as - deliberately
# outside the range claude itself returns, so a skipped iteration cannot be
# confused with a real exit code in the log.
ITERATION_ERROR_RC = 90

# Moved to backend.py when the SDK backend became its second scanner, and
# re-exported here because that is the name this module's readers and tests
# already know. One pattern, so neither backend can be quieter than the other.
QUOTA_RE = backend.QUOTA_RE


def run(args):
    cfg = build_config(args)
    run_ts = paths.timestamp()
    state_path = paths.resolve_state(cfg)
    log_path = paths.resolve_log(cfg, run_ts)
    log = Logger(log_path)

    # Before the lock, before the header, before the loop: a backend that
    # cannot run at all ends the run with one message rather than N skipped
    # iterations under a header claiming a run started.
    chosen = _select_backend(cfg)

    lock_path = state_path.parent / paths.LOCK_NAME
    try:
        with single_instance_lock(lock_path):
            return _run_locked(cfg, log, state_path, run_ts, chosen)
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
        # terminal, so a crashed unattended run is diagnosable afterwards.
        log.error("the runner itself failed - this is a bug in lmi:")
        _log_traceback(log)
        return EXIT_INTERNAL


class PromptLog:
    """Logs the prompt under -v: in full the first time, the state after.

    The four parts of the composed document are the header, the state
    protocol, the inlined state file and the task. Only the state file changes
    between iterations - the task is read once before the loop and the
    protocol is a constant in prompt.py - so logging all four every time
    repeats the same forty-odd lines for every iteration of the run.

    `full_done` is "has the whole document been logged yet", NOT "is this
    iteration 1". An iteration can die before prompt.compose - a vanished temp
    workspace - and the loop deliberately survives that, so keying off the
    iteration number would make iteration 2 claim the rest is "unchanged from
    iteration 1" about text nobody ever wrote. Do not simplify this flag back
    into `if n == 1`.
    """

    def __init__(self, verbose):
        self.verbose = verbose
        self.full_done = False

    def emit(self, log, composed, state_body):
        if not self.verbose:
            return
        if not self.full_done:
            log.line("--- prompt sent to claude (full, %d lines) ---"
                     % len(composed.splitlines()))
            for line in composed.splitlines():
                log.line(line)
            log.line("--- end of prompt ---")
            self.full_done = True
            return
        log.line("--- state sent to claude (header, protocol and task "
                 "unchanged from the first logged prompt) ---")
        for line in state_body.splitlines():
            log.line(line)
        log.line("--- end of state ---")


def _pump(log, lines, render=None):
    """Log every line as it arrives. (quota?, unresumable?), off the RAW lines.

    The one place output reaches the log, so the two invocation paths - a
    finished file's splitlines(), and a live pipe - cannot drift apart in how
    they log or in what they scan.

    The quota scan reads the RAW line, never the rendered one. Under
    stream-json the wording lives inside a JSON error or result event, and a
    renderer that summarised such an event without carrying its message
    through would silently disable the [QUOTA] tag. Scanning before rendering
    makes that impossible however the renderer later changes.
    """
    quota = unresumable = False
    for raw in lines:
        if QUOTA_RE.search(raw):
            quota = True
        # Read before rendering for item 28's reason and now for a second one:
        # "No conversation found with session ID" is claude's own diagnostic, and
        # a renderer that summarised it would leave the runner unable to tell a
        # session that is gone from any other failure.
        if backend.UNRESUMABLE_RE.search(raw):
            unresumable = True
        log.line(render(raw) if render else raw)
    return quota, unresumable


def _decoded_lines(pipe):
    """The child's stdout, one decoded line at a time, as they arrive.

    Bytes decoded here rather than through a text-mode Popen: text mode
    decodes with the locale codepage, which on the site's Windows machines is
    not UTF-8, so the streaming path would disagree with the captured path
    about the same bytes. errors="replace" matches what the captured path's
    read_text does - a half-written line must never end an iteration.
    """
    for chunk in pipe:
        yield chunk.decode("utf-8", "replace").rstrip("\r\n")


def _log_traceback(log):
    """Indent the current traceback into the log, one [ERROR] line each."""
    for line in traceback.format_exc().rstrip().splitlines():
        log.error("  " + line)


def _claude_argv(cfg, state_path, claude):
    """Everything that is fixed for the whole run: no session flags, no -f.

    The session flags change between iterations - a fresh session is minted once
    and resumed afterwards - so they are appended in `call`, and -f after them,
    because -f must stay LAST. That ordering is load-bearing in both directions:
    items 26 and 46 are about claude taking the last occurrence of a repeated
    option, and item 57 refuses the -f flags that would exploit it here.
    """
    verbose = VERBOSE_FLAGS if cfg.verbose else []
    return [claude, "-p"] + DEFAULT_FLAGS + verbose + \
        ["--add-dir", str(state_path.parent)]


def _session_flags(handle):
    """The handle as an argv fragment, and the one place that translation lives.

    `--session-id` names a session that does not exist yet; `--resume` continues
    one that does. Getting them the wrong way round is not a subtle failure -
    claude refuses both - which is the good kind of load-bearing.
    """
    if handle is None:
        return []
    if handle.resuming:
        return ["--resume", handle.id]
    return ["--session-id", handle.id]


# --- the seam -------------------------------------------------------------
#
# Two backends, one shape. Each exposes prepare / describe / call, and `call`
# takes the composed prompt and a session handle, and returns the
# `backend.Outcome` that _capture_claude and _stream_claude have always
# returned (a bare (rc, quota) pair until sessions needed a third verdict). Below this point the
# loop cannot tell which one it has, which is the whole design: everything that
# reads a run - _log_iteration_result, ITERATION_ERROR_RC, EXIT_CALL_FAILED -
# keeps its single vocabulary.

NO_CLAUDE = "claude is not on PATH"


def _select_backend(cfg):
    """The one place the configured mode decides anything.

    Both preconditions live here rather than at the call site, so that "can
    this backend run?" is answered once, before the lock, for whichever backend
    was chosen - and so that nothing further down has to ask about the mode
    again.

    There is deliberately NO fallback between the two. If the SDK is missing
    this raises; it does not quietly run the CLI instead. Falling back is the
    installer's job, done once and written into a config file a human can read
    - see backend.DEFAULT. A runner that silently changes backend is worse than
    one that stops, because both backends exit 0 on success.
    """
    if cfg.mode == backend.SDK:
        sdk.require(cfg.session)
        return _SdkBackend()
    claude = shutil.which("claude")
    if claude is None:
        raise LmiError(NO_CLAUDE, EXIT_USAGE)
    return _CliBackend(claude)


class _CliBackend:
    """`claude -p`, a pipe and a temp workspace: exactly as it always was.

    A thin wrapper around the functions below, which are unchanged. It exists
    to give the CLI path the same three methods the SDK path has, not to
    reorganise it - _claude_argv, _capture_claude, _stream_claude, _pump,
    _decoded_lines and the prompt-N.txt / out-N.txt workspace all keep working
    the way they did, comments included.
    """

    def __init__(self, claude):
        self.claude = claude
        self.argv = None

    def prepare(self, cfg, state_path):
        # Fixed for the whole run, so built once rather than per iteration.
        self.argv = _claude_argv(cfg, state_path, self.claude)

    def describe(self, cfg, log, handle):
        # argv[0] rather than a separate claude argument: they are the same
        # value by construction, and two parameters could disagree.
        log.line("claude    : " + self.argv[0])
        # The complete flag list, which docs/schedule.md's Logging section
        # promises - including the session flag this iteration will carry, so
        # the line stays the argv that actually runs rather than most of it.
        log.line("Flags     : " + " ".join(
            self.argv[1:] + _session_flags(handle) + list(cfg.user_flags)
        ))

    def call(self, cfg, log, composed, state_path, tmp_dir, n, handle):
        prompt_path = tmp_dir / ("prompt-%d.txt" % n)
        # open(), not Path.write_text(..., newline=...): that keyword arrived
        # in Python 3.10 and pyproject declares >=3.9, so on the 3.9.6 that
        # macOS ships every run died at iteration 1 with a TypeError.
        with open(str(prompt_path), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(composed)
        out_path = tmp_dir / ("out-%d.txt" % n)
        argv = self.argv + _session_flags(handle) + list(cfg.user_flags)

        if cfg.verbose:
            return _stream_claude(cfg, log, argv, prompt_path)
        return _capture_claude(cfg, log, argv, prompt_path, out_path)


class _SdkBackend:
    """The Claude Agent SDK, through commands/schedule/sdk.py.

    It writes no prompt file and uses no temp workspace: query() takes the
    prompt as a string. The workspace is still created for the run, because the
    CLI backend needs it and the runner does not branch on the mode.
    """

    def prepare(self, cfg, state_path):
        pass

    def describe(self, cfg, log, handle):
        sdk.describe(cfg, log)

    def call(self, cfg, log, composed, state_path, tmp_dir, n, handle):
        return sdk.call(cfg, log, composed, state_path, handle)


def _session_line(cfg, handle):
    """One line naming the session and what chose it - item 58.

    Shaped like the Backend line above it, "<value> (from <source>)", because
    they answer the same kind of question about the same run and an operator
    reads them together. The source is half the line: "on" alone does not say
    whether a config file, a flag or nothing at all decided.
    """
    if handle is None:
        return "Session   : off (from %s)" % cfg.session_source
    what = ("resuming, created %s" % handle.created) if handle.resuming else "new"
    return "Session   : on (from %s) - %s (%s)" % (
        cfg.session_source, handle.id, what
    )


def _log_header(cfg, log, state_path, chosen, handle):
    log.line(RULE)
    log.line("lmi schedule starting at " + paths.now_str())
    log.line("Working directory: " + str(cfg.work_dir))
    # THE line that makes a two-backend run readable afterwards. Both backends
    # exit 0 on success and neither leaves a mark on the state file saying
    # which one ran, so without this nothing in an unattended run's only record
    # distinguishes a run that used the intended backend from one that did not
    # - and the entire point of a switch is that the outcome cannot tell you.
    # The source is half the line: "sdk" alone does not say whether a config
    # file chose it or nothing did.
    log.line("Backend   : %s (from %s)" % (cfg.mode, cfg.mode_source))
    # And whether one claude session spans the iterations, for exactly the same
    # reason as the line above: both ways round exit 0 and neither marks the
    # state file, so this is the only record of which one this run was.
    log.line(_session_line(cfg, handle))
    # The resolved configuration, which docs/schedule.md's Logging section
    # promises:
    # where the prompt came from, which claude is being run, and the complete
    # flag list including the defaults and -f.
    if cfg.prompt_file is not None:
        log.line("Prompt    : file " + str(cfg.prompt_file))
    else:
        log.line("Prompt    : inline text: " + (cfg.prompt_text or ""))
    # Whatever this backend resolved that the other one has no equivalent of:
    # an argv and a flag list for the CLI, the options that decide what Claude
    # may do for the SDK. Everything above and below is common to both, so the
    # two logs line up everywhere except here.
    chosen.describe(cfg, log, handle)
    log.line("State file: " + str(state_path))
    log.line("Log file  : " + str(log.path))
    log.line("Iterations: %d" % cfg.max_runs)
    log.line("Interval  : %d minute/s" % cfg.interval_min)
    if cfg.at is not None:
        log.line("Start time: " + cfg.at.strftime(AT_FORMAT))
    if cfg.verbose:
        # The two claude flags -v adds are already visible on the Flags line
        # above. This says what lmi itself is doing differently, which argv
        # cannot show.
        log.line("Verbose   : on - prompt logged, claude activity rendered live")
    log.line(RULE)


def _log_iteration_result(log, label, rc, duration):
    """Record how one iteration ended. Returns True if it succeeded.

    Both shapes carry the same four facts - which iteration, when it ended,
    claude's exit code, how long it took - because the log is an unattended
    run's only record and the duration is what reveals a hung or slowing
    iteration.
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
    log.line(RULE)
    log.line("lmi schedule finished at " + paths.now_str())
    log.line("%d run/s, %d succeeded, %d failed." % (runs, runs - fails, fails))
    log.line("State file: " + str(state_path))
    log.line("Log file  : " + str(log.path))
    log.line(RULE)
    if fails:
        log.error(
            "%d iteration/s failed - search the log for [ERROR] and [QUOTA]." % fails
        )


def _run_locked(cfg, log, state_path, run_ts, chosen):
    chosen.prepare(cfg, state_path)
    session_path = paths.resolve_session(state_path)
    # Before the header, because the header has to name the session (item 58).
    # The state file's own prepare() stays where it is, below: its lines belong
    # to the run's body rather than to the resolved configuration. The two
    # follow ONE -r rule, and a test pins the pair rather than either half.
    handle = session.prepare(cfg, session_path, run_ts, log)
    _log_header(cfg, log, state_path, chosen, handle)

    state.prepare(state_path, cfg.resume, run_ts, log)
    # The task text never changes, so it is read and decoded once instead of on
    # every iteration. Doing it here also means an undecodable prompt file ends
    # the run before the first iteration is announced, rather than part-way in.
    task = prompt.read_prompt_source(cfg)
    _wait_until(cfg.at, log)

    tmp_dir = Path(tempfile.mkdtemp(prefix="lmi-schedule-"))
    prompt_log = PromptLog(cfg.verbose)
    runs = fails = 0
    try:
        for iteration in range(1, cfg.max_runs + 1):
            label = "%d of %d" % (iteration, cfg.max_runs)
            started = paths.now_str()
            start_clock = time.time()
            log.line("")
            log.line("--- iteration %s started %s ---" % (label, started))

            rc, handle = _iteration_rc(
                cfg, log, state_path, chosen, task, tmp_dir, iteration,
                label, started, prompt_log, session_path, handle
            )
            runs += 1
            if not _log_iteration_result(
                log, label, rc, int(time.time() - start_clock)
            ):
                fails += 1

            if state.check_complete(state_path):
                log.line(
                    "State file line 1 says TASK_STATUS: COMPLETE - stopping early."
                )
                break
            if iteration >= cfg.max_runs:
                break
            _sleep_between(cfg, log)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    _log_summary(log, state_path, runs, fails)
    # Derived, not tracked alongside `fails`: a failed iteration is the only
    # thing that makes a run exit 1, so the two cannot drift apart.
    return EXIT_CALL_FAILED if fails else EXIT_OK


def _iteration_rc(cfg, log, state_path, chosen, task, tmp_dir, n, label, started,
                  prompt_log, session_path, handle):
    """(exit code, the handle to use next), invariant 2 enforced around it."""
    try:
        return _one_iteration(
            cfg, log, state_path, chosen, task, tmp_dir, n, label, started,
            prompt_log, session_path, handle
        )
    except LmiError:
        # A usage error is deterministic - a prompt file that is not UTF-8
        # would fail identically on every remaining iteration - so it ends the
        # run (logged, exit 2) rather than burning the whole loop. Everything
        # in the clause below is treated as transient instead. This clause must
        # stay first: LmiError is an Exception too.
        raise
    except Exception:
        # Invariant 2, the exception half of it: a failure to even build the
        # prompt, a transient OSError out of subprocess.run, a full disk. The
        # iteration is recorded as skipped and the loop carries on - without
        # this, one bad iteration abandoned every iteration after it.
        log.error("could not run iteration %s - it was skipped:" % label)
        _log_traceback(log)
        # The handle is returned unchanged, deliberately. An iteration that
        # never reached claude learned nothing about the session, and dropping a
        # live conversation because a temp directory vanished is item 54's
        # mistake arriving from a different direction.
        return ITERATION_ERROR_RC, handle


def _sleep_between(cfg, log):
    """Wait out -i, measured from the end of the iteration that just finished."""
    if cfg.interval_min <= 0:
        return
    secs = cfg.interval_min * 60
    nxt = datetime.fromtimestamp(time.time() + secs)
    log.line("Next iteration at " + paths.now_str(nxt))
    time.sleep(secs)


def _one_iteration(cfg, log, state_path, chosen, task, tmp_dir, n, label, started,
                   prompt_log, session_path, handle):
    body = state.read_body(state_path)
    composed = prompt.compose(cfg, state_path, label, started, body, task)
    prompt_log.emit(log, composed, body)

    if handle is not None:
        session.warn_if_moved(handle, cfg.work_dir, log)

    was_resuming = handle is not None and handle.resuming
    outcome = chosen.call(cfg, log, composed, state_path, tmp_dir, n, handle)
    if handle is not None:
        # After the call, whatever it returned. A call that failed part-way may
        # still have created the session, and item 54 is that a failure - a usage
        # limit above all - is not a reason to start the conversation over.
        handle = handle._replace(resuming=True)

    if was_resuming and outcome.rc != 0 and outcome.unresumable:
        # The one condition that drops a session, and the only retry there is.
        #
        # NOT "any failure": a usage limit leaves the conversation perfectly
        # intact, and resuming it next interval is the whole point of the feature
        # (item 54). NOT "no retry": the resume failed locally, before any API
        # call - claude prints "No conversation found" and exits 1 - so trying
        # again fresh costs nothing, where waiting for the next interval costs a
        # third of a `-c 3` run. And NOT "retry until it works": exactly one
        # attempt, so a machine that fails every resume cannot turn a single
        # iteration into an unbounded call loop (item 55).
        handle = session.remint(cfg, session_path, log, handle)
        retry = chosen.call(cfg, log, composed, state_path, tmp_dir, n, handle)
        handle = handle._replace(resuming=True)
        # rc from the attempt that actually ran; quota from EITHER, because
        # under-reporting [QUOTA] is the dangerous direction and a limit reported
        # by the first attempt is no less real for the second having been made.
        outcome = backend.Outcome(
            retry.rc, outcome.quota or retry.quota, retry.unresumable
        )

    if outcome.quota:
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
    return outcome.rc, handle


def _capture_claude(cfg, log, argv, prompt_path, out_path):
    """Run claude to a file and replay it afterwards. A backend.Outcome."""
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
    quota, unresumable = _pump(log, output.splitlines())
    log.line("--- end of claude output ---")
    return backend.Outcome(completed.returncode, quota, unresumable)


def _stream_claude(cfg, log, argv, prompt_path):
    """Run claude on a pipe, rendering events as they arrive.

    No out-N.txt here: there is nothing to capture to a file when the lines
    are consumed as they are produced. Popen is used as a context manager so
    the pipe is closed and the child waited on even if the loop raises -
    without that, an exception mid-stream leaves claude running while
    _iteration_rc records a skip and the loop moves on.
    """
    log.line("--- claude activity ---")
    renderer = Renderer(log)
    with open(prompt_path, "rb") as stdin_fh, \
            subprocess.Popen(
                argv, stdin=stdin_fh, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, cwd=str(cfg.work_dir),
            ) as proc:
        quota, unresumable = _pump(log, _decoded_lines(proc.stdout),
                                   renderer.render)
    log.line("--- end of claude activity ---")
    return backend.Outcome(proc.returncode, quota, unresumable)


def _wait_until(target, log):
    if target is None:
        return
    secs = (target - datetime.now()).total_seconds()
    if secs <= 0:
        log.line(
            "Start time %s has already passed - starting now."
            % target.strftime(AT_FORMAT)
        )
        return
    log.line(
        "Waiting until %s (%d seconds)." % (target.strftime(AT_FORMAT), int(secs))
    )
    time.sleep(secs)
