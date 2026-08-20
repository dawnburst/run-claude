"""The once-a-day "a newer lmi exists" line, on every command's startup path.

Two properties matter more than the message: it never fails a command, and it
says nothing whenever it is not certain. Most of this module is the second one -
one test per way of being unsure - because a notice that cries wolf teaches an
operator to ignore it, and then the real one, months later, is ignored too.
"""

import json

import pytest

from lmi.commands.upgrade import notice
from lmi.core.errors import LmiError

from ...conftest import _REAL_MAYBE_SAY

REPO = "https://github.com/dawnburst/run-claude.git"


@pytest.fixture(autouse=True)
def _real_notice(monkeypatch):
    """Undo the suite-wide guard for this module only.

    tests/conftest.py neuters `maybe_say` for every other test, because it runs
    on the startup path of every command and would otherwise reach a real config
    file and a real git remote. This is the module that tests it, so it gets the
    real one back - the same trade the schedule conftest makes for
    `backend.resolve`.
    """
    monkeypatch.setattr(notice, "maybe_say", _REAL_MAYBE_SAY)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway HOME, so no test touches the developer's own ~/.lmi."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    return h


@pytest.fixture
def configured(home, monkeypatch):
    """A discoverable config file naming a repo, and a known running version."""
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    folder = home / ".lmi"
    folder.mkdir()
    path = folder / "config.json"
    path.write_text(json.dumps({"lmi": {"repo": REPO}}), encoding="utf-8")
    monkeypatch.setattr(notice, "RUNNING", "0.2.1")
    return path


def _said(capsys):
    return capsys.readouterr().out


# --- the one case that speaks ---------------------------------------------

def test_a_newer_tag_is_reported_once(configured, fake_git, capsys):
    fake_git.tags(["v0.2.0", "v0.3.0"])

    notice.maybe_say("schedule")

    out = _said(capsys)
    assert "0.3.0" in out
    assert "0.2.1" in out
    assert "lmi upgrade" in out


def test_the_answer_is_cached_so_the_next_command_runs_no_git(configured,
                                                              fake_git, capsys):
    """MANDATORY - item 62. This is the only network call on `lmi schedule`'s
    startup path; paying it on every invocation is what the cache exists to
    prevent."""
    fake_git.tags(["v0.3.0"])
    notice.maybe_say("schedule")
    assert fake_git.count() == 1

    notice.maybe_say("schedule")

    assert fake_git.count() == 1, "the second command consulted the remote again"
    assert "0.3.0" in _said(capsys)          # and still says so, from the cache


def test_a_stale_cache_is_refreshed(configured, fake_git, capsys):
    fake_git.tags(["v0.3.0"])
    notice.maybe_say("schedule")
    cache = notice.cache_path()
    doc = json.loads(cache.read_text())
    doc["checked"] = "2000-01-01T00:00:00"
    cache.write_text(json.dumps(doc), encoding="utf-8")

    notice.maybe_say("schedule")

    assert fake_git.count() == 2


def test_a_cache_from_a_different_repo_is_not_reused(configured, fake_git,
                                                     capsys):
    """Keyed by URL, so re-pointing `lmi.repo` cannot report the old remote's
    tags as if they were the new one's."""
    fake_git.tags(["v0.3.0"])
    notice.maybe_say("schedule")
    cache = notice.cache_path()
    doc = json.loads(cache.read_text())
    doc["repo"] = "https://elsewhere.invalid/lmi.git"
    cache.write_text(json.dumps(doc), encoding="utf-8")

    notice.maybe_say("schedule")

    assert fake_git.count() == 2


# --- every way of being unsure is silence ---------------------------------

def test_nothing_when_the_tag_is_not_newer(configured, fake_git, capsys):
    fake_git.tags(["v0.2.1", "v0.1.0"])
    notice.maybe_say("schedule")
    assert _said(capsys) == ""


def test_nothing_when_the_newest_tag_is_older(configured, fake_git, monkeypatch,
                                              capsys):
    """MANDATORY - item 61's tuple comparison, reaching the notice: a machine on
    0.10.0 must not be told that 0.9.0 is newer."""
    monkeypatch.setattr(notice, "RUNNING", "0.10.0")
    fake_git.tags(["v0.9.0"])
    notice.maybe_say("schedule")
    assert _said(capsys) == ""


def test_nothing_when_there_is_no_config_file(home, fake_git, monkeypatch,
                                              capsys):
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    notice.maybe_say("schedule")
    assert _said(capsys) == ""
    assert fake_git.count() == 0


