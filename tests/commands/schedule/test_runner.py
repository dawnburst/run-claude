import os
import re

import pytest

from lmi.cli import main
from lmi.commands.schedule import paths

from ...conftest import skip_as_root


def _count(fake):
    return int(fake.count_file.read_text())


def _log_body(tmp_path):
    return next(tmp_path.glob(paths.LOG_PREFIX + "*.log")).read_text(
        encoding="utf-8"
    )


def _default_state(tmp_path):
    """Where the runner puts the state file when -s is not given."""
    return str(tmp_path / paths.STATE_NAME)


def test_single_run_invokes_claude_once(tmp_path, fake_claude, capsys):
    rc = main(["schedule", "hello", "-d", str(tmp_path)])
    assert rc == 0
    assert _count(fake_claude) == 1
    assert "fake claude call 1" in capsys.readouterr().out


def test_default_flags_and_add_dir_reach_the_cli(tmp_path, fake_claude):
    main(["schedule", "hello", "-d", str(tmp_path)])
    argv = (fake_claude.dir / "argv-1.txt").read_text().splitlines()
    assert argv[0] == "-p"
    assert "--allowed-tools=Edit,Write" in argv
    assert "--add-dir" in argv


def test_user_flags_are_appended_after_the_defaults(tmp_path, fake_claude):
    main(["schedule", "hello", "-d", str(tmp_path), "-f", "--verbose --model x"])
    argv = (fake_claude.dir / "argv-1.txt").read_text().splitlines()
    # Order matters: defaults, then --add-dir, then the user's flags last.
    assert argv[-3:] == ["--verbose", "--model", "x"]
    assert argv.index("--allowed-tools=Edit,Write") < argv.index("--verbose")


def test_the_composed_prompt_reaches_claude_on_stdin(tmp_path, fake_claude):
    main(["schedule", "write a haiku", "-d", str(tmp_path)])
    body = (fake_claude.dir / "prompt-1.txt").read_text(encoding="utf-8")
    assert "# Unattended automated run" in body
    assert "## CURRENT STATE" in body
    assert "write a haiku" in body


def test_back_to_back_loop_runs_count_times(tmp_path, fake_claude):
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "3"]) == 0
    assert _count(fake_claude) == 3


def test_early_stop_when_line_one_becomes_complete(tmp_path, fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_STATE_FILE", _default_state(tmp_path))
    monkeypatch.setenv("FAKE_COMPLETE_AT", "2")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "5"]) == 0
    assert _count(fake_claude) == 2


def test_prose_complete_does_not_stop_the_loop(tmp_path, fake_claude, monkeypatch):
    """MANDATORY. The prose false positive: widening check_complete to search
    the whole file must turn this red."""
    monkeypatch.setenv("FAKE_STATE_FILE", _default_state(tmp_path))
    monkeypatch.setenv("FAKE_PROSE", "1")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "3"]) == 0
    assert _count(fake_claude) == 3


def test_failing_claude_call_never_kills_the_runner(tmp_path, fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_RC", "7")
    rc = main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "2"])
    assert rc == 1                      # at least one call failed
    assert _count(fake_claude) == 2      # but the loop kept going


def test_quota_wording_is_flagged(tmp_path, fake_claude, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_OUT", "Error: you have exceeded your usage limit")
    main(["schedule", "x", "-d", str(tmp_path)])
    assert "[QUOTA]" in capsys.readouterr().out


def test_claude_output_reaches_the_log(tmp_path, fake_claude):
    main(["schedule", "x", "-d", str(tmp_path)])
    assert "fake claude call 1" in _log_body(tmp_path)


def test_per_iteration_completion_is_logged_with_a_duration(tmp_path, fake_claude):
    """Every iteration gets a finish line - iteration, exit code, duration -
    whether it succeeded or failed. That information must reach the log and not
    just the terminal, since the log is the only record of an unattended run
    afterwards, and the duration is what reveals a slowing or hung iteration."""
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "2"]) == 0
    log = _log_body(tmp_path)
    # Two iterations, each with its own completion line naming the iteration
    # and carrying a numeric duration in seconds - a line with no digits
    # before the trailing "s" (i.e. the duration silently dropped) must fail.
    matches = re.findall(r"Iteration 1 of 2 finished.*?\d+s", log)
    assert matches, "no per-iteration completion line with a duration found"
    matches2 = re.findall(r"Iteration 2 of 2 finished.*?\d+s", log)
    assert matches2, "second iteration's completion line is missing"


