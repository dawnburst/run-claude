"""End to end: fragment in, settings.json out, snapshot in between."""

import json
import os
import stat

import pytest

from lmi.commands.config import origin, runner
from lmi.core.errors import LmiError
from tests.conftest import skip_as_root


class Args:
    def __init__(self, target=None, file=None, config_command="switch",
                 config=None):
        self.target = target
        self.file = file
        self.config = config
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
    """MANDATORY. Silent failure: a config mutation that reports success.

    The message matters, not just the code: the fall-through also yields 2.

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
    """The whole line, not just the path: the snapshot line contains it too.

    "Saved your current settings as the restore point: .../settings.json
    .lmi-origin" has the settings.json path as a substring, so a bare `str(
    settings(home)) in out` passes with the "Wrote %s" line deleted outright.
    """
    put(settings(home), {"model": "sonnet"})
    runner.run(Args(file=str(frag(tmp_path, {"model": "opus"}))))
    out = capsys.readouterr().out
    assert "model" in out
    assert "Wrote %s" % settings(home) in out


# --- named switch files, from anywhere ------------------------------------
#
# The convention: settings_switch_<name>.json beside the lmi.json discovery
# resolves, exactly where `lmi install claude` looks for its settings.json.
# What makes a switch work from any directory is that the folder is discovered
# rather than being "./config" of wherever the operator is standing.

@pytest.fixture
def config_folder(tmp_path, monkeypatch):
    """A discoverable config folder, and the cwd somewhere else entirely."""
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    folder = tmp_path / "site"
    put(folder / "lmi.json", {})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("LMI_CONFIG", str(folder / "lmi.json"))
    return folder


def switch_file(folder, name, doc):
    return put(folder / ("settings_switch_%s.json" % name), doc)


def test_a_named_switch_is_applied_from_the_config_folder(
        home, config_folder):
    """The point of the feature: this runs from a directory with nothing in it."""
    put(settings(home), {"model": "sonnet", "theme": "dark"})
    switch_file(config_folder, "opus", {"model": "opus"})

    assert runner.run(Args(target="opus")) == 0
    assert read(home) == {"model": "opus", "theme": "dark"}


def test_each_name_selects_its_own_file(home, config_folder):
    put(settings(home), {"model": "sonnet"})
    switch_file(config_folder, "opus", {"model": "opus"})
    switch_file(config_folder, "haiku", {"model": "haiku"})

    assert runner.run(Args(target="haiku")) == 0
    assert read(home)["model"] == "haiku"


def test_a_bare_switch_lists_the_names(home, config_folder, capsys):
    switch_file(config_folder, "opus", {"model": "opus"})
    switch_file(config_folder, "gateway", {"env": {"ANTHROPIC_BASE_URL": "https://g/"}})

    assert runner.run(Args()) == 0
    out = capsys.readouterr().out
    assert "gateway" in out and "opus" in out
    assert str(config_folder) in out
    assert not settings(home).exists(), "listing must write nothing"


def test_an_unknown_name_names_the_ones_that_exist(home, config_folder):
    """MANDATORY-adjacent: "I mistyped it" and "it is in another folder" look
    identical without the list, and the second is the likelier of the two once
    --config and $LMI_CONFIG can move the folder."""
    switch_file(config_folder, "opus", {"model": "opus"})

    with pytest.raises(LmiError) as exc:
        runner.run(Args(target="typo"))
    assert exc.value.code == 2
    message = str(exc.value)
    assert "typo" in message
    assert "opus" in message
    assert str(config_folder) in message
    assert not settings(home).exists()


def test_a_folder_with_no_switch_files_is_a_usage_error(home, config_folder):
    """Not exit 0. A bare switch that lists nothing has done nothing, and
    saying so at exit 0 is the "reports success, changed nothing" shape."""
    with pytest.raises(LmiError) as exc:
        runner.run(Args())
    assert exc.value.code == 2
    assert "settings_switch_" in str(exc.value)


def test_a_file_named_for_the_restore_keyword_is_reported(
        home, config_folder, capsys):
    """MANDATORY. It exists, it can never be selected, and it looks fine.

    `origin` restores, so settings_switch_origin.json is unreachable however it
    is asked for. Silent without the warning: the operator writes the file,
    sees it in the folder beside the ones that work, runs
    `lmi config switch origin`, and gets a restore reported as a success while
    the fragment they wrote has never once been applied.
    """
    switch_file(config_folder, "origin", {"model": "opus"})
    switch_file(config_folder, "gateway", {"model": "haiku"})

    assert runner.run(Args()) == 0
    out = capsys.readouterr().out
    assert "[WARN]" in out
    assert "settings_switch_origin.json" in out
    assert "gateway" in out
    # After the list, not before it: the warning names a file that is NOT in
    # the list, and reading it first sends the operator looking for the name
    # among the ones that follow.
    assert out.index("gateway") < out.index("[WARN]")


def test_origin_still_restores_rather_than_selecting_a_file(
        home, config_folder, tmp_path):
    """MANDATORY. The keyword keeps its meaning now that names share the slot."""
    put(settings(home), {"model": "sonnet"})
    runner.run(Args(file=str(frag(tmp_path, {"model": "opus"}))))
    switch_file(config_folder, "origin", {"model": "haiku"})

    assert runner.run(Args(target="origin")) == 0
    assert read(home) == {"model": "sonnet"}, "restored, not switched"


def test_a_name_and_a_file_together_are_refused(home, config_folder, tmp_path):
    """Two sources for one merge. Picking one silently is how the wrong
    configuration lands while the command reports the other."""
    switch_file(config_folder, "opus", {"model": "opus"})
    f = frag(tmp_path, {"model": "haiku"})

    with pytest.raises(LmiError) as exc:
        runner.run(Args(target="opus", file=str(f)))
    assert exc.value.code == 2
    assert not settings(home).exists()


def test_a_name_that_is_a_path_is_refused(home, config_folder, tmp_path):
    """MANDATORY. See catalog._validate - the argument is a name, not a path."""
    outside = frag(tmp_path, {"model": "haiku"}, name="outside.json")
    with pytest.raises(LmiError) as exc:
        runner.run(Args(target="../" + outside.name))
    assert exc.value.code == 2
    assert not settings(home).exists()


def test_the_unnamed_default_still_applies_from_the_working_directory(
        home, tmp_path, monkeypatch):
    """The old shape keeps working: a bare switch with ./config/settings_switch
    .json present applies it, exactly as it did before names existed."""
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    put(settings(home), {"model": "sonnet"})
    put(tmp_path / "config" / "settings_switch.json", {"model": "opus"})

    assert runner.run(Args()) == 0
    assert read(home)["model"] == "opus"


def test_an_explicit_config_moves_the_folder(home, config_folder, tmp_path):
    other = tmp_path / "other"
    put(other / "lmi.json", {})
    switch_file(config_folder, "opus", {"model": "opus"})
    switch_file(other, "opus", {"model": "haiku"})
    put(settings(home), {})

    assert runner.run(Args(target="opus",
                           config=str(other / "lmi.json"))) == 0
    assert read(home)["model"] == "haiku"


def test_a_name_never_takes_the_restore_path(home, config_folder, tmp_path):
    """MANDATORY. Silent failure: a name read as the restore keyword.

    Inherited from test_args.test_a_path_is_rejected_as_the_target, whose
    mechanism - choices=["origin"] on the positional - named switch files had
    to remove. The failure it guarded is unchanged and is worse than a wrong
    fragment: restoring throws away every switch since the first one and
    consumes the snapshot, so `lmi config switch gateway` silently undoing the
    machine's configuration is not recoverable by running it again.

    Only the exact keyword may restore. A name must apply its own file and
    leave the snapshot untouched.
    """
    put(settings(home), {"model": "sonnet"})
    runner.run(Args(file=str(frag(tmp_path, {"model": "opus"}))))
    snapshot_before = origin.path().read_bytes()
    switch_file(config_folder, "gateway", {"model": "haiku"})

    assert runner.run(Args(target="gateway")) == 0
    assert read(home)["model"] == "haiku", "applied, not restored"
    assert origin.path().read_bytes() == snapshot_before, "snapshot untouched"
