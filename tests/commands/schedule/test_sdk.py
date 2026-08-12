"""The SDK backend, end to end through `main(["schedule", ...])`.

Every test here drives the real `runner.py`, the real `sdk.py` and the real
`stream.py`; only `claude_agent_sdk` itself is replaced, in `sys.modules`, by
`fake_sdk`. That is deliberate - the seam this command has to get right is
between lmi and the SDK, so anything faked on lmi's side of it would be a test
of the fake.
"""

from lmi.cli import main
from lmi.commands.schedule import backend, paths, sdk

from .conftest import FIXTURE_SOURCE, _REAL_SDK_REQUIRE


def _log_body(tmp_path):
    return next(tmp_path.glob(paths.LOG_PREFIX + "*.log")).read_text(
        encoding="utf-8"
    )


def _default_state(tmp_path):
    return str(tmp_path / paths.STATE_NAME)


def _count(fake):
    return int(fake.count_file.read_text())


# --- the seam holds -------------------------------------------------------

def test_a_single_sdk_run_calls_query_once(tmp_path, fake_sdk):
    assert main(["schedule", "hello", "-d", str(tmp_path)]) == 0
    assert _count(fake_sdk) == 1


def test_the_composed_prompt_is_passed_as_a_string(tmp_path, fake_sdk):
    """Task 35. query() takes the text directly, so this backend writes no
    prompt-N.txt at all - the prompt reaches it as an argument."""
    main(["schedule", "write a haiku", "-d", str(tmp_path)])
    composed = fake_sdk.prompts[0]
    assert "# Unattended automated run" in composed
    assert "## CURRENT STATE" in composed
    assert "write a haiku" in composed


def test_the_loop_still_runs_count_times(tmp_path, fake_sdk):
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "3"]) == 0
    assert _count(fake_sdk) == 3


# --- task 32: the options carry exactly what the argv carries -------------

def test_the_options_carry_the_cli_backends_whole_argv(tmp_path, fake_sdk):
    """MANDATORY. `_claude_argv` is the specification and nothing may be lost
    on the way across. The two backends must grant the same tools and the same
    directories, or a task that works in one mode mysteriously cannot write the
    state file in the other - and that failure looks like Claude being unhelpful
    rather than like lmi being wrong."""
    state = tmp_path / "sub" / "state.md"
    state.parent.mkdir()
    assert main(["schedule", "x", "-d", str(tmp_path), "-s", str(state)]) == 0

    options = fake_sdk.options[0]
    assert options.allowed_tools == ["Edit", "Write"]        # --allowed-tools
    assert options.add_dirs == [str(state.parent)]           # --add-dir
    assert options.cwd == str(tmp_path)                      # subprocess cwd


def test_the_tool_list_is_the_one_both_backends_read(tmp_path, fake_sdk):
    """Not spelled out twice. `backend.ALLOWED_TOOLS` is the single definition
    the CLI backend renders into its flag and this one hands to the options, so
    a tool added to one is added to both."""
    main(["schedule", "x", "-d", str(tmp_path)])
    assert fake_sdk.options[0].allowed_tools == list(backend.ALLOWED_TOOLS)


# --- task 33: nothing may ever wait for a keypress ------------------------

def test_the_permission_mode_is_non_interactive(tmp_path, fake_sdk):
    """MANDATORY. Invariant 3. The SDK's *default* permission mode asks, and an
    unattended runner has nobody to answer - so the failure is not an error but
    a **hang**, which is worse: the run never ends, never logs a result and
    never releases the lock.

    `can_use_tool` is asserted absent in the same test because it is the other
    half of the same rule: a callback that awaits anything is a keypress wait
    wearing a library's clothes."""
    main(["schedule", "x", "-d", str(tmp_path)])
    options = fake_sdk.options[0]
    assert options.permission_mode == "acceptEdits"
    assert options.permission_mode != "default"
    assert options.can_use_tool is None


# --- task 34: the user settings source ------------------------------------

