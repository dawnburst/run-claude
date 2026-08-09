"""The mechanism for touching a JSON file the user cares about."""

import json
import os
import re
import stat

import pytest

from lmi.core import jsonfile
from lmi.core.errors import LmiError
from tests.conftest import skip_as_root

# The exit code is the caller's to choose now that jsonfile lives in core/.
# 3 is what both real callers pass, so most of this module uses it: those tests
# pin the value the real callers see. They cannot pin the *parameter*, because 3
# is also what was hardcoded here before the promotion - every one of them stayed
# green with the five `code` arguments replaced by a literal 3, which is the
# whole of what the refactor changed. That job belongs to SENTINEL below.
CODE = 3

# A value no caller passes and nothing in lmi means, so an argument that reaches
# the raise unread cannot produce it by coincidence.
SENTINEL = 7


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
    assert jsonfile.read(tmp_path / "nope.json", "settings", CODE) == {}


def test_read_empty_file_is_empty(tmp_path):
    path = tmp_path / "e.json"
    path.write_bytes(b"   \n")
    assert jsonfile.read(path, "settings", CODE) == {}


def test_read_returns_the_document(tmp_path):
    path = write_json(tmp_path / "s.json", {"model": "opus", "n": 1})
    assert jsonfile.read(path, "settings", CODE) == {"model": "opus", "n": 1}


def test_read_tolerates_a_bom(tmp_path):
    path = tmp_path / "s.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'{"model": "opus"}')
    assert jsonfile.read(path, "settings", CODE) == {"model": "opus"}


def test_read_invalid_json_is_exit_3(tmp_path):
    """MANDATORY. Silent failure: a user's hand-edited settings discarded.

    Treating unparseable JSON as {} and writing over it would silently destroy
    every setting the user had. Refusing, and naming the file, lets them fix it.
    """
    path = tmp_path / "s.json"
    path.write_text('{"model": }', encoding="utf-8")
    with pytest.raises(LmiError) as exc:
        jsonfile.read(path, "settings", CODE)
    assert exc.value.code == 3
    assert "s.json" in str(exc.value)


def test_read_a_json_array_is_exit_3(tmp_path):
    path = write_json(tmp_path / "s.json", [1, 2])
    with pytest.raises(LmiError) as exc:
        jsonfile.read(path, "settings", CODE)
    assert exc.value.code == 3


def test_backup_of_a_missing_file_is_none(tmp_path):
    assert jsonfile.backup(tmp_path / "nope.json", "20260806-120000", "s", CODE) is None


def test_backup_naming_and_content(tmp_path):
    path = write_json(tmp_path / "settings.json", {"model": "opus"})
    dest = jsonfile.backup(path, "20260806-120000", "settings", CODE)
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
    dest = jsonfile.backup(path, "20260806-120000", "claude.json", CODE)
    assert stat.S_IMODE(os.stat(str(dest)).st_mode) == 0o600


def test_write_creates_missing_parents(tmp_path):
    path = tmp_path / "home" / ".claude" / "settings.json"
    jsonfile.write(path, {"model": "opus"}, "settings", CODE)
    assert json.loads(path.read_text(encoding="utf-8")) == {"model": "opus"}


def test_write_is_indented_and_newline_terminated(tmp_path):
    path = tmp_path / "s.json"
    jsonfile.write(path, {"a": {"b": 1}}, "settings", CODE)
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert '\n  "a"' in text, "2-space indent, matching what Claude Code writes"


def test_write_uses_lf_even_on_windows(tmp_path):
    path = tmp_path / "s.json"
    jsonfile.write(path, {"a": 1}, "settings", CODE)
    assert b"\r\n" not in path.read_bytes()


