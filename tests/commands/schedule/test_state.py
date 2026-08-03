from pathlib import Path

import pytest

from lmi.commands.schedule.state import (
    check_complete, prepare, write_template,
)
from lmi.core.errors import LmiError
from lmi.core.log import Logger

TS = "20260803-101500"


def _log(tmp_path):
    return Logger(tmp_path / "run.log")


# --- check_complete: landmine 14 -----------------------------------------

def test_complete_on_line_one_is_complete(tmp_path):
    p = tmp_path / "s.md"
    p.write_text("TASK_STATUS: COMPLETE\n\n## Completed\n", encoding="utf-8")
    assert check_complete(p) is True


def test_prose_mentioning_complete_lower_down_is_NOT_complete(tmp_path):
    """MANDATORY. Landmine 14: real claude restates the protocol sentence
    inside the state file. A whole-file search matches that prose and stops
    the loop after one iteration while reporting success - silently
    abandoning most of the work. Widening this check must turn this red."""
    p = tmp_path / "s.md"
    p.write_text(
        "TASK_STATUS: IN_PROGRESS\n\n## Goal\n\n"
        "Only after step 5 may the first line become TASK_STATUS: COMPLETE.\n",
        encoding="utf-8",
    )
    assert check_complete(p) is False


def test_utf8_bom_before_complete_still_counts(tmp_path):
    p = tmp_path / "s.md"
    p.write_bytes(b"\xef\xbb\xbfTASK_STATUS: COMPLETE\n")
    assert check_complete(p) is True


def test_leading_whitespace_and_tight_colon(tmp_path):
    p = tmp_path / "s.md"
    p.write_text("   TASK_STATUS:COMPLETE\n", encoding="utf-8")
    assert check_complete(p) is True


def test_trailing_punctuation_counts_word_boundary(tmp_path):
    """The .bat's PowerShell regex uses \\b, so a trailing period counts."""
    p = tmp_path / "s.md"
    p.write_text("TASK_STATUS: COMPLETE.\n", encoding="utf-8")
    assert check_complete(p) is True


def test_completed_does_not_count(tmp_path):
    p = tmp_path / "s.md"
    p.write_text("TASK_STATUS: COMPLETED\n", encoding="utf-8")
    assert check_complete(p) is False


def test_lowercase_status_line_is_complete_case_insensitively(tmp_path):
    """MANDATORY. run-claude.bat's PowerShell '-match' is case-insensitive
    by default ('-cmatch' is the case-sensitive form, and it is not used),
    so a first line of 'task_status: complete' is COMPLETE to the .bat. A
    state file must be interchangeable between the two tools."""
    p = tmp_path / "s.md"
    p.write_text("task_status: complete\n", encoding="utf-8")
    assert check_complete(p) is True

    # The word-boundary must still hold regardless of case.
    p2 = tmp_path / "s2.md"
    p2.write_text("Task_Status: Completed\n", encoding="utf-8")
    assert check_complete(p2) is False


def test_utf16_encoded_state_file_is_detected(tmp_path):
    """PowerShell's Get-Content auto-detects UTF-16 from its BOM. A state
    file hand-edited in a Windows editor may be UTF-16, and must not be
    silently treated as never complete."""
    p = tmp_path / "s.md"
    p.write_bytes("TASK_STATUS: COMPLETE\n".encode("utf-16"))
    assert check_complete(p) is True


def test_missing_or_empty_file_is_not_complete(tmp_path):
    assert check_complete(tmp_path / "absent.md") is False
    (tmp_path / "empty.md").write_text("", encoding="utf-8")
    assert check_complete(tmp_path / "empty.md") is False


# --- template and prepare ------------------------------------------------

def test_template_starts_in_progress_and_names_lmi(tmp_path):
    p = tmp_path / "s.md"
    write_template(p, "2026-08-03 10:15:00")
    body = p.read_text(encoding="utf-8")
    assert body.splitlines()[0] == "TASK_STATUS: IN_PROGRESS"
    assert "lmi schedule" in body
    assert "run-claude.bat" not in body
    for heading in ("## Goal", "## Completed", "## In progress",
                    "## Next steps", "## Notes and blockers"):
        assert heading in body


def test_unwritable_state_path_is_a_clear_error(tmp_path):
    """MANDATORY. The .bat logs "created new" even when the write failed,
    so the loop then repeats iteration 1 forever while reporting success.
    That silent shape is landmine 13; lmi must fail loudly instead."""
    with pytest.raises(LmiError) as exc:
        write_template(tmp_path, "2026-08-03 10:15:00")  # a directory
    assert exc.value.code == 2


def test_prepare_creates_a_fresh_file_when_none_exists(tmp_path):
    p = tmp_path / "s.md"
    prepare(p, resume=False, run_ts=TS, log=_log(tmp_path))
    assert p.read_text(encoding="utf-8").splitlines()[0] == "TASK_STATUS: IN_PROGRESS"


def test_prepare_backs_up_and_starts_clean(tmp_path):
    p = tmp_path / "s.md"
    p.write_text("TASK_STATUS: IN_PROGRESS\nold content\n", encoding="utf-8")
    prepare(p, resume=False, run_ts=TS, log=_log(tmp_path))
    backups = list(tmp_path.glob("s.md.*.bak"))
    assert len(backups) == 1
    assert "old content" in backups[0].read_text(encoding="utf-8")
    assert "old content" not in p.read_text(encoding="utf-8")


def test_resume_keeps_the_existing_file(tmp_path):
    p = tmp_path / "s.md"
    p.write_text("TASK_STATUS: IN_PROGRESS\nkeep me\n", encoding="utf-8")
    prepare(p, resume=True, run_ts=TS, log=_log(tmp_path))
    assert "keep me" in p.read_text(encoding="utf-8")
    assert list(tmp_path.glob("s.md.*.bak")) == []


def test_failed_backup_reuses_the_file_rather_than_clobbering(tmp_path, monkeypatch):
    """The .bat logs [WARN] and reuses the file as is when the move fails."""
    p = tmp_path / "s.md"
    p.write_text("TASK_STATUS: IN_PROGRESS\nprecious\n", encoding="utf-8")

    def boom(*a, **k):
        raise OSError("nope")

    monkeypatch.setattr("lmi.commands.schedule.state.os.replace", boom)
    log = _log(tmp_path)
    prepare(p, resume=False, run_ts=TS, log=log)
    assert "precious" in p.read_text(encoding="utf-8")
    assert "[WARN]" in (tmp_path / "run.log").read_text(encoding="utf-8")
