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
