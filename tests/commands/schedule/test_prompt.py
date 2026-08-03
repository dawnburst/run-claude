import pytest

from lmi.commands.schedule.config import Config
from lmi.commands.schedule.prompt import compose, read_prompt_source
from lmi.core.errors import LmiError


def _cfg(tmp_path, **kw):
    base = dict(prompt_text="write a haiku", prompt_file=None, at=None,
                interval_min=0, max_runs=1, work_dir=tmp_path, user_flags=[],
                log_arg=None, state_arg=None, resume=False)
    base.update(kw)
    return Config(**base)


def test_inline_text_is_returned_verbatim(tmp_path):
    assert read_prompt_source(_cfg(tmp_path)) == "write a haiku"


def test_metacharacters_survive_untouched(tmp_path):
    text = "a & b | c < d > e ( f ) %PATH% !x!"
    assert read_prompt_source(_cfg(tmp_path, prompt_text=text)) == text


def test_utf8_file_is_read(tmp_path):
    p = tmp_path / "t.md"
    p.write_text("שלום עולם\n", encoding="utf-8")
    got = read_prompt_source(_cfg(tmp_path, prompt_text=None, prompt_file=p))
    assert "שלום עולם" in got


def test_utf8_bom_file_is_read_without_the_bom(tmp_path):
    p = tmp_path / "t.md"
    p.write_bytes("﻿hello\n".encode("utf-8"))
    got = read_prompt_source(_cfg(tmp_path, prompt_text=None, prompt_file=p))
    assert got.startswith("hello")


def test_utf16_file_is_decoded_not_mangled(tmp_path):
    """The .bat could only warn about UTF-16; Python decodes it properly."""
    p = tmp_path / "t.md"
    p.write_bytes("שלום\n".encode("utf-16"))
    got = read_prompt_source(_cfg(tmp_path, prompt_text=None, prompt_file=p))
    assert "שלום" in got


def test_undecodable_file_is_a_clear_usage_error(tmp_path):
    p = tmp_path / "t.md"
    p.write_bytes(b"\xff\xfe\xfe\xff\x00\x81\x8d")  # not valid UTF-8 or UTF-16
    with pytest.raises(LmiError) as exc:
        read_prompt_source(_cfg(tmp_path, prompt_text=None, prompt_file=p))
    assert exc.value.code == 2
    assert "t.md" in str(exc.value)


def test_composed_prompt_has_every_section(tmp_path):
    state = tmp_path / "s.md"
    body = "TASK_STATUS: IN_PROGRESS\n\n## Goal\n\nsomething\n"
    out = compose(_cfg(tmp_path), state, "2 of 5", "2026-08-03 10:15:00", body)
    assert out.startswith("# Unattended automated run")
    assert "lmi schedule" in out
    assert "run-claude.bat" not in out
    assert "Iteration: 2 of 5" in out
    assert "Started: 2026-08-03 10:15:00" in out
    assert "State file: " + str(state) in out
    assert "## State protocol - read this first" in out
    assert "## CURRENT STATE - " + str(state) in out
    assert "something" in out            # the state body is inlined
    assert "## TASK" in out
    assert out.rstrip().endswith("write a haiku")


def test_task_section_comes_after_current_state(tmp_path):
    out = compose(_cfg(tmp_path), tmp_path / "s.md", "1 of 1", "now", "body")
    assert out.index("## CURRENT STATE") < out.index("## TASK")
