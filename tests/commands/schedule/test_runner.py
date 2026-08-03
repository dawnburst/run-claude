import os

from lmi.cli import main


def _count(fake):
    return int(fake.count_file.read_text())


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
    monkeypatch.setenv("FAKE_STATE_FILE", str(tmp_path / "run-claude-state.md"))
    monkeypatch.setenv("FAKE_COMPLETE_AT", "2")
    assert main(["schedule", "x", "-d", str(tmp_path), "-i", "0", "-c", "5"]) == 0
    assert _count(fake_claude) == 2


def test_prose_complete_does_not_stop_the_loop(tmp_path, fake_claude, monkeypatch):
    """MANDATORY, landmine 14. Widening the check must turn this red."""
    monkeypatch.setenv("FAKE_STATE_FILE", str(tmp_path / "run-claude-state.md"))
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
    log = next(tmp_path.glob("run-claude-*.log"))
    assert "fake claude call 1" in log.read_text(encoding="utf-8")


def test_at_in_the_past_starts_immediately(tmp_path, fake_claude):
    rc = main(["schedule", "x", "-d", str(tmp_path), "-t", "2020-01-01 00:00"])
    assert rc == 0 and _count(fake_claude) == 1


def test_second_run_is_refused_while_the_lock_is_held(tmp_path, fake_claude):
    from lmi.core.lock import single_instance_lock
    lock = tmp_path / "run-claude.lock"
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
    otherwise an unattended run that died is undiagnosable afterwards."""
    def boom(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr("lmi.commands.schedule.runner.prompt.compose", boom)
    rc = main(["schedule", "x", "-d", str(tmp_path)])
    assert rc == 4
    body = next(tmp_path.glob("run-claude-*.log")).read_text(encoding="utf-8")
    assert "[ERROR]" in body
    assert "RuntimeError: synthetic" in body
