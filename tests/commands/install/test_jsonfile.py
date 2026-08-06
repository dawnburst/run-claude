"""The mechanism for touching a JSON file the user cares about."""

import json
import os
import re
import stat

import pytest

from lmi.commands.install import jsonfile
from lmi.core.errors import LmiError
from tests.conftest import skip_as_root


def write_json(path, doc, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    if mode is not None:
        os.chmod(str(path), mode)
    return path


def test_timestamp_shape():
    assert re.match(r"^\d{8}-\d{6}$", jsonfile.timestamp())


def test_read_missing_file_is_empty(tmp_path):
    assert jsonfile.read(tmp_path / "nope.json", "settings") == {}


def test_read_empty_file_is_empty(tmp_path):
    path = tmp_path / "e.json"
    path.write_bytes(b"   \n")
    assert jsonfile.read(path, "settings") == {}


def test_read_returns_the_document(tmp_path):
    path = write_json(tmp_path / "s.json", {"model": "opus", "n": 1})
    assert jsonfile.read(path, "settings") == {"model": "opus", "n": 1}


def test_read_tolerates_a_bom(tmp_path):
    path = tmp_path / "s.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'{"model": "opus"}')
    assert jsonfile.read(path, "settings") == {"model": "opus"}


def test_read_invalid_json_is_exit_3(tmp_path):
    """MANDATORY. Silent failure: a user's hand-edited settings discarded.

    Treating unparseable JSON as {} and writing over it would silently destroy
    every setting the user had. Refusing, and naming the file, lets them fix it.
    """
    path = tmp_path / "s.json"
    path.write_text('{"model": }', encoding="utf-8")
    with pytest.raises(LmiError) as exc:
        jsonfile.read(path, "settings")
    assert exc.value.code == 3
    assert "s.json" in str(exc.value)


def test_read_a_json_array_is_exit_3(tmp_path):
    path = write_json(tmp_path / "s.json", [1, 2])
    with pytest.raises(LmiError) as exc:
        jsonfile.read(path, "settings")
    assert exc.value.code == 3


def test_backup_of_a_missing_file_is_none(tmp_path):
    assert jsonfile.backup(tmp_path / "nope.json", "20260806-120000", "s") is None


def test_backup_naming_and_content(tmp_path):
    path = write_json(tmp_path / "settings.json", {"model": "opus"})
    dest = jsonfile.backup(path, "20260806-120000", "settings")
    assert dest.name == "settings.json.bk_20260806-120000"
    assert json.loads(dest.read_text(encoding="utf-8")) == {"model": "opus"}
    assert path.exists(), "the original must remain"


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_backup_preserves_mode(tmp_path):
    """~/.claude.json is 0600 and holds per-project history.

    A backup at the default 0644 would publish it to every user on the box.
    """
    path = write_json(tmp_path / ".claude.json", {"a": 1}, mode=0o600)
    dest = jsonfile.backup(path, "20260806-120000", "claude.json")
    assert stat.S_IMODE(os.stat(str(dest)).st_mode) == 0o600


def test_write_creates_missing_parents(tmp_path):
    path = tmp_path / "home" / ".claude" / "settings.json"
    jsonfile.write(path, {"model": "opus"}, "settings")
    assert json.loads(path.read_text(encoding="utf-8")) == {"model": "opus"}


def test_write_is_indented_and_newline_terminated(tmp_path):
    path = tmp_path / "s.json"
    jsonfile.write(path, {"a": {"b": 1}}, "settings")
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert '\n  "a"' in text, "2-space indent, matching what Claude Code writes"


def test_write_uses_lf_even_on_windows(tmp_path):
    path = tmp_path / "s.json"
    jsonfile.write(path, {"a": 1}, "settings")
    assert b"\r\n" not in path.read_bytes()


def test_write_leaves_no_temp_file(tmp_path):
    path = tmp_path / "s.json"
    jsonfile.write(path, {"a": 1}, "settings")
    assert [p.name for p in tmp_path.iterdir()] == ["s.json"]


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_write_preserves_an_existing_mode(tmp_path):
    path = write_json(tmp_path / ".claude.json", {"a": 1}, mode=0o600)
    jsonfile.write(path, {"a": 2}, "claude.json")
    assert stat.S_IMODE(os.stat(str(path)).st_mode) == 0o600


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_write_can_force_a_mode(tmp_path):
    path = write_json(tmp_path / "settings.json", {"a": 1}, mode=0o644)
    jsonfile.write(path, {"a": 2}, "settings", mode=0o600)
    assert stat.S_IMODE(os.stat(str(path)).st_mode) == 0o600


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_the_mode_is_set_before_the_file_becomes_visible(tmp_path, monkeypatch):
    """MANDATORY. Silent failure: a token briefly readable by everyone.

    The chmod must land on the temp file BEFORE os.replace publishes it, or
    there is a window in which settings.json holds an auth token at the default
    0644 and any user on the box can read it. Nothing observable afterwards
    distinguishes the two orderings - the end state is identical - so the only
    way to pin it is to look at the mode at the instant of the rename.

    Deliberately behavioural. An earlier draft asserted
    `inspect.getsource(...).index("chmod") < ....index("os.replace")`, which
    could never fail: getsource includes the docstring, and the docstring says
    "chmod ... BEFORE os.replace", so the assertion was satisfied by prose no
    matter what the code did.
    """
    captured = {}
    real_replace = os.replace

    def spy(src, dst):
        captured["mode"] = stat.S_IMODE(os.stat(src).st_mode)
        return real_replace(src, dst)

    monkeypatch.setattr(jsonfile.os, "replace", spy)
    jsonfile.write(tmp_path / "s.json", {"a": 1}, "settings", mode=0o600)
    assert captured["mode"] == 0o600


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_the_temp_file_is_private_before_any_content_reaches_it(
    tmp_path, monkeypatch
):
    """MANDATORY. Silent failure: a token readable by every user on the box.

    Setting the mode before os.replace is not enough. The temp file is written
    inside ~/.claude/, which is 0755, so a temp file created at the umask
    default holds the auth token in a world-readable file for the whole
    duration of the write - and the finished settings.json is 0600 afterwards,
    so nothing about the end state shows it ever happened.

    The window is what is pinned here, not the outcome: the mode is captured at
    the moment the descriptor is handed to the writer, which is before the
    first byte of the document exists on disk.
    """
    captured = {}
    real_fdopen = os.fdopen

    def spy(fd, *args, **kwargs):
        captured["mode"] = stat.S_IMODE(os.fstat(fd).st_mode)
        return real_fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(jsonfile.os, "fdopen", spy)
    path = tmp_path / "settings.json"
    jsonfile.write(
        path, {"env": {"ANTHROPIC_AUTH_TOKEN": "sk-secret"}}, "settings",
        mode=0o600,
    )

    assert captured["mode"] == 0o600
    assert not captured["mode"] & 0o077, "never group- or world-readable"
    assert stat.S_IMODE(os.stat(str(path)).st_mode) == 0o600


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_write_to_an_unwritable_directory_is_exit_3(tmp_path, readonly_dir):
    with pytest.raises(LmiError) as exc:
        jsonfile.write(readonly_dir / "s.json", {"a": 1}, "settings")
    assert exc.value.code == 3


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_a_failed_write_leaves_no_temp_file(tmp_path, readonly_dir):
    with pytest.raises(LmiError):
        jsonfile.write(readonly_dir / "s.json", {"a": 1}, "settings")
    assert list(readonly_dir.iterdir()) == []