def test_the_user_settings_source_is_requested(tmp_path, fake_sdk):
    """MANDATORY. The sharpest asymmetry between the backends. The CLI read
    ~/.claude/settings.json by virtue of BEING the CLI; the SDK loads settings
    only from the sources it is told to.

    **Silent** if omitted: SDK mode runs against the wrong endpoint with no
    credentials, while `lmi config switch` - whose entire purpose is changing
    that file - quietly stops affecting `lmi schedule` at all. Project and
    local are asserted too, because the CLI reads those as well and a backend
    reading a different set of files from the other is a difference nobody can
    see in the result."""
    main(["schedule", "x", "-d", str(tmp_path)])
    sources = fake_sdk.options[0].setting_sources
    assert sources is not None, "setting_sources was not passed at all"
    assert "user" in sources
    assert "project" in sources and "local" in sources


# --- task 38: the rc table, all four rows ---------------------------------

def test_a_success_result_is_exit_zero(tmp_path, fake_sdk):
    assert main(["schedule", "x", "-d", str(tmp_path)]) == 0


def test_a_non_success_result_is_a_failed_iteration(tmp_path, fake_sdk,
                                                    monkeypatch):
    monkeypatch.setenv("FAKE_RC", "1")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "2"]) == 1
    assert _count(fake_sdk) == 2          # and the loop still finished
    assert "2 run/s, 0 succeeded, 2 failed." in _log_body(tmp_path)


def test_a_stream_with_no_result_message_is_a_failure(tmp_path, fake_sdk,
                                                      monkeypatch):
    """MANDATORY. The row that must not be a zero. The SDK ends every completed
    query with a ResultMessage, so its absence means the stream was cut off -
    and mapping that to 0 is regression 1 with a new front end: the iteration
    is counted as a success, the run exits 0, and nothing was done."""
    monkeypatch.setenv("FAKE_SDK_NO_RESULT", "1")
    assert main(["schedule", "x", "-d", str(tmp_path)]) == 1
    assert "FAILED" in _log_body(tmp_path)


def test_a_failed_call_is_distinguishable_from_a_skipped_iteration(
        tmp_path, fake_sdk, monkeypatch):
    """The two non-zero codes mean different things and the log has to say
    which: 90 is "never reached Claude at all", and a call that came back wrong
    is a different fact. Folding them together leaves an unattended log unable
    to tell a broken backend from a broken workspace."""
    from lmi.commands.schedule import runner
    assert sdk.CALL_FAILED_RC != runner.ITERATION_ERROR_RC

    monkeypatch.setenv("FAKE_RC", "1")
    main(["schedule", "x", "-d", str(tmp_path)])
    body = _log_body(tmp_path)
    assert "claude exit code %d" % sdk.CALL_FAILED_RC in body
    assert "was skipped" not in body


def test_an_exception_out_of_the_sdk_skips_the_iteration_and_keeps_looping(
        tmp_path, fake_sdk, monkeypatch):
    """MANDATORY. Item 12 and invariant 2's exception half, in the mode that
    has no temp workspace to wreck: the message stream dies part-way through.
    The iteration is recorded as skipped and the loop carries on. Removing the
    `except Exception` clause from `_iteration_rc` must turn this red - and its
    CLI-mode twin with it."""
    monkeypatch.setenv("FAKE_SDK_RAISE_AT", "2")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "4"]) == 1
    body = _log_body(tmp_path)
    assert "4 run/s, 3 succeeded, 1 failed." in body
    assert "could not run iteration 2 of 4 - it was skipped" in body
    assert "RuntimeError" in body          # the traceback reached the log


# --- task 39: the quota scan reads the message, never the rendered row ----

def test_quota_wording_in_the_result_is_flagged(tmp_path, fake_sdk,
                                                monkeypatch):
    monkeypatch.setenv("FAKE_OUT", "Error: you have exceeded your usage limit")
    main(["schedule", "x", "-d", str(tmp_path)])
    assert "[QUOTA]" in _log_body(tmp_path)


