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


def test_the_running_version_is_read_from_the_package():
    """RUNNING is lmi.__version__ at import, which is the FROM side of the
    upgrade and the one thing this process can honestly report."""
    assert runner.RUNNING == lmi.__version__