def test_at_in_the_past_starts_immediately(tmp_path, fake_claude):
    rc = main(["schedule", "x", "-d", str(tmp_path), "-t", "2020-01-01 00:00"])
    assert rc == 0 and _count(fake_claude) == 1


def test_second_run_is_refused_while_the_lock_is_held(tmp_path, fake_claude):
    from lmi.core.lock import single_instance_lock
    lock = tmp_path / paths.LOCK_NAME
    with single_instance_lock(lock):
        rc = main(["schedule", "x", "-d", str(tmp_path)])
    assert rc == 3
    assert _count(fake_claude) == 0      # claude was never started


def test_the_lock_is_free_again_afterwards(tmp_path, fake_claude):
    assert main(["schedule", "x", "-d", str(tmp_path)]) == 0
    assert main(["schedule", "x", "-d", str(tmp_path)]) == 0


def test_semantic_validation_reaches_the_cli_as_exit_2(tmp_path, fake_claude):
    """Until this task, run() was a placeholder, so build_config was only ever
    called directly by unit tests and no test proved an LmiError raised inside
    it becomes an exit status. Cover the wiring end to end."""
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "5"]) == 2
    assert main(["schedule", "x", "-d", str(tmp_path), "-c", "3"]) == 2
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "1", "-c", "0"]) == 2
    assert main(["schedule", "x", "-d", str(tmp_path), "-t", "nonsense"]) == 2


def test_an_internal_failure_is_written_to_the_log(tmp_path, fake_claude, monkeypatch):
    """A crash in the runner must land in the log, not only on the terminal -
    otherwise an unattended run that died is undiagnosable afterwards.

    Patched outside the loop on purpose: a crash *inside* an iteration is no
    longer fatal (see the skipped-iteration tests below), so this needs a
    failure the per-iteration guard cannot catch to still reach exit 4.
    """
    def boom(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr("lmi.commands.schedule.runner.state.prepare", boom)
    rc = main(["schedule", "x", "-d", str(tmp_path)])
    assert rc == 4
    body = _log_body(tmp_path)
    assert "[ERROR]" in body
    assert "RuntimeError: synthetic" in body


# --- Critical 1: a long inline prompt, end to end -------------------------

def test_a_long_hebrew_inline_prompt_runs(tmp_path, fake_claude):
    """143 Hebrew characters are 286 bytes, which made the path classifier
    raise ENAMETOOLONG before the lock and before any logging."""
    long_prompt = "א" * 143
    assert main(["schedule", long_prompt, "-d", str(tmp_path)]) == 0
    assert _count(fake_claude) == 1
    got = (fake_claude.dir / "prompt-1.txt").read_text(encoding="utf-8")
    assert long_prompt in got


def test_an_over_long_log_path_exits_2_not_1(tmp_path, fake_claude):
    rc = main(["schedule", "x", "-d", str(tmp_path), "-l",
               str(tmp_path / ("L" * 300))])
    assert rc == 2
    assert _count(fake_claude) == 0


def test_an_over_long_state_path_exits_2_not_1(tmp_path, fake_claude):
    rc = main(["schedule", "x", "-d", str(tmp_path), "-s",
               str(tmp_path / ("S" * 300))])
    assert rc == 2
    assert _count(fake_claude) == 0


# --- the prose false positive, in the shape the old fixtures missed -------

def test_complete_on_line_two_does_not_stop_the_loop(tmp_path, fake_claude,
                                                     monkeypatch):
    """MANDATORY, end to end. The state file's line 1 is blank
    and line 2 says COMPLETE: a whole-file search matches (^\\s* spans the
    newline) and would stop the loop after iteration 1, while the line-1-only
    read correctly keeps going. Widening check_complete must turn this red."""
    monkeypatch.setenv("FAKE_STATE_FILE", _default_state(tmp_path))
    monkeypatch.setenv("FAKE_BLANK_FIRST_LINE", "1")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "3"]) == 0
    assert _count(fake_claude) == 3