def test_the_quota_scan_survives_the_renderer_being_useless(
        tmp_path, fake_sdk, monkeypatch):
    """MANDATORY. Item 28, restated for a shape where "the raw line" no longer
    exists. The scan runs off the message's own attributes BEFORE anything
    renders it, so no future change to stream.py can disable [QUOTA] - the one
    tag that tells an unattended run its result is not to be trusted.

    Proved by stubbing the renderer out entirely: with `render` returning a
    constant, a scan that read the rendered row would find nothing at all."""
    from lmi.commands.schedule import stream

    monkeypatch.setattr(stream.MessageRenderer, "render",
                        lambda self, message: "[claude] (rendering disabled)")
    monkeypatch.setenv("FAKE_OUT", "Claude usage limit reached")
    main(["schedule", "x", "-d", str(tmp_path), "-v"])
    body = _log_body(tmp_path)
    assert "[QUOTA]" in body
    # The premise: with the renderer stubbed out, the wording reached the log
    # nowhere at all - so the tag can only have come from the message itself.
    assert "usage limit" not in body


def test_a_clipped_result_message_is_still_flagged(tmp_path, fake_sdk,
                                                   monkeypatch):
    """The SDK twin of the CLI's clipped-message test: the wording sits past
    the renderer's clip width, so the tag can only have come from scanning the
    message rather than the row."""
    monkeypatch.setenv("FAKE_STREAM_QUOTA_TAIL", "Claude usage limit reached")
    main(["schedule", "x", "-d", str(tmp_path), "-v"])
    body = _log_body(tmp_path)
    assert "[QUOTA]" in body
    activity = [ln for ln in body.splitlines() if ln.startswith("[claude]")]
    assert not any("usage limit" in ln for ln in activity)


# --- task 40: the SDK's stderr reaches the log ---------------------------

def test_the_sdk_stderr_callback_lands_in_the_log(tmp_path, fake_sdk,
                                                  monkeypatch):
    """CLI mode gets the binary's diagnostics through stderr=subprocess.STDOUT.
    Without the callback they vanish, and an unattended run's only record loses
    the half of the output that says why something failed."""
    monkeypatch.setenv("FAKE_SDK_STDERR", "spawn: something went sideways")
    main(["schedule", "x", "-d", str(tmp_path)])
    assert "spawn: something went sideways" in _log_body(tmp_path)


def test_quota_wording_on_stderr_is_flagged_too(tmp_path, fake_sdk,
                                                monkeypatch):
    monkeypatch.setenv("FAKE_SDK_STDERR", "429: too many requests")
    main(["schedule", "x", "-d", str(tmp_path)])
    assert "[QUOTA]" in _log_body(tmp_path)


def test_quota_survives_the_sdk_raising_after_the_result(
        tmp_path, fake_sdk, monkeypatch):
    """MANDATORY. Item 45, and the reason the whole quota scan nearly did not
    work in SDK mode at all.

    The real SDK yields the ResultMessage and then raises on the error envelope
    behind it, so on every failure it reports this way the exception used to
    carry off both facts the sink had already computed - the exit code and the
    quota flag. An exhausted quota is exactly such a failure, which made
    [QUOTA] unreachable in SDK mode precisely when it matters."""
    monkeypatch.setenv("FAKE_OUT", "Claude usage limit reached")
    monkeypatch.setenv("FAKE_RC", "1")
    monkeypatch.setenv("FAKE_SDK_RAISE_AFTER_RESULT", "1")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "1"]) == 1
    assert "[QUOTA]" in _log_body(tmp_path)


def test_an_error_result_is_a_failed_call_not_a_skipped_iteration(
        tmp_path, fake_sdk, monkeypatch):
    """MANDATORY. Item 45's other half, and item 41's distinction.

    ITERATION_ERROR_RC means "never reached Claude at all". A call that reached
    Claude and came back wrong is a different fact, and letting the SDK's
    post-result exception propagate reported the wrong one - so an expired
    login read as a broken workspace."""
    monkeypatch.setenv("FAKE_RC", "1")
    monkeypatch.setenv("FAKE_SDK_RAISE_AFTER_RESULT", "1")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "2"]) == 1
    body = _log_body(tmp_path)
    assert "2 run/s, 0 succeeded, 2 failed." in body
    assert "claude exit code %d" % sdk.CALL_FAILED_RC in body
    assert "it was skipped" not in body
    # The reason survives, on one line rather than as a traceback.
    assert "the SDK reported the call failed" in body


