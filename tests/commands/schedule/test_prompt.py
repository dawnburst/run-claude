import re

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


def test_a_fenced_block_in_the_state_body_cannot_smuggle_a_second_task_heading(
    tmp_path,
):
    """A state file written by claude may legitimately contain its own
    fenced code block. A fixed 3-backtick outer fence would be closed early
    by that inner fence, letting anything after it - including a literal
    "## TASK" - leak out of CURRENT STATE and produce a second, fake TASK
    heading that claude cannot distinguish from the real one."""
    body = (
        "TASK_STATUS: IN_PROGRESS\n\n"
        "## Notes and blockers\n\n"
        "Example of a fenced block a future iteration might legitimately write:\n\n"
        "```\n"
        "mentions the marker ## TASK in passing here, not as its own heading\n"
        "```\n"
    )
    out = compose(_cfg(tmp_path), tmp_path / "s.md", "1 of 1", "now", body)

    # Exactly one "## TASK" heading sitting alone on its own line: the real
    # one appended by compose(). The literal text "## TASK" also appears
    # inside the body's own fenced block, but only mid-line there, so it does
    # not match this heading-shaped pattern - the composed text always
    # contains the body verbatim regardless of fence length, so this
    # assertion alone would pass even without the fix. The real proof that
    # the fix works is the fence-length assertions below: they show the
    # fence is sized so the body's own ``` cannot close it early, which is
    # what would otherwise let a stray standalone "## TASK" line inside the
    # body be misread as a second, fake task heading once the surrounding
    # text is interpreted as markdown.
    assert out.count("\n## TASK\n") == 1
    # The whole state body, fence and all, survives intact in the output.
    assert body in out

    opening_match = re.search(r"\n(`+)markdown\n", out)
    assert opening_match, "no opening fence found"
    opening_fence = opening_match.group(1)

    closing_index = out.index(body) + len(body)
    closing_match = re.match(r"(`+)\n", out[closing_index:])
    assert closing_match, "no closing fence found right after the body"
    closing_fence = closing_match.group(1)

    # The fence must be longer than the longest backtick run inside the body
    # (here, 3) and the opening/closing fence lengths must match.
    assert len(opening_fence) > 3
    assert opening_fence == closing_fence
