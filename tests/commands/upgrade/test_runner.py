"""The `lmi upgrade` flow.

Every test drives the real runner with a fake pip and a fake installed
command. The `answers` fixture is a scripted queue behind prompts.confirm, so
no test reaches a real stdin.
"""

import json

import pytest

import lmi
from lmi.commands.upgrade import installation, prompts, runner
from lmi.core.errors import LmiError


class Args:
    def __init__(self, config=None, version=None):
        self.config = config
        self.version = version


@pytest.fixture
def answers(monkeypatch):
    """A scripted queue of yes/no answers behind prompts.confirm."""
    queue = []

    def confirm(question, default=False):
        assert queue, "the runner asked more questions than the test scripted"
        return queue.pop(0)

    monkeypatch.setattr(prompts, "confirm", confirm)
    return queue


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "lmi.json"
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"lmi": {"index": "https://i/simple/"}}, fh)
    return path


@pytest.fixture
def wired(fake_pip, monkeypatch, config_file):
    """The runner, with detection and the running version under our control."""
    monkeypatch.setattr(installation, "detect", fake_pip.installation)
    monkeypatch.setattr(runner, "RUNNING", "0.1.0")
    return fake_pip


def test_a_newer_version_is_installed_and_confirmed(wired, answers, monkeypatch,
                                                    config_file, capsys):
    monkeypatch.setenv("FAKE_PIP_LATEST", "0.2.0")
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.2.0")
    answers.append(True)

    assert runner.run(Args(config=str(config_file))) == 0
    installs = [c for c in wired.calls() if "install" in c]
    assert len(installs) == 1
    assert installs[0][-1] == "lmi==0.2.0"
    assert "0.2.0" in capsys.readouterr().out


def test_answering_no_runs_no_pip_and_changes_nothing(wired, answers, monkeypatch,
                                                      config_file, capsys):
    """MANDATORY. The same guarantee as CLAUDE.md section 3 item 16: a user who
    answers the question rather than erring leaves the machine as they found
    it, and the command exits 0 because they answered."""
    monkeypatch.setenv("FAKE_PIP_LATEST", "0.2.0")
    answers.append(False)

    assert runner.run(Args(config=str(config_file))) == 0
    assert [c for c in wired.calls() if "install" in c] == []
    assert "Nothing was changed." in capsys.readouterr().out


def test_already_at_the_newest_makes_no_pip_install(wired, answers, monkeypatch,
                                                    config_file, capsys):
    monkeypatch.setenv("FAKE_PIP_LATEST", "0.1.0")

    assert runner.run(Args(config=str(config_file))) == 0
    assert [c for c in wired.calls() if "install" in c] == []
    assert "already" in capsys.readouterr().out.lower()


def test_an_explicit_version_equal_to_the_running_one_asks_the_index_nothing(
        wired, answers, config_file):
    assert runner.run(Args(config=str(config_file), version="0.1.0")) == 0
    assert wired.count() == 0


@pytest.mark.parametrize("bad", ["", "   ", "\t"])
def test_an_empty_or_blank_version_is_exit_2_not_a_pip_call(
        wired, answers, config_file, bad):
    """An empty or whitespace-only --version would otherwise pass straight
    through to pip as `lmi==`, which pip itself rejects - surfacing as exit 1
    with a message about checking the index, when the actual mistake is a bad
    argument that belongs at exit 2, before pip is ever invoked."""
    with pytest.raises(LmiError) as exc:
        runner.run(Args(config=str(config_file), version=bad))
    assert exc.value.code == 2
    assert wired.count() == 0


def test_an_explicit_version_is_pinned(wired, answers, monkeypatch, config_file):
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.0.9")
    answers.append(True)

    assert runner.run(Args(config=str(config_file), version="0.0.9")) == 0
    installs = [c for c in wired.calls() if "install" in c]
    assert installs[0][-1] == "lmi==0.0.9"
    assert not [c for c in wired.calls() if "index" in c]  # no probe needed


def test_a_probe_that_cannot_answer_still_upgrades(wired, answers, monkeypatch,
                                                   config_file, capsys):
    monkeypatch.delenv("FAKE_PIP_LATEST", raising=False)
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.5.0")
    answers.append(True)

    assert runner.run(Args(config=str(config_file))) == 0
    installs = [c for c in wired.calls() if "install" in c]
    assert installs[0][-2:] == ["--upgrade", "lmi"]
    assert "0.5.0" in capsys.readouterr().out