def test_a_success_subtype_with_is_error_set_is_a_failure(
        tmp_path, fake_sdk, monkeypatch):
    """MANDATORY. The shape a REAL failed call has, and the one that fooled the
    first version of _rc_of.

    With no valid credential the SDK returns `subtype == "success"` and
    `is_error == True` together - "returned an error result: success" - so a gate
    on the subtype alone reported an iteration that did nothing as a success:
    exit 0, "1 succeeded", regression 1 with a new front end. Verified against
    claude-agent-sdk 0.2.136 by a real run, not inferred."""
    monkeypatch.setenv("FAKE_RC", "1")
    monkeypatch.setenv("FAKE_SDK_SUCCESS_SUBTYPE_ON_ERROR", "1")
    monkeypatch.setenv("FAKE_SDK_RAISE_AFTER_RESULT", "1")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "1"]) == 1
    body = _log_body(tmp_path)
    assert "1 run/s, 0 succeeded, 1 failed." in body
    assert "claude exit code %d" % sdk.CALL_FAILED_RC in body


def test_a_raise_before_any_result_is_still_a_skip(tmp_path, fake_sdk,
                                                   monkeypatch):
    """The other side of item 45's split, so the two cannot be collapsed.

    Nothing is known about a call that produced no result, so item 12's
    behaviour is unchanged: the iteration is recorded as skipped, the traceback
    reaches the log, and the loop carries on."""
    monkeypatch.setenv("FAKE_SDK_RAISE_AT", "1")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "2"]) == 1
    body = _log_body(tmp_path)
    assert "could not run iteration 1 of 2 - it was skipped" in body
    assert "2 run/s, 1 succeeded, 1 failed." in body


def test_a_rate_limit_event_is_flagged(tmp_path, fake_sdk, monkeypatch):
    """MANDATORY. Item 43, and the one shape the scan originally missed.

    RateLimitEvent carries its whole payload in `rate_limit_info` and nothing in
    `result`, `content` or `data` - so a scan of those three found nothing on
    the SDK's own name for the thing [QUOTA] exists to catch, while the CLI
    backend caught the equivalent for free by scanning whole raw lines. Silent,
    and in the direction that under-reports: the iteration exits 0 and the log
    says the run is trustworthy.

    Do not narrow sdk._TEXT_ATTRS back to the three obvious fields."""
    monkeypatch.setenv("FAKE_SDK_RATE_LIMIT", "rejected")
    assert main(["schedule", "x", "-d", str(tmp_path)]) == 0
    assert "[QUOTA]" in _log_body(tmp_path)


def test_a_healthy_rate_limit_event_is_not_flagged(tmp_path, fake_sdk,
                                                   monkeypatch):
    """MANDATORY. Item 43's other direction, and a real regression.

    The SDK emits RateLimitEvent on healthy iterations too, with
    `status='allowed'`. Running QUOTA_RE over the event tagged every one of
    them, because its own repr contains "RateLimitInfo" and "rate_limit_type"
    and the pattern matches `rate.?limit`. A tag that fires on every successful
    run is exactly as useless as one that never fires, and it trains an operator
    to ignore the only warning that matters."""
    monkeypatch.setenv("FAKE_SDK_RATE_LIMIT", "allowed")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "1"]) == 0
    body = _log_body(tmp_path)
    assert "1 run/s, 1 succeeded, 0 failed." in body
    assert "[QUOTA]" not in body


def test_a_rate_limit_event_does_not_spend_the_degrade_warning(
        tmp_path, fake_sdk, monkeypatch):
    """A recognised message type must not be described as an unknown one.

    The warning is once per iteration, so leaving RateLimitEvent to _give_up
    spent it on a type lmi does know - and a genuinely unknown type arriving
    afterwards then passed with no warning at all, which is the half of task 41
    that makes -v trustworthy."""
    monkeypatch.setenv("FAKE_SDK_RATE_LIMIT", "rejected")
    monkeypatch.setenv("FAKE_SDK_UNKNOWN", "1")
    assert main(["schedule", "x", "-d", str(tmp_path), "-v"]) == 0
    body = _log_body(tmp_path)
    warnings = [ln for ln in body.splitlines() if "[WARN]" in ln]
    assert len(warnings) == 1, warnings
    # Spent on the unknown shape, not on the rate limit.
    assert "_Unknown" in body
    assert "[claude] limit" in body