def test_nothing_when_the_config_names_no_repo(home, fake_git, monkeypatch,
                                               capsys):
    """The commonest case, and the one that makes this feature inert until a
    site opts in: every machine configured before it existed has no repo key."""
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    folder = home / ".lmi"
    folder.mkdir()
    (folder / "config.json").write_text(
        json.dumps({"lmi": {"index": "https://i/simple/"}}), encoding="utf-8"
    )
    notice.maybe_say("schedule")
    assert _said(capsys) == ""
    assert fake_git.count() == 0


def test_nothing_when_the_check_is_switched_off(home, fake_git, monkeypatch,
                                               capsys):
    """MANDATORY - what an air-gapped site sets, whose git host is unreachable
    by design. It must cost nothing, not merely print nothing."""
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    folder = home / ".lmi"
    folder.mkdir()
    (folder / "config.json").write_text(
        json.dumps({"lmi": {"repo": REPO, "version_check": False}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(notice, "RUNNING", "0.2.1")

    notice.maybe_say("schedule")

    assert _said(capsys) == ""
    assert fake_git.count() == 0


def test_nothing_when_git_fails(configured, fake_git, capsys):
    fake_git.rc(128)
    notice.maybe_say("schedule")
    assert _said(capsys) == ""


def test_nothing_when_git_is_absent(configured, tmp_path, monkeypatch, capsys):
    empty = tmp_path / "nogit"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    notice.maybe_say("schedule")
    assert _said(capsys) == ""


def test_nothing_when_the_remote_has_no_version_tags(configured, fake_git,
                                                     capsys):
    fake_git.tags(["nightly", "release_final"])
    notice.maybe_say("schedule")
    assert _said(capsys) == ""


def test_nothing_when_the_running_version_cannot_be_parsed(configured, fake_git,
                                                           monkeypatch, capsys):
    monkeypatch.setattr(notice, "RUNNING", "0.3.0.dev0+local")
    fake_git.tags(["v0.9.0"])
    notice.maybe_say("schedule")
    assert _said(capsys) == ""


def test_nothing_for_the_upgrade_command_itself(configured, fake_git, capsys):
    """That command is about to say the same thing with more detail, and having
    asked for it is not a reason to be told."""
    fake_git.tags(["v0.3.0"])
    notice.maybe_say("upgrade")
    assert _said(capsys) == ""
    assert fake_git.count() == 0


def test_a_broken_config_file_is_silence_not_an_error(home, fake_git,
                                                      monkeypatch, capsys):
    """MANDATORY - item 62. `lmi upgrade` refuses an unparseable config, loudly
    and by design. A DIAGNOSTIC on the startup path of every other command must
    not, or one bad config file makes the whole CLI unusable."""
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    folder = home / ".lmi"
    folder.mkdir()
    (folder / "config.json").write_text("{not json", encoding="utf-8")

    notice.maybe_say("schedule")

    assert _said(capsys) == ""


def test_a_broken_cache_file_is_a_miss_not_an_error(configured, fake_git,
                                                    capsys):
    notice.cache_path().parent.mkdir(parents=True, exist_ok=True)
    notice.cache_path().write_text("{not json", encoding="utf-8")
    fake_git.tags(["v0.3.0"])

    notice.maybe_say("schedule")

    assert "0.3.0" in _said(capsys)
    assert fake_git.count() == 1


def test_an_unwritable_cache_is_silent(configured, fake_git, monkeypatch,
                                       capsys):
    from lmi.core import jsonfile

    def _boom(*a, **k):
        raise LmiError("read-only file system", 3)

    monkeypatch.setattr(jsonfile, "write", _boom)
    fake_git.tags(["v0.3.0"])

    notice.maybe_say("schedule")

    assert "0.3.0" in _said(capsys)          # the notice still happens


def test_an_exception_anywhere_inside_is_swallowed(configured, monkeypatch,
                                                  capsys):
    """MANDATORY - item 62, stated as bluntly as it can be: this must never be
    able to fail a command. Not the config read, not the lookup, not the cache."""
    from lmi.commands.upgrade import repo as repo_module

    def _explode(*a, **k):
        raise RuntimeError("something nobody predicted")

    monkeypatch.setattr(repo_module, "newest_tag", _explode)

    notice.maybe_say("schedule")            # must not raise

    assert _said(capsys) == ""


def test_a_hanging_remote_does_not_hold_up_the_command(configured, fake_git,
                                                       capsys):
    """MANDATORY - item 62's other half. An unreachable git host must not delay
    an unattended run's first iteration."""
    import time
    fake_git.hang(30)
    monkeypatch_timeout = 1
    started = time.time()

    notice.maybe_say("schedule", timeout=monkeypatch_timeout)

    assert time.time() - started < 10
    assert _said(capsys) == ""