def test_write_leaves_no_temp_file(tmp_path):
    path = tmp_path / "s.json"
    jsonfile.write(path, {"a": 1}, "settings", CODE)
    assert [p.name for p in tmp_path.iterdir()] == ["s.json"]


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_write_preserves_an_existing_mode(tmp_path):
    path = write_json(tmp_path / ".claude.json", {"a": 1}, mode=0o600)
    jsonfile.write(path, {"a": 2}, "claude.json", CODE)
    assert stat.S_IMODE(os.stat(str(path)).st_mode) == 0o600


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_write_can_force_a_mode(tmp_path):
    path = write_json(tmp_path / "settings.json", {"a": 1}, mode=0o644)
    jsonfile.write(path, {"a": 2}, "settings", CODE, mode=0o600)
    assert stat.S_IMODE(os.stat(str(path)).st_mode) == 0o600


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_the_mode_is_set_before_the_file_becomes_visible(tmp_path, monkeypatch):
    """MANDATORY. Silent failure: a file published at the wrong mode.

    This pins the WIDENING case, and only the widening case. The temp file is
    born 0600 (see the test below), so a target mode that is narrower or equal
    is already satisfied at birth and the chmod could be deleted, moved after
    os.replace, or moved to next Tuesday without any test noticing. A mode that
    must end up LESS restrictive than the birth mode is the one that can only
    come from the chmod - and it still has to land on the temp file, before the
    rename, or settings.json becomes visible under its real name at 0600 and
    only then widens.

    Hence 0644 rather than 0600, which is what makes the assertion
    discriminating. Do not "tidy" it back to 0600 to match its neighbours: that
    is exactly how this test was hollowed out once already, when the birth mode
    changed underneath it and it stayed green with the chmod moved after the
    replace.

    Deliberately behavioural, for the same reason. An earlier draft asserted
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
    jsonfile.write(tmp_path / "s.json", {"a": 1}, "settings", CODE, mode=0o644)
    assert captured["mode"] == 0o644


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_a_brand_new_file_is_created_0600(tmp_path):
    """With no `mode` and no existing file there is nothing to relax to.

    The 0600 outcome is emergent - it holds because `effective` stays None - so
    a tidy-up like `effective = mode if mode is not None else (existing or
    0o644)` would undo it silently. Both documents this command writes may hold
    a credential or the user's project history; neither wants the umask default.
    """
    path = tmp_path / "settings.json"
    jsonfile.write(path, {"a": 1}, "settings", CODE)
    assert stat.S_IMODE(os.stat(str(path)).st_mode) == 0o600


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
        path, {"env": {"ANTHROPIC_AUTH_TOKEN": "sk-secret"}}, "settings", CODE,
        mode=0o600,
    )

    assert captured["mode"] == 0o600
    assert not captured["mode"] & 0o077, "never group- or world-readable"
    assert stat.S_IMODE(os.stat(str(path)).st_mode) == 0o600


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_write_to_an_unwritable_directory_is_exit_3(tmp_path, readonly_dir):
    with pytest.raises(LmiError) as exc:
        jsonfile.write(readonly_dir / "s.json", {"a": 1}, "settings", CODE)
    assert exc.value.code == 3


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_a_failed_write_leaves_no_temp_file(tmp_path, readonly_dir):
    with pytest.raises(LmiError):
        jsonfile.write(readonly_dir / "s.json", {"a": 1}, "settings", CODE)
    assert list(readonly_dir.iterdir()) == []


# The `code` parameter is the only thing the promotion to core/ changed about
# this module's behaviour, and it is invisible to every test above: they pass 3,
# which is exactly what the five raise sites hardcoded beforehand. The tests
# below pass SENTINEL instead, so a raise that ignores its argument reports 3 and
# fails. There is one per raise site rather than one per function, because a
# single unpinned site is enough to reintroduce a core/ module with an opinion
# about a command's exit codes.


@pytest.mark.parametrize(
    "content", ['{"model": }', "[1, 2]"], ids=["unparseable", "not-an-object"]
)
def test_read_raises_with_the_code_it_was_given(tmp_path, content):
    path = tmp_path / "s.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(LmiError) as exc:
        jsonfile.read(path, "settings", SENTINEL)
    assert exc.value.code == SENTINEL


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_an_unreadable_file_raises_with_the_code_it_was_given(tmp_path):
    path = write_json(tmp_path / "s.json", {"a": 1}, mode=0o000)
    with pytest.raises(LmiError) as exc:
        jsonfile.read(path, "settings", SENTINEL)
    assert exc.value.code == SENTINEL


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_backup_raises_with_the_code_it_was_given(tmp_path):
    """The source is a file (so backup proceeds) that copy2 cannot open."""
    path = write_json(tmp_path / "s.json", {"a": 1}, mode=0o000)
    with pytest.raises(LmiError) as exc:
        jsonfile.backup(path, "20260806-120000", "settings", SENTINEL)
    assert exc.value.code == SENTINEL


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_write_raises_with_the_code_it_was_given(readonly_dir):
    with pytest.raises(LmiError) as exc:
        jsonfile.write(readonly_dir / "s.json", {"a": 1}, "settings", SENTINEL)
    assert exc.value.code == SENTINEL