# --- task 41 and 42: the renderer -----------------------------------------

def test_verbose_renders_the_activity(tmp_path, fake_sdk):
    assert main(["schedule", "x", "-d", str(tmp_path), "-v"]) == 0
    body = _log_body(tmp_path)
    assert "--- claude activity ---" in body
    assert "[claude] init" in body
    assert "fake claude call 1" in body
    assert "[claude] done" in body


def test_without_verbose_only_the_result_text_is_logged(tmp_path, fake_sdk,
                                                        monkeypatch):
    """The analogue of CLI non-verbose, where claude prints only its final
    answer. -v is what buys rendered activity, in both modes."""
    monkeypatch.setenv("FAKE_OUT", "the final answer")
    assert main(["schedule", "x", "-d", str(tmp_path)]) == 0
    body = _log_body(tmp_path)
    assert "the final answer" in body
    assert "[claude] init" not in body


def test_a_write_tool_input_never_puts_the_file_into_the_log(
        tmp_path, fake_sdk, monkeypatch):
    """MANDATORY. Item 29 and task 42. `ARG_KEYS` is an allowlist for exactly
    this: a Write's `content` is the whole new file, so rendering it puts the
    state file into the log on every single save and buries the tool calls
    either side of it. The typed block makes that field easier to reach than a
    JSON dict did, which makes the rule easier to break."""
    body_text = "SECRET-STATE-BODY " * 50
    monkeypatch.setenv("FAKE_SDK_TOOL_INPUT", body_text)
    assert main(["schedule", "x", "-d", str(tmp_path), "-v"]) == 0
    log = _log_body(tmp_path)
    assert "SECRET-STATE-BODY" not in log
    # And the premise: the tool call itself WAS rendered, by its file path.
    assert "run-claude-state.md" in log


def test_an_unknown_message_type_warns_once_and_carries_on(
        tmp_path, fake_sdk, monkeypatch):
    """Task 41's degrade-out-loud half. A message type a later SDK adds must
    cost one [WARN] and one dull line - never an exception, which would reach
    _iteration_rc and abandon the whole iteration.

    One iteration, because the renderer is built per iteration in both modes -
    `_Sink` makes a new one each time, exactly as `_stream_claude` does - so
    "warns once" is once per iteration, not once per run."""
    monkeypatch.setenv("FAKE_SDK_UNKNOWN", "1")
    assert main(["schedule", "x", "-d", str(tmp_path), "-v"]) == 0
    body = _log_body(tmp_path)
    assert body.count("message types this lmi does not know") == 1
    assert "[claude] event" in body


# --- regression 2, in the other mode -------------------------------------

def test_prose_complete_does_not_stop_the_sdk_loop(tmp_path, fake_sdk,
                                                   monkeypatch):
    """MANDATORY. Regression 2 in SDK mode. Claude reliably restates the
    protocol sentence inside the state file, so a whole-file search matches
    that prose and stops a -c 5 run after iteration 1 while reporting success.
    Widening `check_complete` must turn this red in BOTH modes - a knob that
    worked in one of them would be a regression test covering half of what it
    claims."""
    monkeypatch.setenv("FAKE_STATE_FILE", _default_state(tmp_path))
    monkeypatch.setenv("FAKE_PROSE", "1")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "3"]) == 0
    assert _count(fake_sdk) == 3


def test_complete_on_line_two_does_not_stop_the_sdk_loop(tmp_path, fake_sdk,
                                                         monkeypatch):
    """MANDATORY. The other half of regression 2: line 1 blank, line 2
    COMPLETE. A whole-file search matches (^\\s* spans the newline)."""
    monkeypatch.setenv("FAKE_STATE_FILE", _default_state(tmp_path))
    monkeypatch.setenv("FAKE_BLANK_FIRST_LINE", "1")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "3"]) == 0
    assert _count(fake_sdk) == 3


