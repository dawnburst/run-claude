"""Documentation facts that go stale silently.

The example config is the thing users copy. If it drifts from what the
validator accepts, every new site starts with a broken file and a usage error.
"""

import json
from pathlib import Path

from lmi.commands.install import claude_json, config, gitbash, settings

REPO = Path(__file__).resolve().parent.parent


class Args:
    def __init__(self, config, target="claude"):
        self.config = config
        self.target = target


def test_the_example_config_is_accepted_by_the_validator(tmp_path):
    example = REPO / "examples" / "lmi.json"
    doc = json.loads(example.read_text(encoding="utf-8"))
    # cafile has to point somewhere real for validation, so rewrite just that.
    pem = tmp_path / "ca.pem"
    pem.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    doc["claude"]["cafile"] = str(pem)
    staged = tmp_path / "lmi.json"
    with open(str(staged), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)

    cfg = config.build_config(Args(str(staged)))
    assert cfg.registry
    assert cfg.marketplaces


def test_the_example_documents_every_supported_key():
    doc = json.loads((REPO / "examples" / "lmi.json").read_text(encoding="utf-8"))
    assert set(doc["claude"]) == {"registry", "cafile", "marketplaces", "env"}


def test_the_printed_example_matches_the_shipped_one():
    """config.EXAMPLE is what an operator pastes when the command has failed.

    It is printed by _nothing_found and by the missing-"claude"-section error,
    with nothing else on screen to copy from, and it had no test at all while
    examples/lmi.json had one - which is how it came to omit `env`, the key the
    256K profile rests on. Key sets, not bytes: the URLs differ deliberately.
    """
    printed = json.loads(config.EXAMPLE)
    shipped = json.loads((REPO / "examples" / "lmi.json").read_text(
        encoding="utf-8"))
    assert set(printed["claude"]) == set(shipped["claude"])


def test_the_readme_names_the_silent_keys():
    """Anyone editing these by hand needs the exact spelling in front of them."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for key in (claude_json.ONBOARDING_KEY, settings.MARKETPLACES_KEY,
                gitbash.VAR, "lmi install claude"):
        assert key in readme, "README.md must document %s" % key


def test_claude_md_scopes_the_keypress_invariant_to_schedule():
    """MANDATORY. Invariant 3 was global and `lmi install` contradicts it.

    Left unscoped it reads as a rule this command breaks, which invites someone
    to "fix" the command by removing its prompts.
    """
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    start = text.index("Nothing may ever wait for a keypress")
    assert "schedule" in text[start - 400:start + 400]
