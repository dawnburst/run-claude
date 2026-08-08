"""Discovery and validation of the lmi install config file."""

import json

import pytest

from lmi.commands.install import config
from lmi.core.errors import LmiError


class Args:
    """argparse.Namespace stand-in: only the two attributes build_config reads."""

    def __init__(self, config=None, target="claude"):
        self.config = config
        self.target = target


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    return path


MINIMAL = {"claude": {"registry": "https://artifactory.corp.local/api/npm/npm/"}}


def test_explicit_config_wins(tmp_path, monkeypatch):
    chosen = write(tmp_path / "chosen.json", MINIMAL)
    write(tmp_path / "lmi.json", {"claude": {"registry": "https://wrong/"}})
    monkeypatch.chdir(tmp_path)
    cfg = config.build_config(Args(config=str(chosen)))
    assert cfg.registry == "https://artifactory.corp.local/api/npm/npm/"
    assert cfg.source == chosen


def test_missing_explicit_config_does_not_fall_through(tmp_path, monkeypatch):
    """MANDATORY. Silent failure: provisioning against the wrong registry.

    A --config the user named and that does not exist must be an error, never
    a quiet fall-through to ./lmi.json - which would install from a different
    registry than the one asked for and report success.
    """
    write(tmp_path / "lmi.json", MINIMAL)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(tmp_path / "nope.json")))
    assert exc.value.code == 2


def test_env_var_beats_cwd(tmp_path, monkeypatch):
    from_env = write(tmp_path / "env.json", MINIMAL)
    write(tmp_path / "lmi.json", {"claude": {"registry": "https://wrong/"}})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LMI_CONFIG", str(from_env))
    assert config.build_config(Args()).source == from_env


def test_cwd_beats_home(tmp_path, monkeypatch):
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    write(tmp_path / "home" / ".lmi" / "config.json",
          {"claude": {"registry": "https://wrong/"}})
    here = write(tmp_path / "work" / "lmi.json", MINIMAL)
    monkeypatch.chdir(tmp_path / "work")
    assert config.build_config(Args()).source == here


def test_home_is_the_last_resort(tmp_path, monkeypatch):
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    fallback = write(tmp_path / "home" / ".lmi" / "config.json", MINIMAL)
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    assert config.build_config(Args()).source == fallback


def test_no_config_anywhere_is_usage_with_an_example(tmp_path, monkeypatch):
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    with pytest.raises(LmiError) as exc:
        config.build_config(Args())
    assert exc.value.code == 2
    message = str(exc.value)
    assert "registry" in message          # the paste-ready example
    assert "lmi.json" in message          # the paths searched


@pytest.mark.parametrize("doc", [
    [1, 2, 3],                                        # top level not an object
    {},                                               # no "claude"
    {"claude": "nope"},                               # "claude" not an object
    {"claude": {}},                                   # no registry
    {"claude": {"registry": ""}},                     # empty registry
    {"claude": {"registry": 5}},                      # registry not a string
    {"claude": {"registry": "u", "marketplaces": []}},
    {"claude": {"registry": "u", "env": []}},
])
def test_rejected_shapes_are_usage_errors(tmp_path, monkeypatch, doc):
    path = write(tmp_path / "lmi.json", doc)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2


def test_invalid_json_names_the_file_and_the_position(tmp_path, monkeypatch):
    path = tmp_path / "lmi.json"
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        fh.write('{"claude": }')
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert "lmi.json" in str(exc.value)


def test_a_utf8_bom_is_tolerated(tmp_path):
    """Notepad and PowerShell's Set-Content both write one; json.loads rejects it."""
    path = tmp_path / "lmi.json"
    with open(str(path), "wb") as fh:
        fh.write(b"\xef\xbb\xbf" + json.dumps(MINIMAL).encode("utf-8"))
    assert config.build_config(Args(config=str(path))).registry.startswith("https://")


def test_non_string_env_value_is_rejected(tmp_path):
    """MANDATORY. Silent failure: the 256K profile does not apply.

    Claude Code types settings.json `env` as a map of string to string. A JSON
    number writes cleanly, parses cleanly, and the setting does nothing.
    """
    path = write(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/",
        "env": {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": 256000},
    }})
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2
    assert "string" in str(exc.value)


def test_the_256k_profile_is_the_default():
    assert config.DEFAULT_ENV == {
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000",
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "204800",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000",
    }


def test_config_env_overrides_one_key_and_keeps_the_others(tmp_path):
    path = write(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/",
        "env": {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "32000",
                "ANTHROPIC_BASE_URL": "https://gw.corp/"},
    }})
    env = config.build_config(Args(config=str(path))).env
    assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "32000"
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "256000"
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "204800"
    assert env["ANTHROPIC_BASE_URL"] == "https://gw.corp/"


def test_default_env_is_not_mutated_by_a_config(tmp_path):
    """A shared module-level dict updated in place would leak between runs."""
    path = write(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/", "env": {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "1"}}})
    config.build_config(Args(config=str(path)))
    assert config.DEFAULT_ENV["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "64000"


def test_cafile_must_exist(tmp_path):
    path = write(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/", "cafile": str(tmp_path / "absent.pem")}})
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config=str(path)))
    assert exc.value.code == 2


def test_cafile_that_exists_is_resolved(tmp_path):
    pem = tmp_path / "ca.pem"
    pem.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    path = write(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/", "cafile": str(pem)}})
    assert config.build_config(Args(config=str(path))).cafile == pem


def test_tilde_user_that_cannot_resolve_is_usage_not_a_traceback():
    with pytest.raises(LmiError) as exc:
        config.build_config(Args(config="~nosuchuser-lmi/lmi.json"))
    assert exc.value.code == 2


def test_marketplaces_pass_through_unaltered(tmp_path):
    markets = {"corp": {"source": {"source": "git", "url": "https://g/c.git"},
                        "whateverUpstreamAddsNext": True}}
    path = write(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/", "marketplaces": markets}})
    assert config.build_config(Args(config=str(path))).marketplaces == markets
