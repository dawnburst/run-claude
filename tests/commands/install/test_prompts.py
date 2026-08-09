"""Every question the command asks, and the guard against hanging."""

import builtins

import pytest

from lmi.commands.install import prompts
from lmi.core import prompts as core_prompts
from lmi.core.errors import LmiError


def feed(monkeypatch, *answers):
    """Queue answers for input(); raise if more are asked for than queued."""
    queue = list(answers)
    asked = []

    def fake_input(prompt=""):
        asked.append(prompt)
        if not queue:
            raise AssertionError("asked more questions than were answered")
        return queue.pop(0)

    monkeypatch.setattr(builtins, "input", fake_input)
    return asked


@pytest.mark.parametrize("answer,expected", [
    ("y", True), ("Y", True), ("yes", True), ("YES", True), (" y ", True),
    ("n", False), ("no", False), ("", False), ("maybe", False), ("yy", False),
])
def test_confirm_defaults_to_no(monkeypatch, answer, expected):
    feed(monkeypatch, answer)
    assert prompts.confirm("Repair?") is expected


def test_confirm_blank_takes_the_stated_default(monkeypatch):
    feed(monkeypatch, "")
    assert prompts.confirm("Repair?", default=True) is True


def test_confirm_shows_which_default_applies(monkeypatch):
    asked = feed(monkeypatch, "")
    prompts.confirm("Repair?")
    assert "[y/N]" in asked[0]
    asked = feed(monkeypatch, "")
    prompts.confirm("Repair?", default=True)
    assert "[Y/n]" in asked[0]


def test_text_returns_the_answer_stripped(monkeypatch):
    feed(monkeypatch, "  C:\\Git\\bin\\bash.exe  ")
    assert prompts.text("Path") == "C:\\Git\\bin\\bash.exe"


def test_text_blank_takes_the_default(monkeypatch):
    feed(monkeypatch, "")
    assert prompts.text("Path", default="/usr/bin/bash") == "/usr/bin/bash"


def test_text_blank_with_no_default_is_empty(monkeypatch):
    feed(monkeypatch, "")
    assert prompts.text("Path") == ""


def test_secret_uses_getpass_not_input(monkeypatch):
    """MANDATORY. A token echoed to the terminal lands in scrollback.

    If secret() ever falls back to input(), the credential is displayed, and on
    a shared or recorded session that is a disclosure. The fixture makes input()
    raise so the fallback cannot pass unnoticed.
    """
    def explode(prompt=""):
        raise AssertionError("secret() must not use input()")

    monkeypatch.setattr(builtins, "input", explode)
    monkeypatch.setattr(core_prompts.getpass, "getpass", lambda prompt="": " tok ")
    assert prompts.secret("Token") == "tok"


@pytest.mark.parametrize("ask", [
    lambda: prompts.confirm("q"),
    lambda: prompts.text("q"),
])
def test_eof_is_a_usage_error_not_a_hang(monkeypatch, ask):
    """MANDATORY. Without this the command blocks forever in a script.

    There is no --yes flag by design, so a run with no terminal cannot answer.
    It must fail fast and say why, not wait on a stdin that will never deliver.
    """
    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr(builtins, "input", eof)
    with pytest.raises(LmiError) as exc:
        ask()
    assert exc.value.code == 2
    assert "terminal" in str(exc.value)


def test_eof_from_getpass_is_also_a_usage_error(monkeypatch):
    def eof(prompt=""):
        raise EOFError

    # The module object is shared, so patching it here is what core.prompts
    # sees. Named through core.prompts now that the call lives there.
    monkeypatch.setattr(core_prompts.getpass, "getpass", eof)
    with pytest.raises(LmiError) as exc:
        prompts.secret("Token")
    assert exc.value.code == 2


def test_ctrl_c_is_a_clean_message_not_a_traceback(monkeypatch):
    def interrupt(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr(builtins, "input", interrupt)
    with pytest.raises(LmiError) as exc:
        prompts.confirm("q")
    assert exc.value.code == 2