# --- Important 4: an exception mid-iteration must not abort the loop ------

def test_a_wrecked_temp_workspace_skips_the_iteration_and_keeps_looping(
    tmp_path, fake_claude, monkeypatch
):
    """MANDATORY. Invariant 2's exception half. The stub deletes the runner's
    whole temp workspace after each call, so every iteration after the first
    cannot even write its prompt file. That used to end the run at iteration 2
    with exit 4; the loop must instead log [ERROR], count the iteration as
    failed and carry on to the last one."""
    private_tmp = tmp_path / "tmp"
    private_tmp.mkdir()
    # The environment variables are for the stub (a fresh process); the
    # attribute is for this process, whose tempfile has long since cached
    # gettempdir(). Both must point at the same private directory or the stub
    # deletes nothing.
    for var in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.setenv(var, str(private_tmp))
    monkeypatch.setattr("tempfile.tempdir", str(private_tmp))
    monkeypatch.setenv("FAKE_WRECK_TMP", "1")

    rc = main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "4"])
    assert rc == 1                      # iterations failed, the runner did not
    body = _log_body(tmp_path)
    # All four iterations ran. Before the guard this ended at iteration 2 with
    # exit 4 and iterations 3 and 4 never happened at all. (Iteration 1 is a
    # failure too: its output file vanished with the workspace before the
    # runner could read it back.)
    assert "4 run/s, 0 succeeded, 4 failed." in body
    for n in (2, 3, 4):
        assert "could not run iteration %d of 4 - it was skipped" % n in body
    assert "FileNotFoundError" in body   # the traceback reached the log


def test_a_transient_oserror_from_subprocess_is_survived(
    tmp_path, fake_claude, monkeypatch
):
    """The same guard, on the other realistic source: subprocess.run itself
    failing (EAGAIN, a vanished executable) rather than claude exiting."""
    real_run = __import__("subprocess").run
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("Resource temporarily unavailable")
        return real_run(*a, **k)

    monkeypatch.setattr("lmi.commands.schedule.runner.subprocess.run", flaky)
    rc = main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "3"])
    assert rc == 1
    body = _log_body(tmp_path)
    assert "3 run/s, 2 succeeded, 1 failed." in body
    assert _count(fake_claude) == 2


def test_a_bad_prompt_file_ends_the_run_as_a_usage_error(tmp_path, fake_claude):
    """The other side of the guard: a deterministic usage error must NOT be
    retried for every remaining iteration. It ends the run with exit 2, and
    the reason is in the log."""
    bad = tmp_path / "task.md"
    bad.write_bytes(b"\xff\xfe\xfe\xff\x00\x81\x8d")
    rc = main(["schedule", str(bad), "-d", str(tmp_path), "-i", "0", "-c", "5"])
    assert rc == 2
    assert _count(fake_claude) == 0
    assert "not UTF-8" in _log_body(tmp_path)


# --- Important 5: errors inside the locked region reach the log -----------

def test_a_state_write_failure_reaches_the_log_file(tmp_path, fake_claude,
                                                    monkeypatch):
    """MANDATORY. Design 8.2: nothing the runner reports is lost from the log.
    cli.py prints an LmiError on stderr, which for a Task Scheduler or cron
    run goes nowhere - the log would end at "State file : created new" with no
    reason at all, which is exactly the failure 8.1 claims to have fixed."""
    from lmi.core.errors import LmiError

    def boom(*a, **k):
        raise LmiError("cannot write the state file: synthetic", 2)

    monkeypatch.setattr(
        "lmi.commands.schedule.runner.state.write_template", boom
    )
    rc = main(["schedule", "x", "-d", str(tmp_path)])
    assert rc == 2
    body = _log_body(tmp_path)
    assert "[ERROR] cannot write the state file: synthetic" in body


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="needs POSIX symlinks")
def test_a_really_unwritable_state_path_reaches_the_log_file(
    tmp_path, fake_claude, readonly_dir
):
    """The same thing without a monkeypatch: the state file is a symlink into
    a read-only directory, so its directory (and therefore the lock and the
    log) are writable while the state file itself cannot be created. A
    dangling link on purpose - os.replace would otherwise just move the link
    aside and write a perfectly good regular file in its place."""
    link = tmp_path / "state.md"
    link.symlink_to(readonly_dir / "never-created.md")
    assert main(["schedule", "x", "-d", str(tmp_path), "-s", str(link)]) == 2
    body = _log_body(tmp_path)
    assert "[ERROR]" in body
    assert "state file" in body and "Permission denied" in body


