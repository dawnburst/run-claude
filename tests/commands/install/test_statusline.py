"""Finding the statusline script, and copying it into ~/.claude."""

import os
import stat

import pytest

from lmi.commands.install import statusline
from lmi.core.errors import EXIT_USAGE, LmiError
from tests.conftest import skip_as_root

SCRIPT = b"#!/usr/bin/env node\nprocess.stdout.write('hi');\n"


def write(path, data=SCRIPT):
    with open(str(path), "wb") as fh:
        fh.write(data)
    return path


# --- find -----------------------------------------------------------------

def test_it_is_found_beside_the_config_file(tmp_path):
    write(tmp_path / statusline.NAME)
    assert statusline.find(tmp_path / "lmi.json") == tmp_path / statusline.NAME


def test_a_missing_script_is_none_rather_than_an_error(tmp_path):
    """The script is optional, unlike the settings template.

    A site that wants no statusline has no such file, and an existing config
    folder written before this feature existed must keep installing cleanly.
    """
    assert statusline.find(tmp_path / "lmi.json") is None


def test_a_directory_named_statusline_js_is_not_a_script(tmp_path):
    (tmp_path / statusline.NAME).mkdir()
    assert statusline.find(tmp_path / "lmi.json") is None


def test_it_is_looked_for_beside_the_config_file_not_the_working_dir(tmp_path):
    """One folder, one site - the rule the settings template already follows.

    Resolving the script against the working directory instead would let one
    site's `--config` be paired with another site's statusline.
    """
    site = tmp_path / "site"
    site.mkdir()
    write(tmp_path / statusline.NAME)           # a decoy, in the "wrong" folder
    assert statusline.find(site / "lmi.json") is None


def test_an_unclassifiable_path_is_exit_2(tmp_path):
    """Path.is_file() raises ENAMETOOLONG rather than answering - CLAUDE.md 5."""
    long = tmp_path / ("x" * 300)
    with pytest.raises(LmiError) as exc:
        statusline.find(long / "lmi.json")
    assert exc.value.code == EXIT_USAGE


# --- declares -------------------------------------------------------------

def test_a_template_with_a_statusline_block_declares_one():
    assert statusline.declares({"statusLine": {"type": "command",
                                               "command": "node x.js"}})


def test_a_template_without_one_does_not():
    assert not statusline.declares({"env": {}})


def test_an_explicitly_null_statusline_still_counts_as_declared():
    """`"statusLine": null` is the operator saying something about the key.

    Absent means "no statusline wanted" and is silent; present means the two
    halves are meant to line up, and a missing script is worth a warning even
    when the block is malformed - a template lmi cannot make sense of is
    exactly when the operator most needs to be told what lmi did.
    """
    assert statusline.declares({"statusLine": None})


# --- install --------------------------------------------------------------

def test_it_lands_in_the_claude_folder_byte_for_byte(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    src = write(tmp_path / statusline.NAME)
    dest = statusline.path()

    statusline.install(src, dest, "script", 3)

    assert dest == tmp_path / "home" / ".claude" / statusline.NAME
    assert dest.read_bytes() == SCRIPT


def test_crlf_and_a_missing_final_newline_survive(tmp_path):
    """MANDATORY. Silent failure: a script lmi edited without being asked to.

    The copy is bytes, not text. Normalising line endings or re-encoding on
    the way through would rewrite somebody's script, and the damage shows up
    as a statusline that behaves subtly differently on one platform.
    """
    odd = b"// \xc3\xa9\r\nconst x = 1;\r\nprocess.stdout.write(String(x));"
    src = write(tmp_path / statusline.NAME, odd)
    dest = tmp_path / "out" / statusline.NAME

    statusline.install(src, dest, "script", 3)

    assert dest.read_bytes() == odd


def test_an_existing_script_is_replaced_whole(tmp_path):
    src = write(tmp_path / statusline.NAME)
    dest = tmp_path / "out" / statusline.NAME
    dest.parent.mkdir()
    write(dest, b"// the previous one, much longer than the new one\n" * 20)

    statusline.install(src, dest, "script", 3)

    assert dest.read_bytes() == SCRIPT


def test_the_executable_bit_is_carried_over(tmp_path):
    """A template may run the script directly rather than through `node`.

    Dropping the mode makes that command fail with EACCES on every keystroke,
    for a file that is present and correct.
    """
    src = write(tmp_path / statusline.NAME)
    os.chmod(str(src), 0o755)
    dest = tmp_path / "out" / statusline.NAME

    statusline.install(src, dest, "script", 3)

    assert stat.S_IMODE(os.stat(str(dest)).st_mode) == 0o755


def test_a_non_executable_script_stays_non_executable(tmp_path):
    src = write(tmp_path / statusline.NAME)
    os.chmod(str(src), 0o644)
    dest = tmp_path / "out" / statusline.NAME

    statusline.install(src, dest, "script", 3)

    assert stat.S_IMODE(os.stat(str(dest)).st_mode) == 0o644


def test_no_temp_file_is_left_behind(tmp_path):
    src = write(tmp_path / statusline.NAME)
    dest = tmp_path / "out" / statusline.NAME

    statusline.install(src, dest, "script", 3)

    assert [p.name for p in dest.parent.iterdir()] == [statusline.NAME]


@skip_as_root
def test_an_unwritable_destination_raises_the_callers_code(tmp_path,
                                                           readonly_dir):
    src = write(tmp_path / statusline.NAME)
    with pytest.raises(LmiError) as exc:
        statusline.install(src, readonly_dir / statusline.NAME, "script", 7)
    assert exc.value.code == 7
    assert statusline.NAME in str(exc.value)


@skip_as_root
def test_an_unreadable_source_is_a_usage_error(tmp_path):
    src = write(tmp_path / statusline.NAME)
    os.chmod(str(src), 0o000)
    try:
        with pytest.raises(LmiError) as exc:
            statusline.install(src, tmp_path / "out" / statusline.NAME,
                               "script", 3)
        assert exc.value.code == EXIT_USAGE
    finally:
        os.chmod(str(src), 0o644)
