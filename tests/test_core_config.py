"""What the promotion out of lmi/commands/install/ added.

Behaviour that existed before the move is pinned by
tests/commands/install/test_config.py, which drives all of it through
install's build_config and must keep passing unchanged. What is new here is
that the purpose sentence, the section name and the example are the caller's,
so two commands can share one file without either one's error message
mentioning the other.
"""

import json

import pytest

from lmi.core import config
from lmi.core.errors import LmiError

EXAMPLE = '{\n  "widget": {\n    "size": 3\n  }\n}'


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    return path


def test_the_purpose_sentence_is_the_callers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.delenv(config.CONFIG_ENV_VAR, raising=False)

    with pytest.raises(LmiError) as exc:
        config.find(None, "`lmi widget` needs one to know the size.", EXAMPLE)
    assert exc.value.code == 2
    assert "`lmi widget` needs one to know the size." in str(exc.value)
    assert "lmi install" not in str(exc.value)
    assert "widget" in str(exc.value)          # the example is printed too


def test_a_missing_section_names_the_section_asked_for(tmp_path):
    path = write(tmp_path / "lmi.json", {"claude": {}})
    with pytest.raises(LmiError) as exc:
        config.section(config.load(path), "lmi", path, EXAMPLE)
    assert exc.value.code == 2
    assert '"lmi" section' in str(exc.value)


def test_a_section_that_is_not_an_object_names_it_too(tmp_path):
    path = write(tmp_path / "lmi.json", {"lmi": "nope"})
    with pytest.raises(LmiError) as exc:
        config.section(config.load(path), "lmi", path, EXAMPLE)
    assert exc.value.code == 2
    assert '"lmi" section must be a JSON object' in str(exc.value)


def test_a_present_section_is_returned(tmp_path):
    path = write(tmp_path / "lmi.json", {"lmi": {"index": "https://x/"}})
    got = config.section(config.load(path), "lmi", path, EXAMPLE)
    assert got == {"index": "https://x/"}


def test_two_sections_live_in_one_file(tmp_path):
    """The whole point of the promotion: one file, two commands."""
    path = write(tmp_path / "lmi.json",
                 {"lmi": {"index": "https://i/"}, "claude": {"registry": "https://r/"}})
    doc = config.load(path)
    assert config.section(doc, "lmi", path, EXAMPLE)["index"] == "https://i/"
    assert config.section(doc, "claude", path, EXAMPLE)["registry"] == "https://r/"