@skip_as_root
def test_an_unwritable_state_directory_is_a_usage_error_not_a_bug(
    tmp_path, fake_claude, readonly_dir
):
    """The lock file lives beside the state file, so an unwritable state
    directory fails at the lock - which reported exit 4, "a bug in lmi", for
    what is plainly the user's path being wrong."""
    rc = main(["schedule", "x", "-d", str(tmp_path),
               "-s", str(readonly_dir / "state.md")])
    assert rc == 2


# --- Important 6: an unwritable log must not decide the exit code ---------

@skip_as_root
def test_an_unwritable_log_still_lets_the_run_succeed(
    tmp_path, fake_claude, readonly_dir, capsys
):
    """MANDATORY. -l pointing at a read-only directory used to double-fault:
    Logger.line raised, the handler called log.error, which raised the same
    PermissionError again - two tracebacks and exit 1, indistinguishable from
    a failed claude call."""
    assert main(["schedule", "x", "-d", str(tmp_path), "-l",
                 str(readonly_dir)]) == 0
    captured = capsys.readouterr()
    assert "fake claude call 1" in captured.out    # console intact
    assert "cannot be written" in captured.err     # warned once
    assert captured.err.count("cannot be written") == 1
    assert "Traceback" not in captured.err


# --- the resolved configuration in the header ----------------------------

def test_the_header_records_the_resolved_configuration(tmp_path, fake_claude):
    """README's Logging section promises the resolved configuration: the prompt
    source, the claude executable and the full flag list. Without them a log
    cannot be matched to what actually ran."""
    task = tmp_path / "task.md"
    task.write_text("do the thing\n", encoding="utf-8")
    assert main(["schedule", str(task), "-d", str(tmp_path),
                 "-f", "--model sonnet"]) == 0
    body = _log_body(tmp_path)
    assert "Prompt    : file " + str(task) in body
    assert str(fake_claude.exe) in body
    assert "--allowed-tools=Edit,Write" in body
    assert "--add-dir" in body
    assert "--model sonnet" in body


def test_the_header_records_an_inline_prompt(tmp_path, fake_claude):
    assert main(["schedule", "write a haiku", "-d", str(tmp_path)]) == 0
    assert "Prompt    : inline text: write a haiku" in _log_body(tmp_path)


# --- the state body and the completion check must decode alike ------------

def test_a_utf16_state_file_is_inlined_without_mojibake(tmp_path, fake_claude):
    state = tmp_path / "st.md"
    state.write_bytes("TASK_STATUS: IN_PROGRESS\n## Notes\nשלום\n".encode("utf-16"))
    assert main(["schedule", "x", "-d", str(tmp_path), "-s", str(state),
                 "-r"]) == 0
    got = (fake_claude.dir / "prompt-1.txt").read_text(encoding="utf-8")
    assert "שלום" in got


def test_verbose_puts_stream_json_on_the_command_line(tmp_path, fake_claude):
    main(["schedule", "hello", "-d", str(tmp_path), "-v"])
    argv = (fake_claude.dir / "argv-1.txt").read_text().splitlines()
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv


def test_verbose_flags_come_before_the_user_flags(tmp_path, fake_claude):
    """-v is one switch: the user never also needs -f "--verbose". lmi's own
    flags stay first so -f still composes after them, as README promises."""
    main(["schedule", "hello", "-d", str(tmp_path), "-v", "-f", "--model x"])
    argv = (fake_claude.dir / "argv-1.txt").read_text().splitlines()
    assert argv[-2:] == ["--model", "x"]
    assert argv.index("--output-format") < argv.index("--model")


