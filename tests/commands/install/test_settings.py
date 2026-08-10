"""What goes into ~/.claude/settings.json."""

import copy
from pathlib import Path

from lmi.commands.install import gitbash, settings

PLACEHOLDER = "<Token from the user input>"


def test_path_is_under_home(home):
    assert settings.path() == Path(str(home)) / ".claude" / "settings.json"


def test_the_marketplaces_key_is_spelled_exactly():
    """MANDATORY. Silent failure: marketplaces never register.

    Verified against the Claude Code 2.1.222 settings schema. Any other spelling
    writes cleanly, parses cleanly, and is ignored. Nothing merges through this
    constant any more - the operator writes the key by hand in the template -
    which makes the README spelling it correctly matter more, not less. It is
    what tests/test_docs.py pins the README against.
    """
    assert settings.MARKETPLACES_KEY == "extraKnownMarketplaces"


def test_the_token_key_is_spelled_exactly():
    assert settings.TOKEN_KEY == "ANTHROPIC_AUTH_TOKEN"


def test_the_token_lands_in_the_env_block():
    doc = settings.compose({"env": {"ANTHROPIC_BASE_URL": "https://gw/"}},
                           "sk-real", None)
    assert doc["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-real"
    assert doc["env"]["ANTHROPIC_BASE_URL"] == "https://gw/"


def test_the_placeholder_token_is_replaced():
    """MANDATORY. Silent failure: every Claude Code call 401s.

    The shipped and example templates carry a placeholder where the token goes.
    Written through verbatim it looks configured at a glance, the install
    reports success, and the error the user eventually sees points at the
    gateway rather than at lmi.
    """
    doc = settings.compose({"env": {"ANTHROPIC_AUTH_TOKEN": PLACEHOLDER}},
                           "sk-real", None)
    assert doc["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-real"
    assert PLACEHOLDER not in str(doc)


def test_a_template_with_no_env_block_gets_one():
    doc = settings.compose({"theme": "dark"}, "sk-real", None)
    assert doc["env"] == {"ANTHROPIC_AUTH_TOKEN": "sk-real"}
    assert doc["theme"] == "dark"


def test_every_other_key_is_installed_verbatim():
    """The whole point of the template: lmi does not model the schema."""
    template = {
        "autoUpdatesChannel": "latest",
        "extraKnownMarketplaces": {
            "corp": {"source": {"source": "url", "url": "https://g/m.git"}}
        },
        "statusLine": {"type": "command", "command": "node ~/.claude/s.js"},
        "somethingAddedIn2027": [1, {"a": None}],
    }
    doc = settings.compose(template, "sk-real", None)
    for key, value in template.items():
        assert doc[key] == value


def test_the_template_is_not_mutated():
    """The Config owns it, and a frozen dataclass does not freeze a dict."""
    template = {"env": {"ANTHROPIC_AUTH_TOKEN": PLACEHOLDER}}
    before = copy.deepcopy(template)
    settings.compose(template, "sk-real", "C:\\Git\\bin\\bash.exe")
    assert template == before


def test_nested_values_are_copied_not_shared():
    """A shallow copy would let a later edit reach back into the Config."""
    template = {"extraKnownMarketplaces": {"corp": {"source": {"url": "https://g/"}}}}
    doc = settings.compose(template, "sk-real", None)
    doc["extraKnownMarketplaces"]["corp"]["source"]["url"] = "https://changed/"
    assert template["extraKnownMarketplaces"]["corp"]["source"]["url"] == "https://g/"


def test_the_git_bash_path_lands_when_there_is_one():
    doc = settings.compose({}, "sk-real", "C:\\Program Files\\Git\\bin\\bash.exe")
    assert doc["env"][gitbash.VAR] == "C:\\Program Files\\Git\\bin\\bash.exe"


def test_no_git_bash_key_when_there_is_no_path():
    """Off Windows nothing is probed, so the key must not appear at all.

    An empty or null value there is not the same as an absent one: Claude Code
    would read it and fail to run a shell rather than falling back.
    """
    doc = settings.compose({}, "sk-real", None)
    assert gitbash.VAR not in doc["env"]
