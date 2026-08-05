"""lmi.core.fs - path classification and UNC detection.

looks_like_unc is string logic only, and its caller decides whether it applies.
Where that guard is enforced for the state file is tested in
tests/commands/schedule/test_paths.py; this module pins the detection itself.
"""

import pytest

from lmi.core import fs


@pytest.mark.parametrize("text", [
    r"\\wsl.localhost\Ubuntu\home",
    "//wsl.localhost/Ubuntu/home",
    r"\\server\share",
    r"\\?\UNC\server\share\dir",     # a share wearing a device prefix
    r"\\.\UNC\server\share",
])
def test_looks_like_unc_accepts_every_share_spelling(text):
    assert fs.looks_like_unc(text) is True


@pytest.mark.parametrize("text", [
    r"C:\work\state.md",
    "/home/u/work/state.md",
    r"\\?\C:\work",                  # a LOCAL drive wearing the same prefix
    r"\\.\C:\work",
    r"\relative\single",
    "relative/path",
])
def test_looks_like_unc_rejects_local_paths(text):
    assert fs.looks_like_unc(text) is False


def test_classify_names_what_is_there(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x", encoding="utf-8")
    assert fs.classify(tmp_path) == (fs.DIR, "")
    assert fs.classify(f) == (fs.FILE, "")
    assert fs.classify(tmp_path / "nope") == (fs.MISSING, "")


def test_an_unanswerable_path_is_unknown_with_a_reason(tmp_path):
    """The whole reason this module exists: it must not raise.

    Path.is_dir() swallows ENOENT, ENOTDIR, EBADF and ELOOP and lets everything
    else through - ENAMETOOLONG in particular, which an inline prompt of 256
    bytes without a slash is enough to trigger.
    """
    kind, reason = fs.classify(tmp_path / ("a" * 300))
    assert kind == fs.UNKNOWN
    assert reason                                  # the OS message, for the user
    # An embedded NUL is a ValueError rather than an OSError, and answers the
    # same way.
    assert fs.classify("x\0y")[0] == fs.UNKNOWN


def test_kind_is_classify_without_the_reason(tmp_path):
    assert fs.kind(tmp_path) == fs.DIR
    assert fs.kind(tmp_path / "nope") == fs.MISSING
