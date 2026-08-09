"""Confirming an upgrade by running the installed command."""

import pytest

from lmi.commands.upgrade import verify
from lmi.core.errors import LmiError


def test_the_installed_version_is_returned(fake_pip, monkeypatch):
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.2.0")
    assert verify.confirm(fake_pip.script, "0.2.0") == "0.2.0"


def test_an_old_version_after_a_successful_pip_is_exit_3(fake_pip, monkeypatch):
    """MANDATORY. This is the stale-wheel failure reached through a new door.

    pip exits 0, the command runs, and the code is the old code. Anything that
    reported success here - reading lmi.__version__ out of this process, for
    instance, which is the version imported BEFORE pip ran - would announce an
    upgrade that did not happen and leave nothing on screen to suggest
    otherwise.
    """
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.1.0")
    with pytest.raises(LmiError) as exc:
        verify.confirm(fake_pip.script, "0.2.0")
    assert exc.value.code == 3
    assert "0.2.0" in str(exc.value)
    assert "0.1.0" in str(exc.value)


def test_no_expectation_still_requires_it_to_run(fake_pip, monkeypatch):
    """When the probe could not say what to expect, verification is weaker -
    it still catches a broken install, just not a stale one."""
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.7.0")
    assert verify.confirm(fake_pip.script, None) == "0.7.0"


def test_a_command_that_fails_to_run_is_exit_3(fake_pip, monkeypatch):
    monkeypatch.setenv("FAKE_SCRIPT_RC", "9")
    with pytest.raises(LmiError) as exc:
        verify.confirm(fake_pip.script, None)
    assert exc.value.code == 3
    assert str(fake_pip.script) in str(exc.value)


def test_a_missing_command_is_exit_3(tmp_path):
    with pytest.raises(LmiError) as exc:
        verify.confirm(tmp_path / "nothing-here", None)
    assert exc.value.code == 3


def test_a_stderr_warning_before_the_version_line_still_succeeds(fake_pip, monkeypatch):
    """MANDATORY. This is the false exit-3 the whole-branch review found.

    stdout and stderr used to be merged with stderr=subprocess.STDOUT, and only
    line 0 of the result was checked. Any byte the new interpreter writes to
    stderr before argparse's version action fires - a DeprecationWarning, a
    .pth file's own output, a locale complaint - became line 0, the match
    failed, and a SUCCESSFUL upgrade raised UNREADABLE at exit 3. stderr must be
    captured separately, and every stdout line must be a candidate.
    """
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.2.0")
    monkeypatch.setenv("FAKE_SCRIPT_STDERR",
                       "DeprecationWarning: something noisy on stderr")
    assert verify.confirm(fake_pip.script, "0.2.0") == "0.2.0"


def test_a_version_line_followed_by_a_nonzero_exit_is_still_exit_3(fake_pip,
                                                                    monkeypatch):
    """The returncode check must keep winning even once every stdout line is a
    candidate: printing a correct-looking version line does not excuse a
    process that then reports failure."""
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.2.0")
    monkeypatch.setenv("FAKE_SCRIPT_RC", "1")
    with pytest.raises(LmiError) as exc:
        verify.confirm(fake_pip.script, "0.2.0")
    assert exc.value.code == 3


def test_a_bom_before_the_version_line_is_handled(fake_pip, monkeypatch):
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.2.0")
    monkeypatch.setenv("FAKE_SCRIPT_BOM", "1")
    assert verify.confirm(fake_pip.script, "0.2.0") == "0.2.0"


def test_unusual_whitespace_before_the_version_line_is_handled(fake_pip,
                                                                monkeypatch):
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.2.0")
    monkeypatch.setenv("FAKE_SCRIPT_PREFIX", "  \t")
    assert verify.confirm(fake_pip.script, "0.2.0") == "0.2.0"


def test_unreadable_output_is_exit_3(fake_pip, monkeypatch, tmp_path):
    odd = tmp_path / "odd"
    odd.write_text("#!%s\nprint('something else')\n" % __import__("sys").executable)
    odd.chmod(0o755)
    with pytest.raises(LmiError) as exc:
        verify.confirm(odd, None)
    assert exc.value.code == 3
