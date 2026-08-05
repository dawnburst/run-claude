import os
from pathlib import Path

import pytest

from lmi.commands.schedule import paths
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


# --- UNC paths on Windows ---------------------------------------------------
#
# The lock file is created next to the state file, and Windows byte-range
# locking is unsupported on a share: msvcrt.locking fails with EINVAL on a WSL
# 9p mount, and core.lock reads any OSError from the lock call as contention.
# The measured symptom was exit 3, "another run is working on this state file",
# with nothing else running. These tests pin the refusal that replaced it.
#
# The guard is Windows-only by design: on POSIX a //-prefixed path is local and
# locks correctly, and pathlib keeps the two leading slashes, which is what lets
# these tests build a UNC-looking path on Linux at all.
#
# paths._on_windows is patched rather than os.name, which cannot be patched:
# pathlib picks its concrete class from os.name at instantiation, so forcing it
# to "nt" here makes every Path() raise NotImplementedError.

UNC_STATE = "//wsl.localhost/Ubuntu-24.04/home/u/work/run-claude-state.md"


@pytest.mark.parametrize("text", [
    r"\\wsl.localhost\Ubuntu\home",
    "//wsl.localhost/Ubuntu/home",
    r"\\server\share",
    r"\\?\UNC\server\share\dir",     # a share wearing a device prefix
    r"\\.\UNC\server\share",
])
def test_looks_like_unc_accepts_every_share_spelling(text):
    from lmi.core.fs import looks_like_unc
    assert looks_like_unc(text) is True


@pytest.mark.parametrize("text", [
    r"C:\work\state.md",
    "/home/u/work/state.md",
    r"\\?\C:\work",                  # a LOCAL drive wearing the same prefix
    r"\\.\C:\work",
    r"\relative\single",
    "relative/path",
])
def test_looks_like_unc_rejects_local_paths(text):
    from lmi.core.fs import looks_like_unc
    assert looks_like_unc(text) is False


def test_unc_working_directory_is_refused_on_windows(monkeypatch, make_cfg):
    monkeypatch.setattr(paths, "_on_windows", lambda: True)
    cfg = make_cfg(Path("//wsl.localhost/Ubuntu-24.04/home/u/work"))
    with pytest.raises(LmiError) as caught:
        resolve_state(cfg)
    assert caught.value.code == 2
    message = str(caught.value)
    assert "network share" in message and "UNC" in message
    # It must offer the escape hatch, not just say no: the working directory can
    # stay on the share as long as the state file does not.
    assert "-s C:\\lmi\\run-claude-state.md" in message


def test_unc_state_file_is_refused_on_windows(monkeypatch, tmp_path, make_cfg):
    monkeypatch.setattr(paths, "_on_windows", lambda: True)
    with pytest.raises(LmiError) as caught:
        resolve_state(make_cfg(tmp_path, state_arg=UNC_STATE))
    assert caught.value.code == 2
    assert "network share" in str(caught.value)


def test_a_local_state_file_under_a_unc_workdir_is_allowed(monkeypatch, tmp_path, make_cfg):
    """The documented workaround has to actually work.

    Working directory on the share, state file - and therefore the lock - on a
    local drive. This is the case the guard must NOT reject.
    """
    monkeypatch.setattr(paths, "_on_windows", lambda: True)
    target = tmp_path / "run-claude-state.md"
    cfg = make_cfg(Path("//wsl.localhost/Ubuntu-24.04/home/u/work"),
                   state_arg=str(target))
    assert resolve_state(cfg) == target


def test_unc_is_ignored_off_windows(tmp_path, make_cfg):
    """On POSIX a // path is local, so the guard must stay out of the way."""
    assert os.name != "nt", "this test describes the POSIX branch"
    target = tmp_path / "st.md"
    assert resolve_state(make_cfg(tmp_path, state_arg=str(target))) == target


def test_windows_directory_names_the_cmd_unc_cause(monkeypatch, tmp_path, make_cfg):
    r"""cmd.exe started on a share substitutes the Windows directory silently.

    By the time lmi runs the UNC path is gone, so the UNC guard cannot see it and
    all that is left is an unwritable C:\Windows. The hint is the only place the
    real cause gets named.
    """
    monkeypatch.setattr(paths, "_on_windows", lambda: True)
    fake_root = tmp_path / "Windows"
    fake_root.mkdir()
    monkeypatch.setenv("SystemRoot", str(fake_root))
    # Make the probe fail the way C:\Windows does for an unprivileged user.
    monkeypatch.setattr(paths.Path, "touch",
                        lambda self, *a, **k: (_ for _ in ()).throw(PermissionError(13, "denied")))
    with pytest.raises(LmiError) as caught:
        resolve_state(make_cfg(fake_root))
    message = str(caught.value)
    assert caught.value.code == 2
    assert "cmd.exe" in message and "UNC working directory" in message


def test_an_ordinary_unwritable_directory_gets_no_cmd_hint(monkeypatch, tmp_path, make_cfg):
    """The hint must not appear for a directory that simply is not writable."""
    monkeypatch.setattr(paths, "_on_windows", lambda: True)
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Windows"))
    monkeypatch.setattr(paths.Path, "touch",
                        lambda self, *a, **k: (_ for _ in ()).throw(PermissionError(13, "denied")))
    with pytest.raises(LmiError) as caught:
        resolve_state(make_cfg(tmp_path))
    assert "cmd.exe" not in str(caught.value)
