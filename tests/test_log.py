import os

import pytest

from lmi.core.log import Logger


def test_writes_to_console_and_file(tmp_path, capsys):
    log = Logger(tmp_path / "run.log")
    log.line("hello")
    assert capsys.readouterr().out == "hello\n"
    assert (tmp_path / "run.log").read_text(encoding="utf-8") == "hello\n"


def test_tags(tmp_path, capsys):
    log = Logger(tmp_path / "run.log")
    log.warn("careful")
    log.error("broken")
    log.quota("limits")
    out = capsys.readouterr().out
    assert "[WARN] careful" in out
    assert "[ERROR] broken" in out
    assert "[QUOTA] limits" in out
    assert (tmp_path / "run.log").read_text(encoding="utf-8").count("[") == 3


def test_blank_line(tmp_path, capsys):
    log = Logger(tmp_path / "run.log")
    log.line()
    assert capsys.readouterr().out == "\n"


def test_non_ascii_survives_a_round_trip(tmp_path):
    log = Logger(tmp_path / "run.log")
    log.line("שלום עולם")
    assert "שלום עולם" in (tmp_path / "run.log").read_text(encoding="utf-8")


def test_appends_rather_than_truncating(tmp_path):
    log = Logger(tmp_path / "run.log")
    log.line("first")
    Logger(tmp_path / "run.log").line("second")
    body = (tmp_path / "run.log").read_text(encoding="utf-8")
    assert body == "first\nsecond\n"


def test_an_unwritable_log_never_raises_and_keeps_the_console(tmp_path, capsys):
    """MANDATORY. The .bat's :log ignores an append failure and finishes the
    run with console output intact. Raising here double-faulted: the runner's
    handler called log.error, which raised the same PermissionError again, for
    a two-level traceback and exit 1 - indistinguishable from a failed claude
    call, with exit 4 unreachable exactly when logging is what broke."""
    unwritable = tmp_path            # a directory: open(..., "a") cannot
    log = Logger(unwritable)
    log.line("first")                # must not raise
    log.error("second")
    log.warn("third")
    log.quota("fourth")
    captured = capsys.readouterr()
    # Every line still reached the console.
    for text in ("first", "[ERROR] second", "[WARN] third", "[QUOTA] fourth"):
        assert text in captured.out
    # And the reason was reported once, on stderr, not once per line.
    assert captured.err.count("cannot be written") == 1
    assert log.file_broken is True


@pytest.mark.skipif(
    getattr(os, "geteuid", lambda: 1)() == 0,
    reason="root ignores file permissions",
)
def test_a_read_only_log_file_degrades_to_console_only(tmp_path, capsys):
    target = tmp_path / "run.log"
    target.write_text("", encoding="utf-8")
    target.chmod(0o400)
    try:
        log = Logger(target)
        log.line("hello")
        captured = capsys.readouterr()
        assert "hello" in captured.out
        assert "cannot be written" in captured.err
    finally:
        target.chmod(0o600)
