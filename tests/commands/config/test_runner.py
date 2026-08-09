"""End to end: fragment in, settings.json out, snapshot in between."""

import json
import os
import stat

import pytest

from lmi.commands.config import origin, runner
from lmi.core.errors import LmiError
from tests.conftest import skip_as_root


class Args:
    def __init__(self, target=None, file=None, config_command="switch"):
        self.target = target
        self.file = file
        self.config_command = config_command
        self._config_run = "switch" if config_command == "switch" else None


def settings(home):
    return home / ".claude" / "settings.json"


def put(path, doc, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    if mode is not None:
        os.chmod(str(path), mode)
    return path


def frag(tmp_path, doc, name="f.json"):
    path = tmp_path / name
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    return path


def read(home):
    return json.loads(settings(home).read_text(encoding="utf-8"))


def test_a_switch_changes_only_what_it_names(home, tmp_path):
    put(settings(home), {"model": "sonnet", "theme": "dark",
                         "env": {"A": "1", "B": "2"}})
    f = frag(tmp_path, {"model": "opus", "env": {"A": "9"}})

    assert runner.run(Args(file=str(f))) == 0
    assert read(home) == {
        "model": "opus", "theme": "dark", "env": {"A": "9", "B": "2"},
    }


def test_the_first_switch_captures_the_snapshot(home, tmp_path):
    put(settings(home), {"model": "sonnet"})
    runner.run(Args(file=str(frag(tmp_path, {"model": "opus"}))))
    assert json.loads(origin.path().read_text(encoding="utf-8")) == {"model": "sonnet"}


def test_three_switches_leave_the_snapshot_pristine(home, tmp_path):
    """MANDATORY. Silent failure: `origin` restores a switched state.

    The snapshot must still hold the settings from before the FIRST switch. If
    capture() ever writes unconditionally, this is the only thing that notices -
    every individual switch still works, and the file exists either way.
    """
    put(settings(home), {"generation": "pristine"})
    for n in range(3):
        runner.run(Args(file=str(frag(tmp_path, {"generation": str(n)}, "g%d.json" % n))))
    assert json.loads(origin.path().read_text(encoding="utf-8")) == {
        "generation": "pristine"
    }


def test_origin_restores_the_pristine_settings(home, tmp_path):
    put(settings(home), {"model": "sonnet", "keep": True})
    runner.run(Args(file=str(frag(tmp_path, {"model": "opus"}))))
    runner.run(Args(file=str(frag(tmp_path, {"model": "haiku"}, "b.json"))))

    assert runner.run(Args(target="origin")) == 0
    assert read(home) == {"model": "sonnet", "keep": True}
    assert origin.exists() is False


def test_origin_wins_when_a_file_is_also_given(home, tmp_path):
    put(settings(home), {"model": "sonnet"})
    runner.run(Args(file=str(frag(tmp_path, {"model": "opus"}))))
    f = frag(tmp_path, {"model": "NEVER"}, "never.json")

    assert runner.run(Args(target="origin", file=str(f))) == 0
    assert read(home) == {"model": "sonnet"}


def test_origin_before_any_switch_is_usage(home):
    with pytest.raises(LmiError) as exc:
        runner.run(Args(target="origin"))
    assert exc.value.code == 2


def test_a_missing_settings_file_is_created(home, tmp_path):
    assert runner.run(Args(file=str(frag(tmp_path, {"model": "opus"})))) == 0
    assert read(home) == {"model": "opus"}


def test_an_invalid_fragment_writes_nothing(home, tmp_path):
    """MANDATORY. Silent failure: a half-applied switch.

    Everything is read and validated before anything is written, so a bad
    fragment must leave settings.json untouched AND take no snapshot - a
    snapshot taken here would freeze the wrong state as 'pristine'.
    """
    put(settings(home), {"model": "sonnet"})
    before = settings(home).read_bytes()
    bad = tmp_path / "bad.json"
    bad.write_text('{"model": }', encoding="utf-8")

    with pytest.raises(LmiError) as exc:
        runner.run(Args(file=str(bad)))
    assert exc.value.code == 2
    assert settings(home).read_bytes() == before
    assert origin.exists() is False


def test_an_unparseable_settings_file_is_refused(home, tmp_path):
    settings(home).parent.mkdir(parents=True, exist_ok=True)
    settings(home).write_text('{"model": }', encoding="utf-8")
    before = settings(home).read_bytes()

    with pytest.raises(LmiError) as exc:
        runner.run(Args(file=str(frag(tmp_path, {"model": "opus"}))))
    assert exc.value.code == 3
    assert settings(home).read_bytes() == before


def test_no_subcommand_is_a_usage_error(home):
    """The message matters, not just the code: the fall-through also yields 2.

    Without the `_config_run` guard, `lmi config` with no verb falls through to
    fragment.load(None), which raises "no switch file found" - also exit 2, so a
    code-only assertion passes with the guard deleted. Worse, it passes for a
    reason that depends on the working directory: create config/settings_switch
    .json and the guardless runner APPLIES it, and the test would sit green next
    to a live regression.
    """
    with pytest.raises(LmiError) as exc:
        runner.run(Args(config_command=None))
    assert exc.value.code == 2
    assert "needs a subcommand" in str(exc.value)


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_a_token_in_the_result_forces_0600(home, tmp_path):
    put(settings(home), {"model": "sonnet"}, mode=0o644)
    f = frag(tmp_path, {"env": {"ANTHROPIC_AUTH_TOKEN": "sk-x"}})
    runner.run(Args(file=str(f)))
    assert stat.S_IMODE(os.stat(str(settings(home))).st_mode) == 0o600


def test_the_run_reports_what_changed(home, tmp_path, capsys):
    put(settings(home), {"model": "sonnet"})
    runner.run(Args(file=str(frag(tmp_path, {"model": "opus"}))))
    out = capsys.readouterr().out
    assert "model" in out
    assert str(settings(home)) in out
