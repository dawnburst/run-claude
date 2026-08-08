"""What goes into ~/.claude/settings.json."""

from pathlib import Path

from lmi.commands.install import settings


def test_path_is_under_home(home):
    assert settings.path() == Path(str(home)) / ".claude" / "settings.json"


def test_the_marketplaces_key_is_spelled_exactly():
    """MANDATORY. Silent failure: marketplaces never register.

    Verified against the Claude Code 2.1.222 settings schema. Any other spelling
    writes cleanly, parses cleanly, and is ignored.
    """
    assert settings.MARKETPLACES_KEY == "extraKnownMarketplaces"


def test_the_token_key_is_spelled_exactly():
    assert settings.TOKEN_KEY == "ANTHROPIC_AUTH_TOKEN"


def test_unrelated_keys_survive():
    doc = {"model": "opus[1m]", "theme": "dark", "enabledPlugins": {"a": True}}
    merged = settings.merge(doc, {"X": "1"}, {})
    assert merged["model"] == "opus[1m]"
    assert merged["theme"] == "dark"
    assert merged["enabledPlugins"] == {"a": True}


def test_an_unmanaged_env_key_survives():
    doc = {"env": {"SOMETHING_ELSE": "keep me"}}
    merged = settings.merge(doc, {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000"}, {})
    assert merged["env"]["SOMETHING_ELSE"] == "keep me"
    assert merged["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "256000"


def test_a_managed_env_key_is_overwritten_not_duplicated():
    doc = {"env": {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "8000"}}
    merged = settings.merge(doc, {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"}, {})
    assert merged["env"] == {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"}


def test_marketplaces_under_other_names_survive():
    doc = {"extraKnownMarketplaces": {"existing": {"source": {"source": "github",
                                                              "repo": "a/b"}}}}
    merged = settings.merge(doc, {}, {"corp": {"source": {"source": "git",
                                                          "url": "https://g/"}}})
    assert set(merged["extraKnownMarketplaces"]) == {"existing", "corp"}


def test_a_same_named_marketplace_is_replaced():
    doc = {"extraKnownMarketplaces": {"corp": {"source": {"source": "github",
                                                          "repo": "old/old"}}}}
    new = {"corp": {"source": {"source": "git", "url": "https://new/"}}}
    merged = settings.merge(doc, {}, new)
    assert merged["extraKnownMarketplaces"]["corp"] == new["corp"]


def test_marketplaces_are_passed_through_unaltered():
    """lmi does not model source types; upstream may add one tomorrow."""
    exotic = {"m": {"source": {"source": "something-new-in-2027", "x": [1, {"y": 2}]}}}
    merged = settings.merge({}, {}, exotic)
    assert merged["extraKnownMarketplaces"] == exotic


def test_a_corrupt_env_value_of_the_wrong_type_is_replaced_not_merged():
    """If env is somehow a list, merging into it would raise. Replace it."""
    merged = settings.merge({"env": ["not", "a", "dict"]}, {"A": "1"}, {})
    assert merged["env"] == {"A": "1"}


def test_empty_inputs_add_no_keys():
    assert settings.merge({}, {}, {}) == {}


def test_token_of_reads_the_env_block():
    assert settings.token_of({"env": {"ANTHROPIC_AUTH_TOKEN": "sk-x"}}) == "sk-x"


def test_token_of_missing_is_none():
    assert settings.token_of({}) is None
    assert settings.token_of({"env": {}}) is None
    assert settings.token_of({"env": "corrupt"}) is None
