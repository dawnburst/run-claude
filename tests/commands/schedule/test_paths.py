import os
from pathlib import Path

import pytest

from lmi.commands.schedule.paths import (
    has_extension, resolve_log, resolve_state, timestamp,
)
from lmi.core.errors import LmiError

from ...conftest import skip_as_root
from .conftest import TS


def test_timestamp_shape():
    ts = timestamp()
    assert len(ts) == 15 and ts[8] == "-" and ts.replace("-", "").isdigit()


def test_default_state_path_is_beside_the_workdir(tmp_path, make_cfg):
    assert resolve_state(make_cfg(tmp_path)) == tmp_path / "run-claude-state.md"


def test_state_parent_is_created_when_missing(tmp_path, make_cfg):
    """A missing parent is created, and only a failure to create it is an error."""
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
    """The trap: rule 4 makes this a DIRECTORY containing a timestamped log,
    not a file named 'newlogs'."""
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
    """Documented in the README: a quoted -s "~/x" must land in the home
    directory, not in a folder literally named '~'."""
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


@skip_as_root
def test_unwritable_log_parent_is_a_clear_error(tmp_path, make_cfg, readonly_dir):
    with pytest.raises(LmiError) as exc:
        resolve_log(
            make_cfg(tmp_path, log_arg=str(readonly_dir / "sub" / "x.log")), TS
        )
    assert exc.value.code == 2


@skip_as_root
def test_an_unwritable_working_directory_says_to_pass_d(make_cfg, readonly_dir):
    """One clear error naming -d, not three Permission denied in a row.

    The report this comes from: on Windows, cmd.exe cannot hold a UNC working
    directory, so launching from \\\\wsl.localhost\\... left the process in
    C:\\Windows. lmi then aimed its state file, log and lock there and failed
    three separate times, which read like three faults rather than one wrong
    directory. Worse, a *writable* system directory would have been scribbled
    in silently.
    """
    with pytest.raises(LmiError) as exc:
        resolve_state(make_cfg(readonly_dir))
    assert exc.value.code == 2
    message = str(exc.value)
    assert "working directory" in message
    assert "-d" in message               # the advice, not just the complaint


@skip_as_root
def test_an_explicit_s_in_an_unwritable_folder_does_not_mention_d(
    tmp_path, make_cfg, readonly_dir
):
    """-s was given, so telling the user to pass -d would be wrong advice."""
    with pytest.raises(LmiError) as exc:
        resolve_state(make_cfg(tmp_path, state_arg=str(readonly_dir / "state.md")))
    assert exc.value.code == 2
    assert "-d" not in str(exc.value)


@skip_as_root
def test_an_unwritable_log_folder_is_still_allowed_through(
    tmp_path, make_cfg, readonly_dir
):
    """The guard is deliberately state-only.

    An unwritable log must not abort the run: Logger degrades to console-only
    and warns once. A writability guard on the log would undo that on purpose-
    built behaviour.
    """
    got = resolve_log(make_cfg(tmp_path, log_arg=str(readonly_dir)), TS)
    assert got.parent == readonly_dir    # resolved, not rejected


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
# these tests build a UNC-looking path on Linux at all. The `on_windows` fixture
# takes the Windows branch; the detection itself is tested in tests/test_fs.py.

UNC_WORKDIR = Path("//wsl.localhost/Ubuntu-24.04/home/u/work")
UNC_STATE = "//wsl.localhost/Ubuntu-24.04/home/u/work/run-claude-state.md"


def test_unc_working_directory_is_refused_on_windows(on_windows, make_cfg):
    cfg = make_cfg(UNC_WORKDIR)
    with pytest.raises(LmiError) as caught:
        resolve_state(cfg)
    assert caught.value.code == 2
    message = str(caught.value)
    assert "network share" in message and "UNC" in message
    # It must offer the escape hatch, not just say no: the working directory can
    # stay on the share as long as the state file does not.
    assert "-s C:\\lmi\\run-claude-state.md" in message


def test_unc_state_file_is_refused_on_windows(on_windows, tmp_path, make_cfg):
    with pytest.raises(LmiError) as caught:
        resolve_state(make_cfg(tmp_path, state_arg=UNC_STATE))
    assert caught.value.code == 2
    assert "network share" in str(caught.value)


def test_a_local_state_file_under_a_unc_workdir_is_allowed(
    on_windows, tmp_path, make_cfg
):
    """The documented workaround has to actually work.

    Working directory on the share, state file - and therefore the lock - on a
    local drive. This is the case the guard must NOT reject.
    """
    target = tmp_path / "run-claude-state.md"
    assert resolve_state(make_cfg(UNC_WORKDIR, state_arg=str(target))) == target


def test_a_unc_looking_path_is_accepted_off_windows(tmp_path, make_cfg):
    """On POSIX a // path is local, so the guard must stay out of the way.

    Deliberately a genuinely //-prefixed path, not just any local one: pathlib
    preserves exactly two leading slashes, so this is the same text the Windows
    branch refuses, and only the platform check decides the difference.
    """
    assert os.name != "nt", "this test describes the POSIX branch"
    doubled = "/" + str(tmp_path / "st.md")     # //tmp/... - local on POSIX
    got = resolve_state(make_cfg(tmp_path, state_arg=doubled))
    assert got.parts[0] == "//" and got.name == "st.md"


def test_windows_directory_names_the_cmd_unc_cause(
    on_windows, deny_touch, monkeypatch, tmp_path, make_cfg
):
    r"""cmd.exe started on a share substitutes the Windows directory silently.

    By the time lmi runs the UNC path is gone, so the UNC guard cannot see it and
    all that is left is an unwritable C:\Windows. The hint is the only place the
    real cause gets named.
    """
    fake_root = tmp_path / "Windows"
    fake_root.mkdir()
    monkeypatch.setenv("SystemRoot", str(fake_root))
    with pytest.raises(LmiError) as caught:
        resolve_state(make_cfg(fake_root))
    message = str(caught.value)
    assert caught.value.code == 2
    assert "cmd.exe" in message and "UNC working directory" in message


def test_an_ordinary_unwritable_directory_gets_no_cmd_hint(
    on_windows, deny_touch, monkeypatch, tmp_path, make_cfg
):
    """The hint must not appear for a directory that simply is not writable."""
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Windows"))
    with pytest.raises(LmiError) as caught:
        resolve_state(make_cfg(tmp_path))
    assert "cmd.exe" not in str(caught.value)
