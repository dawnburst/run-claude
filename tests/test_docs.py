"""Documentation facts that go stale silently.

The example config is the thing users copy. If it drifts from what the
validator accepts, every new site starts with a broken file and a usage error.
"""

import json
from pathlib import Path

import pytest

from lmi.commands.install import claude_json, config, gitbash, settings
from lmi.commands.upgrade import config as upgrade_config
from lmi.core.errors import LmiError

REPO = Path(__file__).resolve().parent.parent


class Args:
    version = None

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


def test_the_shipped_default_config_is_accepted_by_the_validator():
    """config/lmi.json is what `lmi install claude` reads from a checkout.

    Unlike examples/lmi.json it is not copied and edited first, so a shape the
    validator rejects is not a bad first day - it is the command failing where
    it is supposed to work. It deliberately omits `cafile`: that key is checked
    to exist, so a placeholder path would be exit 2 on every machine.
    """
    shipped = REPO / config.CWD_CONFIG_DIR / config.CWD_CONFIG_NAME
    assert shipped.is_file(), "%s must exist" % config.CWD_CONFIG
    cfg = config.build_config(Args(str(shipped)))
    assert cfg.registry
    assert "cafile" not in json.loads(shipped.read_text(encoding="utf-8"))["claude"]


def test_the_shipped_default_config_is_rejected_by_the_upgrade_validator():
    """The mirror image of the test above, and load-bearing in the other
    direction: config/lmi.json must NOT carry an "lmi" section, because lmi is
    never published anywhere and a live index there could only ever resolve a
    stranger's package of that name. If someone re-adds one - even a
    placeholder - this catches it before it ships, rather than a checkout
    quietly starting to point `lmi upgrade` at public PyPI.
    """
    shipped = REPO / config.CWD_CONFIG_DIR / config.CWD_CONFIG_NAME
    assert "lmi" not in json.loads(shipped.read_text(encoding="utf-8"))
    with pytest.raises(LmiError) as exc:
        upgrade_config.build_config(Args(str(shipped)))
    assert exc.value.code == 2
    assert '"lmi"' in str(exc.value)


def test_the_readme_names_the_working_directory_default():
    """The search order is the first thing an operator reads and the easiest to
    leave stale: it moved from ./lmi.json into ./config/ once already."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert config.CWD_CONFIG in readme


def test_the_example_switch_fragment_is_accepted(tmp_path):
    """It is copied and edited, so a rejected shape is a broken starting point."""
    from lmi.commands.config import fragment
    src = REPO / "examples" / "settings_switch.json"
    staged = tmp_path / "f.json"
    staged.write_bytes(src.read_bytes())
    doc, _ = fragment.load(str(staged))
    assert doc


def test_the_readme_documents_config_switch():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for needle in ("lmi config switch", "settings.json.lmi-origin",
                   "config/settings_switch.json"):
        assert needle in readme, "README.md must document %s" % needle


def test_claude_md_records_the_write_once_snapshot():
    """MANDATORY. The rule is one line of code and invisible when inverted.

    If CLAUDE.md does not carry it, the next person to touch origin.capture has
    nothing telling them why the `if not exists()` is there.
    """
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert "lmi-origin" in text
    start = text.index("lmi-origin")
    window = text[max(0, start - 800):start + 800]
    assert "once" in window or "only if" in window


def test_claude_md_scopes_the_keypress_invariant_to_schedule():
    """MANDATORY. Invariant 3 was global and `lmi install` contradicts it.

    Left unscoped it reads as a rule this command breaks, which invites someone
    to "fix" the command by removing its prompts.
    """
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    start = text.index("Nothing may ever wait for a keypress")
    assert "schedule" in text[start - 400:start + 400]


def test_the_example_documents_every_upgrade_key():
    doc = json.loads((REPO / "examples" / "lmi.json").read_text(encoding="utf-8"))
    assert set(doc["lmi"]) == {"index", "cafile"}


def test_the_printed_upgrade_example_matches_the_shipped_one():
    """upgrade's EXAMPLE is pasted by an operator whose command just failed.

    Pinned against its own section rather than the whole document, so the two
    commands can each document their own keys without either one having to know
    about the other.
    """
    printed = json.loads(upgrade_config.EXAMPLE)
    shipped = json.loads((REPO / "examples" / "lmi.json").read_text(
        encoding="utf-8"))
    assert set(printed["lmi"]) == set(shipped["lmi"])


def test_the_example_config_is_accepted_by_the_upgrade_validator(tmp_path):
    example = REPO / "examples" / "lmi.json"
    doc = json.loads(example.read_text(encoding="utf-8"))
    pem = tmp_path / "ca.pem"
    pem.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    doc["lmi"]["cafile"] = str(pem)
    staged = tmp_path / "lmi.json"
    with open(str(staged), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)

    cfg = upgrade_config.build_config(Args(str(staged)))
    assert cfg.index
    assert cfg.cafile == pem
