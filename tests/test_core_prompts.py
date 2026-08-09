"""The shared prompt guard.

The behaviour of each question type is pinned by
tests/commands/install/test_prompts.py and must keep passing through the
delegating wrapper. What is new here is that the no-terminal message is the
caller's, so `lmi upgrade` does not tell the user about an auth token it never
asks for.
"""

import builtins

import pytest

from lmi.core import prompts
from lmi.core.errors import LmiError

MINE = "lmi widget is interactive and needs a terminal."


def eof(prompt=""):
    raise EOFError


def test_the_no_terminal_message_is_the_callers(monkeypatch):
    monkeypatch.setattr(builtins, "input", eof)
    with pytest.raises(LmiError) as exc:
        prompts.confirm("q?", no_terminal=MINE)
    assert exc.value.code == 2
    assert str(exc.value) == MINE


def test_secret_carries_the_callers_message_too(monkeypatch):
    monkeypatch.setattr(prompts.getpass, "getpass", eof)
    with pytest.raises(LmiError) as exc:
        prompts.secret("Token", no_terminal=MINE)
    assert str(exc.value) == MINE


def test_the_default_message_still_says_terminal(monkeypatch):
    """A caller that passes nothing must still fail fast, not hang."""
    monkeypatch.setattr(builtins, "input", eof)
    with pytest.raises(LmiError) as exc:
        prompts.confirm("q?")
    assert exc.value.code == 2
    assert "terminal" in str(exc.value)


def test_ctrl_c_is_cancelled_whatever_the_caller_said(monkeypatch):
    def interrupt(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr(builtins, "input", interrupt)
    with pytest.raises(LmiError) as exc:
        prompts.confirm("q?", no_terminal=MINE)
    assert exc.value.code == 2
    assert str(exc.value) == prompts.CANCELLED
