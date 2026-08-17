"""Where switch files live, and what they are called.

The collection, not the document: fragment.py owns one file's contents, this
owns the folder they sit in and the name convention that finds them.
"""

import json

import pytest

from lmi.commands.config import catalog
from lmi.core.errors import LmiError


def put(path, doc=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({} if doc is None else doc, fh)
    return path


def switch_file(folder, name, doc=None):
    return put(folder / ("%s%s%s" % (catalog.PREFIX, name, catalog.SUFFIX)), doc)


# --- the name convention --------------------------------------------------

def test_a_name_becomes_the_documented_filename(tmp_path):
    assert catalog.path_for(tmp_path, "gateway") == \
        tmp_path / "settings_switch_gateway.json"


def test_the_prefix_is_spelled_as_documented():
    """The README and every site's folder are built on this string."""
    assert catalog.PREFIX == "settings_switch_"
    assert catalog.SUFFIX == ".json"


def test_a_name_with_a_path_separator_is_refused(tmp_path):
    """MANDATORY. The name becomes a filename, so it must not be a path.

    `lmi config switch ../../etc/passwd` has to be a bad name, not a path
    expression: without this the argument reads any JSON document on the
    machine and merges it into settings.json, which is both an escape from the
    config folder and a way to write a settings file from something that was
    never meant to be one.
    """
    for bad in ("../../etc/passwd", "a/b", "a\\b", "/abs", ".", ".."):
        with pytest.raises(LmiError) as exc:
            catalog.path_for(tmp_path, bad)
        assert exc.value.code == 2, bad


def test_an_empty_or_odd_name_is_refused(tmp_path):
    for bad in ("", " ", "a b", "naïve", "a;b", "a*b"):
        with pytest.raises(LmiError) as exc:
            catalog.path_for(tmp_path, bad)
        assert exc.value.code == 2, bad


def test_the_ordinary_name_characters_are_allowed(tmp_path):
    for good in ("gateway", "corp-prod", "corp_prod", "v1.2", "A9"):
        assert catalog.path_for(tmp_path, good).name.startswith(catalog.PREFIX)


def test_the_restore_keyword_is_not_a_selectable_name(tmp_path):
    """MANDATORY. `origin` restores; it must never also apply a file.

    The two meanings occupy one argument now, so the keyword wins and the file
    is unreachable. Silent if it did not: `lmi config switch origin` would
    merge a fragment instead of restoring the machine's pristine settings, at
    exit 0, and the operator would be told the restore had happened.
    """
    switch_file(tmp_path, "origin")
    with pytest.raises(LmiError) as exc:
        catalog.path_for(tmp_path, "origin")
    assert exc.value.code == 2
    assert "origin" in str(exc.value)


# --- scanning a folder ----------------------------------------------------

def test_scan_lists_every_switch_file_by_name(tmp_path):
    switch_file(tmp_path, "opus")
    switch_file(tmp_path, "gateway")
    switch_file(tmp_path, "local")
    entries, reserved = catalog.scan(tmp_path)
    assert [name for name, _ in entries] == ["gateway", "local", "opus"]
    assert reserved == []


def test_scan_ignores_everything_that_is_not_a_switch_file(tmp_path):
    put(tmp_path / "lmi.json")
    put(tmp_path / "settings.json")
    put(tmp_path / "settings_switch.json")      # the unnamed legacy default
    put(tmp_path / "settings_switch_.json")     # prefix with no name
    put(tmp_path / "notes.txt")
    (tmp_path / "settings_switch_dir.json").mkdir()
    switch_file(tmp_path, "real")
    entries, reserved = catalog.scan(tmp_path)
    assert [name for name, _ in entries] == ["real"]
    assert reserved == []


def test_scan_reports_a_reserved_name_separately(tmp_path):
    """It exists, it cannot be chosen, and saying nothing would be the bug."""
    switch_file(tmp_path, "origin")
    switch_file(tmp_path, "gateway")
    entries, reserved = catalog.scan(tmp_path)
    assert [name for name, _ in entries] == ["gateway"]
    assert reserved == ["origin"]


def test_scan_of_a_folder_with_nothing_in_it_is_empty(tmp_path):
    assert catalog.scan(tmp_path) == ([], [])


def test_scan_of_a_missing_folder_does_not_raise(tmp_path):
    """The caller turns an empty list into its own message; a folder that is
    not there is the same answer as a folder with nothing in it."""
    assert catalog.scan(tmp_path / "nope") == ([], [])


# --- the folder itself ----------------------------------------------------

def test_the_folder_is_the_one_holding_the_resolved_config(tmp_path, monkeypatch):
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    put(tmp_path / "config" / "lmi.json")
    assert catalog.folder(None) == tmp_path / "config"


def test_an_explicit_config_retargets_the_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    put(tmp_path / "config" / "lmi.json")
    elsewhere = put(tmp_path / "other" / "lmi.json")
    assert catalog.folder(str(elsewhere)) == tmp_path / "other"


def test_no_config_file_anywhere_is_a_usage_error(tmp_path, monkeypatch, home):
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(LmiError) as exc:
        catalog.folder(None)
    assert exc.value.code == 2