def test_line_one_complete_still_stops_the_sdk_loop_early(tmp_path, fake_sdk,
                                                          monkeypatch):
    """And the positive case, so the two above cannot pass by the completion
    check being broken outright."""
    monkeypatch.setenv("FAKE_STATE_FILE", _default_state(tmp_path))
    monkeypatch.setenv("FAKE_COMPLETE_AT", "2")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "5"]) == 0
    assert _count(fake_sdk) == 2


# --- item 33: the header names the backend and what chose it -------------

def test_the_header_names_the_sdk_backend_and_its_source(tmp_path, fake_sdk):
    """MANDATORY. The plan's central silent failure. Both backends exit 0 on
    success and neither marks the state file, so without this line **nothing**
    in an unattended run's only record distinguishes a run that used the
    intended backend from one that did not - and the entire point of a switch
    is that the outcome cannot tell you.

    The source is half the line: "sdk" alone does not say whether a config file
    chose it or nothing did."""
    assert main(["schedule", "x", "-d", str(tmp_path)]) == 0
    assert "Backend   : sdk (from %s)" % FIXTURE_SOURCE in _log_body(tmp_path)


def test_the_header_describes_what_this_backend_resolved(tmp_path, fake_sdk):
    """There is no argv here to print, so the header carries the options that
    decide what Claude may do instead - which is the half of the CLI's Flags
    line that actually matters."""
    main(["schedule", "x", "-d", str(tmp_path)])
    body = _log_body(tmp_path)
    assert "Tools     : Edit,Write" in body
    assert "Permission: acceptEdits" in body
    assert "Settings  : user,project,local" in body


def test_the_sdk_backend_uses_no_temp_workspace(tmp_path, fake_sdk,
                                                monkeypatch):
    """Task 35's other half. The temp workspace is still created - the runner
    does not branch on the mode and the CLI backend needs it - but this backend
    must not write into it. Asserted by pointing tempfile at a directory of our
    own and finding nothing in the workspace afterwards."""
    private_tmp = tmp_path / "tmp"
    private_tmp.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(private_tmp))

    main(["schedule", "x", "-d", str(tmp_path)])
    assert fake_sdk.prompts[0]                       # it went as an argument
    assert not list(private_tmp.glob("**/prompt-*.txt"))
    assert not list(private_tmp.glob("**/out-*.txt"))


# --- item 34: no fallback, and a loud failure ----------------------------

def test_a_missing_sdk_is_exit_2_naming_every_way_out(tmp_path, sdk_mode,
                                                      monkeypatch):
    """MANDATORY. Item 34. There is deliberately no run-time fallback to the
    CLI backend: both backends exit 0 on success, so a runner that quietly
    changed backend produces a log that looks exactly like a correct run. The
    fallback is the installer's, once, written into a file a human can read.

    Deliberately takes `sdk_mode` and NOT `fake_sdk` - the import has to fail,
    which is the one SDK-mode test that must not have a fake module installed.
    `sdk_mode`'s refusal stub is bypassed because `require()` raises before
    `call` is ever reached."""
    import sys as _sys
    monkeypatch.setattr(sdk, "require", _REAL_SDK_REQUIRE)
    # None in sys.modules is the documented way to make `import x` raise
    # ImportError, so this covers the real shape: the package is simply not
    # importable from the interpreter that will run `lmi schedule`.
    monkeypatch.setitem(_sys.modules, "claude_agent_sdk", None)

    rc = main(["schedule", "x", "-d", str(tmp_path)])
    assert rc == 2
    # No log iterations: the check runs before the lock and before the header.
    logs = list(tmp_path.glob(paths.LOG_PREFIX + "*.log"))
    if logs:
        assert "iteration 1" not in logs[0].read_text(encoding="utf-8")


def test_the_missing_sdk_message_offers_all_three_fixes():
    """The message is the whole of what an operator has to go on, so it names
    the installer, the pip line and the way to run without the SDK at all."""
    text = sdk.MISSING % (backend.SDK, "No module named 'claude_agent_sdk'",
                          backend.CLI, backend.CLI)
    assert "lmi install claude" in text
    assert 'pip install "lmi[sdk]"' in text
    assert "lmi config schedule --mode cli" in text
    assert "does not fall back" in text