def test_without_verbose_the_command_line_is_untouched(tmp_path, fake_claude):
    """The feature adds a path; it must not modify the existing one."""
    main(["schedule", "hello", "-d", str(tmp_path)])
    argv = (fake_claude.dir / "argv-1.txt").read_text().splitlines()
    assert "--output-format" not in argv
    assert "--verbose" not in argv


def test_verbose_renders_claude_events_into_the_log(tmp_path, fake_claude,
                                                    monkeypatch):
    monkeypatch.setenv("FAKE_STREAM", "1")
    assert main(["schedule", "x", "-d", str(tmp_path), "-v"]) == 0
    body = _log_body(tmp_path)
    assert "--- claude activity ---" in body
    assert "[claude] init" in body
    assert "fake claude call 1" in body
    assert "[claude] done" in body
    # The raw JSON must not reach the log - that is what rendering is for.
    assert '{"type"' not in body


def test_verbose_never_uses_the_capture_path(tmp_path, fake_claude,
                                             monkeypatch):
    """There is nothing to capture to a file when the lines are consumed as
    they arrive, so -v must not reach _capture_claude at all. Asserting on the
    absence of out-*.txt cannot work - the temp workspace is deleted when the
    run ends - so the seam is the function itself."""
    from lmi.commands.schedule import runner as runner_mod

    def forbidden(*a, **kw):
        raise AssertionError("-v took the capture path")

    monkeypatch.setattr(runner_mod, "_capture_claude", forbidden)
    monkeypatch.setenv("FAKE_STREAM", "1")
    assert main(["schedule", "x", "-d", str(tmp_path), "-v"]) == 0


def test_without_verbose_the_capture_path_is_still_used(tmp_path, fake_claude,
                                                       monkeypatch):
    """The mirror of the above: the existing path must stay the default."""
    from lmi.commands.schedule import runner as runner_mod

    def forbidden(*a, **kw):
        raise AssertionError("a run without -v took the streaming path")

    monkeypatch.setattr(runner_mod, "_stream_claude", forbidden)
    assert main(["schedule", "x", "-d", str(tmp_path)]) == 0


def test_a_clipped_message_inside_a_json_event_is_still_flagged(
        tmp_path, fake_claude, monkeypatch):
    """MANDATORY.

    The name of this test avoids every word in QUOTA_RE on purpose. pytest
    names its temp directory after the test function, the fake reports that
    directory as the session cwd, and the renderer puts the cwd in the init
    line - so a test called test_quota_... matches on its own directory name
    and passes whichever line the scan reads. That is how this test first
    went green with the guard inverted. Under stream-json the usage-limit wording lives inside a
    JSON event, and the renderer clips a long message. Scanning the RENDERED
    line rather than the raw one silently disables [QUOTA] - the one tag that
    tells an unattended run its result is not to be trusted.

    The wording is deliberately placed past the clip width. With a short
    message both scans find it and this test is a false green: it passed with
    the guard inverted before that was fixed."""
    monkeypatch.setenv("FAKE_STREAM", "1")
    monkeypatch.setenv("FAKE_STREAM_QUOTA_TAIL", "Claude usage limit reached")
    main(["schedule", "x", "-d", str(tmp_path), "-v"])
    body = _log_body(tmp_path)
    assert "[QUOTA]" in body
    # And the premise: the rendered line really did lose the wording, so the
    # tag can only have come from scanning the raw line.
    activity = [ln for ln in body.splitlines() if ln.startswith("[claude]")]
    assert not any("usage limit" in ln for ln in activity)


def test_a_failing_verbose_iteration_does_not_stop_the_loop(
        tmp_path, fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_STREAM", "1")
    monkeypatch.setenv("FAKE_RC", "1")
    rc = main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "3", "-v"])
    assert rc == 1
    assert _count(fake_claude) == 3
    assert "3 run/s, 0 succeeded, 3 failed." in _log_body(tmp_path)


