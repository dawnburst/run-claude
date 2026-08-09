"""Locating and validating a settings.json fragment."""

import json

import pytest

from lmi.commands.config import fragment
from lmi.core.errors import LmiError


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    return path


def test_the_default_path_is_used_when_no_file_is_given(tmp_path, monkeypatch):
    expected = write(tmp_path / "config" / "settings_switch.json", {"model": "opus"})
    monkeypatch.chdir(tmp_path)
    doc, path = fragment.load(None)
    assert doc == {"model": "opus"}
    assert path == expected


def test_the_default_name_is_spelled_exactly():
    assert fragment.DEFAULT_NAME == "config/settings_switch.json"


def test_an_explicit_file_is_used(tmp_path, monkeypatch):
    chosen = write(tmp_path / "prod.json", {"model": "opus"})
    write(tmp_path / "config" / "settings_switch.json", {"model": "WRONG"})
    monkeypatch.chdir(tmp_path)
    doc, path = fragment.load(str(chosen))
    assert doc == {"model": "opus"}
    assert path == chosen


def test_a_missing_explicit_file_does_not_fall_back(tmp_path, monkeypatch):
    """MANDATORY. Silent failure: switching to a profile you did not name.

    A --file the user typed and that does not exist must be an error, never a
    quiet fall-through to ./config/settings_switch.json - which would apply a
    different profile while reporting success.
    """
    write(tmp_path / "config" / "settings_switch.json", {"model": "WRONG"})
    monkeypatch.chdir(tmp_path)
    with pytest.raises(LmiError) as exc:
        fragment.load(str(tmp_path / "nope.json"))
    assert exc.value.code == 2


def test_no_file_anywhere_is_a_usage_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(LmiError) as exc:
        fragment.load(None)
    assert exc.value.code == 2
    assert "settings_switch.json" in str(exc.value)


def test_a_utf8_bom_is_tolerated(tmp_path):
    path = tmp_path / "f.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'{"model": "opus"}')
    assert fragment.load(str(path))[0] == {"model": "opus"}


def test_invalid_json_names_the_file(tmp_path):
    path = tmp_path / "f.json"
    path.write_text('{"model": }', encoding="utf-8")
    with pytest.raises(LmiError) as exc:
        fragment.load(str(path))
    assert exc.value.code == 2
    assert "f.json" in str(exc.value)


@pytest.mark.parametrize("doc", [[1, 2], "text", 5])
def test_a_non_object_top_level_is_rejected(tmp_path, doc):
    path = write(tmp_path / "f.json", doc)
    with pytest.raises(LmiError) as exc:
        fragment.load(str(path))
    assert exc.value.code == 2


def test_a_non_string_env_value_is_rejected(tmp_path):
    """MANDATORY. Silent failure: the switched setting does not apply.

    Claude Code types settings.json env as string-to-string. A JSON number
    writes cleanly, parses cleanly, and the setting does nothing.
    """
    path = write(tmp_path / "f.json", {"env": {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": 32000}})
    with pytest.raises(LmiError) as exc:
        fragment.load(str(path))
    assert exc.value.code == 2
    assert "string" in str(exc.value)


def test_a_string_env_value_is_accepted(tmp_path):
    path = write(tmp_path / "f.json", {"env": {"A": "1"}})
    assert fragment.load(str(path))[0] == {"env": {"A": "1"}}


def test_a_non_object_env_is_rejected(tmp_path):
    path = write(tmp_path / "f.json", {"env": ["not", "a", "map"]})
    with pytest.raises(LmiError) as exc:
        fragment.load(str(path))
    assert exc.value.code == 2


def test_a_null_env_is_rejected(tmp_path):
    """MANDATORY. Silent failure: the whole env block discarded at exit 0.

    `null` is a value here, not an absence, so a merged "env": null replaces the
    entire block - ANTHROPIC_AUTH_TOKEN, base URL and all - and reports success.
    A `doc.get("env") is None` guard cannot see the difference between this and
    a fragment that never mentioned env, so it waves it through while rejecting
    "env": [] and "env": "x" beside it.
    """
    path = write(tmp_path / "f.json", {"env": None})
    with pytest.raises(LmiError) as exc:
        fragment.load(str(path))
    assert exc.value.code == 2
    assert "env" in str(exc.value)


def test_a_null_value_under_another_key_is_still_accepted(tmp_path):
    """Only `env` is typed. Everywhere else null is an ordinary value - it sets.

    The counterpart to test_null_sets_and_does_not_delete in the merge suite: a
    validator that grew a blanket "no nulls" rule would take that away.
    """
    path = write(tmp_path / "f.json", {"model": None})
    assert fragment.load(str(path))[0] == {"model": None}


def test_an_unknown_key_passes_through_untouched(tmp_path):
    """lmi does not model Claude Code's schema; it reports typos better."""
    exotic = {"somethingAddedIn2027": {"nested": [1, {"a": 2}]}}
    path = write(tmp_path / "f.json", exotic)
    assert fragment.load(str(path))[0] == exotic


def test_an_empty_object_is_accepted(tmp_path):
    path = write(tmp_path / "f.json", {})
    assert fragment.load(str(path))[0] == {}


def test_tilde_user_that_cannot_resolve_is_usage_not_a_traceback():
    with pytest.raises(LmiError) as exc:
        fragment.load("~nosuchuser-lmi/f.json")
    assert exc.value.code == 2
