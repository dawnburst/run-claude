"""The `lmi` section of the config file, and this command's arguments."""

import argparse
import json

import pytest

from lmi.commands.upgrade import config
from lmi.core.errors import LmiError

MINIMAL = {"lmi": {"index": "https://artifactory.example.com/api/pypi/x/simple/"}}


class Args:
    def __init__(self, config=None, version=None, source=None):
        self.config = config
        self.version = version
        self.source = source


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


@pytest.mark.parametrize("value", ["", "   ", 3, [], {}])
def test_an_empty_or_non_string_index_is_a_usage_error(tmp_path, value):
    """A present-but-wrong index is still an error. Its ABSENCE no longer is -
    a config naming only a repo is a complete config now, which is what
    test_neither_index_nor_repo_is_a_usage_error below covers instead."""
    path = write(tmp_path / "lmi.json", {"lmi": {"index": value}})
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


# --- the repo as a source --------------------------------------------------

REPO = "https://github.com/dawnburst/run-claude.git"


def test_a_repo_alone_is_a_complete_config(tmp_path):
    """A site whose lmi lives in git and nowhere else has no index to name."""
    path = write(tmp_path / "lmi.json", {"lmi": {"repo": REPO}})
    cfg = config.build_config(Args(config=str(path)))
    assert cfg.repo == REPO
    assert cfg.index is None
    assert cfg.source_kind == config.SOURCE_REPO


def test_an_index_alone_still_is(tmp_path):
    path = write(tmp_path / "lmi.json", MINIMAL)
    cfg = config.build_config(Args(config=str(path)))
    assert cfg.repo is None
    assert cfg.source_kind == config.SOURCE_INDEX


def test_neither_index_nor_repo_is_a_usage_error(tmp_path):
    """MANDATORY-adjacent: the message must name BOTH keys. Naming only the one
    this command used to need sends an operator to configure an index they may
    have no way to publish to."""
    path = write(tmp_path / "lmi.json", {"lmi": {}})
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert "index" in str(exc.value) and "repo" in str(exc.value)


def test_the_repo_wins_when_both_are_configured(tmp_path):
    """A rule an operator can state, rather than a precedence they discover. The
    header names it either way, because both sources end in the same
    "Upgraded X -> Y"."""
    path = write(tmp_path / "lmi.json", {"lmi": {"repo": REPO,
                                                 "index": "https://i/simple/"}})
    cfg = config.build_config(Args(config=str(path)))
    assert cfg.source_kind == config.SOURCE_REPO
    # And the index is still read, because a repo install needs it for pip's
    # build dependencies - item 60.
    assert cfg.index == "https://i/simple/"


def test_source_index_overrides_the_repo(tmp_path):
    path = write(tmp_path / "lmi.json", {"lmi": {"repo": REPO,
                                                 "index": "https://i/simple/"}})
    cfg = config.build_config(Args(config=str(path), source=config.SOURCE_INDEX))
    assert cfg.source_kind == config.SOURCE_INDEX


def test_source_repo_without_a_repo_key_is_a_usage_error(tmp_path):
    path = write(tmp_path / "lmi.json", MINIMAL)
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path), source=config.SOURCE_REPO))
    assert exc.value.code == 2
    assert "repo" in str(exc.value)


def test_source_index_without_an_index_key_is_a_usage_error(tmp_path):
    path = write(tmp_path / "lmi.json", {"lmi": {"repo": REPO}})
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path), source=config.SOURCE_INDEX))
    assert exc.value.code == 2
    assert "index" in str(exc.value)


@pytest.mark.parametrize("value", ["", "   ", 3, [], {}])
def test_a_non_string_repo_is_a_usage_error(tmp_path, value):
    path = write(tmp_path / "lmi.json", {"lmi": {"repo": value}})
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert "repo" in str(exc.value)


# --- version_check ---------------------------------------------------------

def test_the_version_check_is_on_when_the_key_is_absent(tmp_path):
    path = write(tmp_path / "lmi.json", {"lmi": {"repo": REPO}})
    assert config.build_config(Args(config=str(path))).version_check is True


@pytest.mark.parametrize("value,expected", [(True, True), (False, False)])
def test_the_version_check_is_read(tmp_path, value, expected):
    path = write(tmp_path / "lmi.json",
                 {"lmi": {"repo": REPO, "version_check": value}})
    assert config.build_config(Args(config=str(path))).version_check is expected


@pytest.mark.parametrize("value", [None, "false", "no", 0, 1, [], {}])
def test_a_non_boolean_version_check_is_a_usage_error(tmp_path, value):
    """The _MISSING sentinel rule in its sixth home: absent means the default,
    and a `null` somebody wrote is refused rather than read as one - it would
    turn the notice back on for a machine that meant to silence it."""
    path = write(tmp_path / "lmi.json",
                 {"lmi": {"repo": REPO, "version_check": value}})
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert "version_check" in str(exc.value)


def test_the_source_argument_parses(tmp_path):
    parser = argparse.ArgumentParser()
    config.add_arguments(parser)
    assert parser.parse_args([]).source is None
    assert parser.parse_args(["--source", "repo"]).source == config.SOURCE_REPO
    assert parser.parse_args(["--source", "index"]).source == config.SOURCE_INDEX


def test_the_example_shows_every_key_this_command_reads(tmp_path):
    """The EXAMPLE is what a first-time operator pastes, with the command having
    just failed and nothing else on screen to copy from."""
    doc = json.loads(config.EXAMPLE)
    assert set(doc["lmi"]) == {"index", "repo", "cafile", "version_check"}
    # And what remains must be a config this command accepts, not merely valid
    # JSON. `cafile` is dropped first because its value is a path that
    # deliberately does not exist - _cafile checks existence up front, so a
    # placeholder CA cannot be part of a loadable example.
    doc["lmi"].pop("cafile")
    path = write(tmp_path / "example.json", doc)
    config.build_config(Args(config=str(path)))