def test_probe_unavailable_and_already_current_does_not_claim_an_upgrade(
        wired, answers, monkeypatch, config_file, capsys):
    """MANDATORY. Pins the exact silent failure CLAUDE.md section 3 exists for.

    On a pip too old for `pip index versions` (stock pip on Debian 11 / RHEL
    8), the probe answers None, the target is None, `pip install --upgrade
    lmi` finds nothing newer and exits 0 having changed nothing, and
    verify.confirm(script, None) skips the equality check and returns
    whatever RUNNING already was. Without a branch on that result, the runner
    used to print "Upgraded lmi 0.1.0 -> 0.1.0" and exit 0 on every single
    already-current invocation at a site whose pip lacks the subcommand. The
    output must say nothing changed, not claim an upgrade.
    """
    monkeypatch.delenv("FAKE_PIP_LATEST", raising=False)
    # FAKE_SCRIPT_VERSION deliberately left unset, so the "installed" script
    # keeps reporting RUNNING ("0.1.0") - pip changed nothing.
    answers.append(True)

    assert runner.run(Args(config=str(config_file))) == 0
    out = capsys.readouterr().out
    assert "Upgraded" not in out
    assert "0.1.0" in out


def test_a_stale_result_is_exit_3(wired, answers, monkeypatch, config_file):
    monkeypatch.setenv("FAKE_PIP_LATEST", "0.2.0")
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.1.0")   # pip lied
    answers.append(True)

    with pytest.raises(LmiError) as exc:
        runner.run(Args(config=str(config_file)))
    assert exc.value.code == 3


def test_a_failing_pip_is_exit_1(wired, answers, monkeypatch, config_file):
    monkeypatch.setenv("FAKE_PIP_LATEST", "0.2.0")
    monkeypatch.setenv("FAKE_PIP_RC", "1")
    answers.append(True)

    with pytest.raises(LmiError) as exc:
        runner.run(Args(config=str(config_file)))
    assert exc.value.code == 1


def test_a_refused_installation_never_reaches_pip(fake_pip, monkeypatch,
                                                  config_file):
    def refuse():
        raise LmiError("nope", 2)

    monkeypatch.setattr(installation, "detect", refuse)
    with pytest.raises(LmiError) as exc:
        runner.run(Args(config=str(config_file)))
    assert exc.value.code == 2
    assert fake_pip.count() == 0


def test_an_unexpected_exception_is_exit_4(wired, answers, monkeypatch,
                                           config_file):
    def boom():
        raise ZeroDivisionError("x")

    monkeypatch.setattr(installation, "detect", boom)
    with pytest.raises(LmiError) as exc:
        runner.run(Args(config=str(config_file)))
    assert exc.value.code == 4
    assert "ZeroDivisionError" in str(exc.value)


def test_shadowed_warns_when_another_lmi_is_earlier_on_path(
        wired, answers, monkeypatch, config_file, capsys, tmp_path):
    """The last backstop for "the upgrade was real and invisible": another lmi
    earlier on PATH means the user's next `lmi --version` still shows the old
    one. SHADOWED has a %s count a refactor could break silently - this pins
    both the warning firing and the two paths it names."""
    monkeypatch.setenv("FAKE_PIP_LATEST", "0.2.0")
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.2.0")
    other = tmp_path / "shadow-lmi"
    other.write_text("", encoding="utf-8")
    monkeypatch.setattr(runner.shutil, "which", lambda name: str(other))
    answers.append(True)

    assert runner.run(Args(config=str(config_file))) == 0
    out = capsys.readouterr().out
    assert "WARN" in out
    assert str(other) in out
    assert str(wired.script) in out


def test_no_warning_when_which_resolves_to_the_upgraded_script(
        wired, answers, monkeypatch, config_file, capsys):
    monkeypatch.setenv("FAKE_PIP_LATEST", "0.2.0")
    monkeypatch.setenv("FAKE_SCRIPT_VERSION", "0.2.0")
    monkeypatch.setattr(runner.shutil, "which", lambda name: str(wired.script))
    answers.append(True)

    assert runner.run(Args(config=str(config_file))) == 0
    assert "WARN" not in capsys.readouterr().out


def test_the_running_version_is_read_from_the_package():
    """RUNNING is lmi.__version__ at import, which is the FROM side of the
    upgrade and the one thing this process can honestly report."""
    assert runner.RUNNING == lmi.__version__
