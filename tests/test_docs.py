"""Documentation facts that go stale silently.

The example config is the thing users copy. If it drifts from what the
validator accepts, every new site starts with a broken file and a usage error.
"""

import json
from pathlib import Path

import pytest

from lmi.commands.install import (
    claude_json, config, gitbash, settings, statusline, template,
)
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
    # The template is half of what a site copies, and build_config now loads it.
    (tmp_path / template.NAME).write_bytes(
        (REPO / "examples" / "settings.json").read_bytes())

    cfg = config.build_config(Args(str(staged)))
    assert cfg.registry
    assert cfg.settings


def test_the_example_documents_every_supported_key():
    doc = json.loads((REPO / "examples" / "lmi.json").read_text(encoding="utf-8"))
    assert set(doc["claude"]) == {"registry", "index", "cafile"}


def test_the_example_config_does_not_duplicate_the_template():
    """MANDATORY. Silent failure: a setting written where nothing reads it.

    `marketplaces` and `env` used to live in lmi.json and be copied into
    settings.json. Re-adding either gives an operator somewhere plausible to
    write a setting that lmi no longer reads - it is in the config file, it
    parses, and it never reaches ~/.claude/settings.json.
    """
    doc = json.loads((REPO / "examples" / "lmi.json").read_text(encoding="utf-8"))
    assert "marketplaces" not in doc["claude"]
    assert "env" not in doc["claude"]


# --- the settings.json template -------------------------------------------

@pytest.mark.parametrize("where", ["examples", "config"])
def test_the_shipped_settings_templates_are_accepted(tmp_path, where):
    """Both are copied and edited, so a rejected shape is a broken first day.

    config/settings.json is the stronger case: it is not copied first, so a
    shape the validator rejects is `lmi install claude` failing in a checkout
    where it is supposed to work.
    """
    src = REPO / where / template.NAME
    assert src.is_file(), "%s/%s must exist" % (where, template.NAME)
    (tmp_path / template.NAME).write_bytes(src.read_bytes())
    doc, _ = template.load(tmp_path / "lmi.json")
    assert doc


@pytest.mark.parametrize("where", ["examples", "config"])
def test_no_shipped_template_carries_a_real_looking_token(where):
    """MANDATORY. A committed token is a leaked token.

    The templates are the one place in the repo with an ANTHROPIC_AUTH_TOKEN
    key in it, and they are edited by hand at every site. A placeholder that
    looks like a token is also how one gets installed unnoticed - so the value
    must stay obviously not-a-token.
    """
    doc = json.loads((REPO / where / template.NAME).read_text(encoding="utf-8"))
    value = doc.get("env", {}).get(settings.TOKEN_KEY, "")
    assert value.startswith("<") and value.endswith(">"), \
        "the token placeholder must be an obvious placeholder, not %r" % value


def test_the_readme_documents_the_settings_template():
    """The template is now the whole of what a site configures."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for needle in ("config/settings.json", "ANTHROPIC_AUTH_TOKEN"):
        assert needle in readme, "README.md must document %s" % needle


def test_claude_md_records_that_the_placeholder_must_not_be_installed():
    """MANDATORY. Item 30 is one refusal in one prompt, and inverting it

    produces a settings.json that looks completely configured. Like items 22
    and 27 it exists nowhere but CLAUDE.md: no failing command, no symptom lmi
    can see, and the eventual 401 points at the gateway rather than at here.
    """
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert "placeholder" in text
    start = text.index("placeholder")
    window = text[start - 400:start + 900]
    assert "blank" in window
    assert settings.TOKEN_KEY in window


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
    assert cfg.settings, "and the template beside it, which build_config loads"
    assert "cafile" not in json.loads(shipped.read_text(encoding="utf-8"))["claude"]


def test_the_shipped_config_folder_carries_the_statusline_it_declares():
    """MANDATORY. Silent failure: a checkout that installs half a statusline.

    config/settings.json runs `node ~/.claude/statusline.js`, and the file that
    puts a script there is config/statusline.js beside it. Deleting or moving
    the script - back into scripts/, say, which is not shipped in the wheel -
    leaves an install that reports success and shows no statusline. It is a
    warning at run time rather than an error, deliberately, which is exactly
    why the shipped pair needs pinning here instead.
    """
    folder = REPO / config.CWD_CONFIG_DIR
    doc = json.loads((folder / template.NAME).read_text(encoding="utf-8"))
    assert statusline.declares(doc), \
        "config/settings.json is expected to declare a statusline"
    assert statusline.find(folder / config.CWD_CONFIG_NAME) is not None, \
        "%s must exist beside it" % statusline.NAME


def test_the_readme_documents_the_statusline_script():
    """Both halves, by name: the file to write and the key that runs it."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for needle in (statusline.NAME, statusline.SETTINGS_KEY,
                   "config/statusline.js"):
        assert needle in readme, "README.md must document %s" % needle


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


def test_the_readme_documents_verbose_mode():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for needle in ("Verbose mode", "-v", "--output-format stream-json"):
        assert needle in readme, "README.md must document %s" % needle


def test_the_readme_says_verbose_costs_no_tokens():
    """MANDATORY. The first thing anyone asks about -v is whether a bigger log
    grows the next iteration's context. It does not - the log is written by
    lmi and read back by nothing - but that is not deducible from the flag, so
    the answer has to be written down or it gets asked again."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    start = readme.index("### Verbose mode")
    window = readme[start:start + 3000]
    assert "costs no tokens" in window or "no tokens" in window


def test_claude_md_records_why_the_full_prompt_flag_is_not_an_iteration_number():
    """MANDATORY. Item 27 is one boolean, and inverting it produces a log that
    looks complete. Like item 22 it exists nowhere but CLAUDE.md: no symptom,
    no failing command, and only someone who knows what the header should have
    said would ever notice."""
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert "full_done" in text
    start = text.index("full_done")
    window = text[start:start + 900]
    assert "iteration 1" in window