def test_claude_output_is_logged_while_the_iteration_is_still_running(
        tmp_path, fake_claude, monkeypatch):
    """MANDATORY. The whole point of -v: output must reach the log as claude
    produces it, not after it exits. The fake blocks until the runner has
    logged its first event, then emits a second one. Under capture-then-replay
    nothing is logged until the process exits, so the fake times out and the
    second event never appears.

    This is the only test that can tell live from buffered, and the only one
    with a timing element - the fake's wait is bounded, so a regression fails
    cleanly rather than hanging the suite."""
    from lmi.core.log import Logger

    marker = tmp_path / "logged-the-first-line"
    real_line = Logger.line

    def line(self, msg=""):
        real_line(self, msg)
        if "fake claude call 1" in msg:
            marker.touch()

    monkeypatch.setattr(Logger, "line", line)
    monkeypatch.setenv("FAKE_STREAM", "1")
    monkeypatch.setenv("FAKE_LIVE_MARKER", str(marker))

    assert main(["schedule", "x", "-d", str(tmp_path), "-v"]) == 0
    assert "after-the-marker.py" in _log_body(tmp_path)


def test_verbose_logs_the_whole_prompt_on_the_first_iteration(
        tmp_path, fake_claude):
    main(["schedule", "write a haiku", "-d", str(tmp_path), "-v"])
    body = _log_body(tmp_path)
    assert "--- prompt sent to claude" in body
    assert "# Unattended automated run" in body     # the header
    assert "## State protocol - read this first" in body  # the protocol
    assert "write a haiku" in body                  # the task


def test_without_verbose_the_prompt_is_not_logged(tmp_path, fake_claude):
    main(["schedule", "write a haiku", "-d", str(tmp_path)])
    body = _log_body(tmp_path)
    assert "--- prompt sent to claude" not in body
    assert "## State protocol - read this first" not in body


def test_later_iterations_log_only_the_state(tmp_path, fake_claude):
    """Option A: the header, protocol and task are byte-identical every
    iteration - the task is read once before the loop and the protocol is a
    module constant - so repeating them is noise, not information."""
    main(["schedule", "write a haiku", "-d", str(tmp_path), "-i", "0", "-c", "3"
          , "-v"])
    body = _log_body(tmp_path)
    assert body.count("## State protocol - read this first") == 1
    assert body.count("--- state sent to claude") == 2
    assert body.count("--- prompt sent to claude") == 1


def test_the_state_block_of_a_later_iteration_is_logged(tmp_path, fake_claude):
    monkey = tmp_path / "run-claude-state.md"
    main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "2", "-v"])
    body = _log_body(tmp_path)
    assert monkey.exists()
    # The state template's first line, inside the second iteration's block.
    after = body.split("--- state sent to claude")[1]
    assert "TASK_STATUS: IN_PROGRESS" in after


def test_the_full_prompt_is_logged_by_whichever_iteration_reaches_it_first(
        tmp_path, fake_claude, monkeypatch):
    """MANDATORY. Keying "log it in full" off iteration number 1 is wrong: an
    iteration can die before compose() and still leave the loop running, so
    iteration 2 would print "unchanged from iteration 1" about text that was
    never written. The claim in that header has to be true."""
    from lmi.commands.schedule import prompt as prompt_mod
    real = prompt_mod.compose
    calls = []

    def flaky(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("the temp workspace vanished")
        return real(*a, **kw)

    monkeypatch.setattr(prompt_mod, "compose", flaky)
    main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "2", "-v"])
    body = _log_body(tmp_path)
    # Iteration 1 never got a prompt at all; iteration 2 must log the full one.
    assert body.count("--- prompt sent to claude") == 1
    assert "## State protocol - read this first" in body
    assert "--- state sent to claude" not in body


def test_the_header_says_verbose_is_on(tmp_path, fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_STREAM", "1")
    main(["schedule", "x", "-d", str(tmp_path), "-v"])
    assert "Verbose   : on" in _log_body(tmp_path)


def test_the_header_says_nothing_about_verbose_when_it_is_off(
        tmp_path, fake_claude):
    main(["schedule", "x", "-d", str(tmp_path)])
    assert "Verbose" not in _log_body(tmp_path)
