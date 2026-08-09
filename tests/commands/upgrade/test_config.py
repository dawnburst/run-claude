"""The `lmi` section of the config file, and this command's arguments."""

import argparse
import json

import pytest

from lmi.commands.upgrade import config
from lmi.core.errors import LmiError

MINIMAL = {"lmi": {"index": "https://artifactory.example.com/api/pypi/x/simple/"}}


class Args:
    def __init__(self, config=None, version=None):
        self.config = config
        self.version = version


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    return path


def test_the_index_is_read(tmp_path):
    path = write(tmp_path / "lmi.json", MINIMAL)
    cfg = config.build_config(Args(config=str(path)))
    assert cfg.index == "https://artifactory.example.com/api/pypi/x/simple/"
    assert cfg.cafile is None
    assert cfg.source == path


@pytest.mark.parametrize("value", [None, "", "   ", 3, [], {}])
def test_a_missing_or_empty_index_is_a_usage_error(tmp_path, value):
    doc = {"lmi": {} if value is None else {"index": value}}
    path = write(tmp_path / "lmi.json", doc)
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert "index" in str(exc.value)


def test_a_file_with_only_a_claude_section_names_the_lmi_one(tmp_path):
    """The two commands share a file; the error must not be about the other."""
    path = write(tmp_path / "lmi.json", {"claude": {"registry": "https://r/"}})
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert '"lmi" section' in str(exc.value)


def test_cafile_must_exist(tmp_path):
    path = write(tmp_path / "lmi.json",
                 {"lmi": {"index": "https://i/", "cafile": str(tmp_path / "no.pem")}})
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert "cafile" in str(exc.value)


def test_cafile_that_exists_is_resolved(tmp_path):
    pem = tmp_path / "ca.pem"
    pem.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    path = write(tmp_path / "lmi.json",
                 {"lmi": {"index": "https://i/", "cafile": str(pem)}})
    assert config.build_config(Args(config=str(path))).cafile == pem


def test_missing_explicit_config_does_not_fall_through(tmp_path):
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(tmp_path / "nope.json")))
    assert exc.value.code == 2
    assert "does not exist" in str(exc.value)


def test_the_purpose_sentence_is_this_commands(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    with pytest.raises(LmiError) as exc:
        config.build_config(Args())
    assert "lmi upgrade" in str(exc.value)
    assert "registry" not in str(exc.value)


def test_the_arguments_parse(tmp_path):
    parser = argparse.ArgumentParser()
    config.add_arguments(parser)
    args = parser.parse_args(["--version", "0.2.0", "--config", "x.json"])
    assert args.version == "0.2.0"
    assert args.config == "x.json"
    assert parser.parse_args([]).version is None
