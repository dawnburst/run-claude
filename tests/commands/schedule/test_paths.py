import os
from pathlib import Path

import pytest

from lmi.commands.schedule.paths import (
    has_extension, resolve_log, resolve_state, timestamp,
)
from lmi.core.errors import LmiError

TS = "20260803-101500"




def test_timestamp_shape():
    ts = timestamp()
    assert len(ts) == 15 and ts[8] == "-" and ts.replace("-", "").isdigit()


def test_default_state_path_is_beside_the_workdir(tmp_path, make_cfg):
    assert resolve_state(make_cfg(tmp_path)) == tmp_path / "run-claude-state.md"


def test_state_parent_is_created_when_missing(tmp_path, make_cfg):
    """The .bat mkdirs a missing parent and only fails if that fails."""
    target = tmp_path / "deep" / "dir" / "st.md"
    assert resolve_state(make_cfg(tmp_path, state_arg=str(target))) == target
    assert target.parent.is_dir()


def test_default_log_is_timestamped_in_the_workdir(tmp_path, make_cfg):
    assert resolve_log(make_cfg(tmp_path), TS) == tmp_path / ("run-claude-%s.log" % TS)


def test_rule_1_existing_directory_receives_a_timestamped_log(tmp_path, make_cfg):
    d = tmp_path / "logs"
    d.mkdir()
    assert resolve_log(make_cfg(tmp_path, log_arg=str(d)), TS) == d / ("run-claude-%s.log" % TS)


def test_rule_2_trailing_separator_is_a_folder_not_yet_created(tmp_path, make_cfg):
    d = tmp_path / "later"
    got = resolve_log(make_cfg(tmp_path, log_arg=str(d) + "/"), TS)
    assert got == d / ("run-claude-%s.log" % TS)
    assert d.is_dir()


def test_rule_3_a_basename_with_an_extension_is_the_log_file(tmp_path, make_cfg):
    target = tmp_path / "a" / "b" / "my.log"
    assert resolve_log(make_cfg(tmp_path, log_arg=str(target)), TS) == target
    assert target.parent.is_dir()


def test_rule_4_extensionless_nonexistent_path_is_a_folder(tmp_path, make_cfg):
    """The trap: the .bat falls through to :rl_folder here, so this must be
    a DIRECTORY containing a timestamped log, not a file named 'newlogs'."""
    d = tmp_path / "newlogs"
    got = resolve_log(make_cfg(tmp_path, log_arg=str(d)), TS)
    assert got == d / ("run-claude-%s.log" % TS)
    assert d.is_dir()


def test_dotfile_does_not_count_as_having_an_extension():
    assert has_extension(".hidden") is False
    assert has_extension("my.log") is True
    assert has_extension("plain") is False
    assert has_extension("a.b.c") is True


def test_an_over_long_log_path_is_a_usage_error_not_a_crash(tmp_path, make_cfg):
    """pathlib swallows ENOENT/ENOTDIR/EBADF/ELOOP only, so Path.is_dir() on
    a 256-byte name raises ENAMETOOLONG. That used to leave the CLI with a raw
    traceback and exit 1 - the code that means a claude call failed."""
    long_name = "a" * 300
    with pytest.raises(LmiError) as exc:
        resolve_log(make_cfg(tmp_path, log_arg=str(tmp_path / long_name)), TS)
    assert exc.value.code == 2


def test_an_over_long_state_path_is_a_usage_error_not_a_crash(tmp_path, make_cfg):
    with pytest.raises(LmiError) as exc:
        resolve_state(make_cfg(tmp_path, state_arg=str(tmp_path / ("s" * 300))))
    assert exc.value.code == 2


def test_an_unknown_user_tilde_is_a_usage_error_not_a_crash(tmp_path, make_cfg):
    """expanduser() raises RuntimeError when it cannot find that user's home,
    which reached the CLI as a traceback and exit 1. The tilde expansion
    itself stays - it is what makes a quoted -s "~/x" work."""
    for kw in ("state_arg", "log_arg"):
        with pytest.raises(LmiError) as exc:
            cfg = make_cfg(tmp_path, **{kw: "~nosuchuser42/x.log"})
            resolve_state(cfg) if kw == "state_arg" else resolve_log(cfg, TS)
        assert exc.value.code == 2


def test_a_leading_tilde_is_still_expanded(tmp_path, make_cfg):
    """Deliberate deviation from the .bat, documented in the README: a quoted
    -s "~/x" must land in the home directory, not in a folder named '~'."""
    got = resolve_state(make_cfg(tmp_path, state_arg="~/lmi-test-state.md"))
    assert str(got).startswith(str(Path.home()))
    assert "~" not in str(got)


def test_a_state_path_that_is_an_existing_directory_is_refused(tmp_path, make_cfg):
    """os.replace moves a directory happily, so `-s ~/notes` used to rename
    the whole folder to ~/notes.<ts>.bak and write a file in its place."""
    d = tmp_path / "notes"
    d.mkdir()
    (d / "keep.md").write_text("precious\n", encoding="utf-8")
    with pytest.raises(LmiError) as exc:
        resolve_state(make_cfg(tmp_path, state_arg=str(d)))
    assert exc.value.code == 2
    assert "directory" in str(exc.value)
    assert (d / "keep.md").exists()


@pytest.mark.skipif(
    getattr(os, "geteuid", lambda: 1)() == 0,
    # os.geteuid is Unix-only, and this argument is evaluated at import time:
    # a bare os.geteuid() made the whole module raise AttributeError during
    # collection on Windows, silently losing every test in it.
    reason="root ignores directory permissions",
)
def test_unwritable_log_parent_is_a_clear_error(tmp_path, make_cfg):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        with pytest.raises(LmiError) as exc:
            resolve_log(make_cfg(tmp_path, log_arg=str(ro / "sub" / "x.log")), TS)
        assert exc.value.code == 2
    finally:
        ro.chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_an_unwritable_working_directory_says_to_pass_d(tmp_path, make_cfg):
    """One clear error naming -d, not three Permission denied in a row.

    The report this comes from: on Windows, cmd.exe cannot hold a UNC working
    directory, so launching from \\\\wsl.localhost\\... left the process in
    C:\\Windows. lmi then aimed its state file, log and lock there and failed
    three separate times, which read like three faults rather than one wrong
    directory. Worse, a *writable* system directory would have been scribbled
    in silently.
    """
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        with pytest.raises(LmiError) as exc:
            resolve_state(make_cfg(ro))
        assert exc.value.code == 2
        message = str(exc.value)
        assert "working directory" in message
        assert "-d" in message           # the advice, not just the complaint
    finally:
        ro.chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_an_explicit_s_in_an_unwritable_folder_does_not_mention_d(tmp_path, make_cfg):
    """-s was given, so telling the user to pass -d would be wrong advice."""
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        with pytest.raises(LmiError) as exc:
            resolve_state(make_cfg(tmp_path, state_arg=str(ro / "state.md")))
        assert exc.value.code == 2
        assert "-d" not in str(exc.value)
    finally:
        ro.chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_an_unwritable_log_folder_is_still_allowed_through(tmp_path, make_cfg):
    """The guard is deliberately state-only.

    An unwritable log must not abort the run: Logger degrades to console-only
    and warns once, matching run-claude.bat. A writability guard on the log
    would undo that on purpose-built behaviour.
    """
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        got = resolve_log(make_cfg(tmp_path, log_arg=str(ro)), "20260804-120000")
        assert got.parent == ro          # resolved, not rejected
    finally:
        ro.chmod(0o700)
