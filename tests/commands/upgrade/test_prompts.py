"""The one question `lmi upgrade` asks, and the guard against hanging.

Nothing else in the suite drives this module: tests/commands/upgrade/
test_runner.py's `answers` fixture patches `prompts.confirm` away entirely, so
the wrapper - and the no-terminal guard it forwards into core.prompts.confirm -
was never actually executed. This is the hang guard on the command that
replaces the binary currently running it, so it gets its own test, mirroring
tests/commands/install/test_prompts.py.
"""

import builtins

import pytest

from lmi.commands.upgrade import prompts
from lmi.core.errors import LmiError


def test_eof_is_a_usage_error_naming_lmi_upgrade(monkeypatch):
    """MANDATORY. Without this the command blocks forever with no terminal to
    answer it - the spec (section 10) lists "no terminal is exit 2 and not a
    hang" among the covered cases, and nothing pinned it for this command."""
    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr(builtins, "input", eof)
    with pytest.raises(LmiError) as exc:
        prompts.confirm("Replace lmi 0.1.0 with 0.2.0?")
    assert exc.value.code == 2
    assert "lmi upgrade" in str(exc.value)
    assert "terminal" in str(exc.value)


def test_ctrl_c_is_the_cancelled_message_not_a_traceback(monkeypatch):
    def interrupt(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr(builtins, "input", interrupt)
    with pytest.raises(LmiError) as exc:
        prompts.confirm("Replace lmi 0.1.0 with 0.2.0?")
    assert exc.value.code == 2
    assert "cancelled" in str(exc.value)
    assert "nothing was changed" in str(exc.value)


def test_confirm_defaults_to_no(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt="": "")
    assert prompts.confirm("q?") is False


def test_confirm_honours_a_yes_answer(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt="": "y")
    assert prompts.confirm("q?") is True
