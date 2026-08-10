"""Finding and validating the settings.json template.

The template is the whole content of ~/.claude/settings.json, so every way it
can be wrong has to be an error here rather than a surprise in Claude Code.
"""

import json

import pytest

from lmi.commands.install import template
from lmi.core.errors import LmiError


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    return path


def test_the_name_is_spelled_exactly():
    assert template.NAME == "settings.json"


def test_it_is_read_from_beside_the_config_file(tmp_path):
    """The config *folder* is the directory the lmi.json came from."""
    expected = write(tmp_path / "site" / "settings.json", {"theme": "dark"})
    doc, path = template.load(tmp_path / "site" / "lmi.json")
    assert doc == {"theme": "dark"}
    assert path == expected


def test_it_follows_the_config_file_rather_than_the_working_directory(
        tmp_path, monkeypatch):
    """MANDATORY. Silent failure: a machine configured from another site.

    --config names one site's lmi.json; a template resolved against the working
    directory instead would pair it with a different site's settings - a
    different gateway and a different token - and report success.
    """
    write(tmp_path / "site" / "settings.json", {"theme": "right"})
    write(tmp_path / "elsewhere" / "settings.json", {"theme": "WRONG"})
    monkeypatch.chdir(tmp_path / "elsewhere")
    doc, _ = template.load(tmp_path / "site" / "lmi.json")
    assert doc == {"theme": "right"}


def test_a_missing_template_is_a_usage_error(tmp_path):
    """MANDATORY. Silent failure: a binary with no configuration at all.

    Skipping the settings write would leave the machine with no token, no base
    URL and no marketplaces while the command reported success.
    """
    (tmp_path / "site").mkdir()
    with pytest.raises(LmiError) as exc:
        template.load(tmp_path / "site" / "lmi.json")
    assert exc.value.code == 2
    message = str(exc.value)
    assert str(tmp_path / "site" / "settings.json") in message


def test_a_directory_where_the_template_should_be_is_a_usage_error(tmp_path):
    (tmp_path / "site" / "settings.json").mkdir(parents=True)
    with pytest.raises(LmiError) as exc:
        template.load(tmp_path / "site" / "lmi.json")
    assert exc.value.code == 2


def test_a_utf8_bom_is_tolerated(tmp_path):
    """Notepad and PowerShell's Set-Content both write one."""
    path = tmp_path / "settings.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'{"theme": "dark"}')
    assert template.load(tmp_path / "lmi.json")[0] == {"theme": "dark"}


def test_a_non_utf8_payload_is_refused_by_name(tmp_path):
    """ANSI carries no mark, so it arrives here as undecodable bytes."""
    path = tmp_path / "settings.json"
    path.write_bytes(b'{"theme": "d\xe4rk"}')
    with pytest.raises(LmiError) as exc:
        template.load(tmp_path / "lmi.json")
    assert exc.value.code == 2
    assert "UTF-8" in str(exc.value)


def test_invalid_json_names_the_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"env": }', encoding="utf-8")
    with pytest.raises(LmiError) as exc:
        template.load(tmp_path / "lmi.json")
    assert exc.value.code == 2
    assert "settings.json" in str(exc.value)


@pytest.mark.parametrize("doc", [[1, 2], "text", 5])
def test_a_non_object_top_level_is_rejected(tmp_path, doc):
    write(tmp_path / "settings.json", doc)
    with pytest.raises(LmiError) as exc:
        template.load(tmp_path / "lmi.json")
    assert exc.value.code == 2


def test_a_non_string_env_value_is_rejected(tmp_path):
    """MANDATORY. Silent failure: the 256K profile does not apply.

    Claude Code types settings.json env as string-to-string. A JSON number
    writes cleanly, parses cleanly, and the setting does nothing. This is the
    rule that used to guard "claude.env" in lmi.json, one file over.
    """
    write(tmp_path / "settings.json",
          {"env": {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": 256000}})
    with pytest.raises(LmiError) as exc:
        template.load(tmp_path / "lmi.json")
    assert exc.value.code == 2
    assert "string" in str(exc.value)


def test_a_non_object_env_is_rejected(tmp_path):
    write(tmp_path / "settings.json", {"env": ["not", "a", "map"]})
    with pytest.raises(LmiError) as exc:
        template.load(tmp_path / "lmi.json")
    assert exc.value.code == 2


def test_a_null_env_is_rejected(tmp_path):
    """MANDATORY. Silent failure: the token written into a discarded block.

    `null` is a value, not an absence. A doc.get("env") is None guard cannot
    tell this from a template that never mentioned env, so it waves it through
    while rejecting "env": [] and "env": "x" beside it - and compose would then
    have to invent an env block over the top of a key the operator explicitly
    nulled, or write the token nowhere at all.
    """
    write(tmp_path / "settings.json", {"env": None})
    with pytest.raises(LmiError) as exc:
        template.load(tmp_path / "lmi.json")
    assert exc.value.code == 2
    assert "env" in str(exc.value)


def test_a_template_with_no_env_block_is_accepted(tmp_path):
    """compose adds one. A site with nothing but a token needs no env key."""
    write(tmp_path / "settings.json", {"theme": "dark"})
    assert template.load(tmp_path / "lmi.json")[0] == {"theme": "dark"}


def test_an_empty_object_is_accepted(tmp_path):
    write(tmp_path / "settings.json", {})
    assert template.load(tmp_path / "lmi.json")[0] == {}


def test_unknown_keys_pass_through_untouched(tmp_path):
    """lmi does not model Claude Code's schema; it reports typos better.

    This is the whole point of the template: a setting Anthropic adds tomorrow
    works today, without lmi learning it first.
    """
    exotic = {"somethingAddedIn2027": {"nested": [1, {"a": 2}]}, "model": None}
    write(tmp_path / "settings.json", exotic)
    assert template.load(tmp_path / "lmi.json")[0] == exotic
