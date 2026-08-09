"""The pristine snapshot: written once, restored once, then gone."""

import json
import os
import stat

import pytest

from lmi.commands.config import origin
from lmi.core.errors import LmiError
from tests.conftest import skip_as_root

CODE = 3


def settings(home):
    return home / ".claude" / "settings.json"


def put(path, doc, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    if mode is not None:
        os.chmod(str(path), mode)
    return path


def test_the_suffix_is_spelled_exactly():
    assert origin.SUFFIX == ".lmi-origin"


def test_path_sits_beside_settings_json(home):
    assert origin.path().name == "settings.json.lmi-origin"
    assert origin.path().parent == settings(home).parent


def test_capture_writes_when_absent(home):
    assert origin.capture({"model": "sonnet"}, CODE) is True
    assert json.loads(origin.path().read_text(encoding="utf-8")) == {"model": "sonnet"}


def test_capture_is_write_once(home):
    """MANDATORY. Silent failure: `origin` stops meaning your real settings.

    The snapshot must be written only if it does not already exist. Written
    unconditionally, `origin` silently becomes "undo one step" while still being
    spelled origin, and the pristine settings are unrecoverable after the second
    switch. Nothing observable distinguishes the two: the file is present either
    way, and a single switch behaves identically.
    """
    origin.capture({"generation": 0}, CODE)
    assert origin.capture({"generation": 1}, CODE) is False
    assert origin.capture({"generation": 2}, CODE) is False
    assert json.loads(origin.path().read_text(encoding="utf-8")) == {"generation": 0}


def test_exists_reflects_the_file(home):
    assert origin.exists() is False
    origin.capture({"a": 1}, CODE)
    assert origin.exists() is True


def test_restore_puts_it_back_and_removes_the_snapshot(home):
    put(settings(home), {"model": "sonnet"})
    origin.capture({"model": "sonnet"}, CODE)
    put(settings(home), {"model": "opus"})

    origin.restore(CODE)
    assert json.loads(settings(home).read_text(encoding="utf-8")) == {"model": "sonnet"}
    assert origin.exists() is False


def test_restore_returns_the_file_it_overwrote(home):
    """The return value is settings.json, not the snapshot it consumed.

    runner._restore prints it as "Restored <path>", so returning path() instead
    would name a file that no longer exists - and every other test in this
    module stays green either way, which is why this one is here.
    """
    put(settings(home), {"a": 1})
    origin.capture({"a": 1}, CODE)
    assert origin.restore(CODE) == settings(home)


def test_restore_without_a_snapshot_is_usage(home):
    with pytest.raises(LmiError) as exc:
        origin.restore(CODE)
    assert exc.value.code == 2
    assert "nothing to restore" in str(exc.value)


def test_restore_twice_is_usage_the_second_time(home):
    put(settings(home), {"a": 1})
    origin.capture({"a": 1}, CODE)
    origin.restore(CODE)
    with pytest.raises(LmiError) as exc:
        origin.restore(CODE)
    assert exc.value.code == 2


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_the_snapshot_is_0600(home):
    """It can hold ANTHROPIC_AUTH_TOKEN, and ~/.claude/ is 0755.

    This asserts the BIRTH mode and cannot prove the forced one. jsonfile.write
    creates its temp file 0600 and has no existing mode to relax to here -
    capture() only ever writes when the snapshot is absent - so `mode=0o600` can
    be dropped from the call and this stays green under any normal umask. The
    argument is still right and stays: it is what makes the mode a stated
    property of the snapshot rather than a coincidence of the writer, and
    jsonfile is free to change its default. Same trap as
    test_a_written_token_forces_mode_600 in the install suite, which can escape
    it with a pre-existing 0644 file; no reachable state here can.
    """
    origin.capture({"env": {"ANTHROPIC_AUTH_TOKEN": "sk-x"}}, CODE)
    assert stat.S_IMODE(os.stat(str(origin.path())).st_mode) == 0o600


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_a_restored_settings_file_is_0600(home):
    put(settings(home), {"env": {"ANTHROPIC_AUTH_TOKEN": "sk-x"}}, mode=0o600)
    origin.capture({"env": {"ANTHROPIC_AUTH_TOKEN": "sk-x"}}, CODE)
    put(settings(home), {"model": "opus"}, mode=0o644)
    origin.restore(CODE)
    assert stat.S_IMODE(os.stat(str(settings(home))).st_mode) == 0o600
