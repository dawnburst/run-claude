"""Documentation facts that go stale silently.

The example config is the thing users copy. If it drifts from what the
validator accepts, every new site starts with a broken file and a usage error.

The `test_the_readme_*` names are kept from when the user documentation was a
single README.md; they read `user_docs()` below, which is the whole set. The
names stay because the design specs under docs/superpowers/ cite several of
them by name, and a rename would leave those citations pointing at nothing -
the same reason CLAUDE.md's numbered items are appended to and never
renumbered.
"""

import json
from pathlib import Path

import pytest

from lmi.commands.install import (
    claude_json, config, defaults, gitbash, settings, statusline, template,
)
from lmi.commands.config import catalog
from lmi.commands.upgrade import config as upgrade_config
from lmi.core.errors import LmiError

REPO = Path(__file__).resolve().parent.parent

# The user documentation was one file and is now several: a front page and one
# reference per command. These tests pin *facts*, not filenames - a fact may
# move between these files as the documentation is reorganised, and what they
# refuse is a fact leaving them altogether.
#
# The list is explicit rather than a glob over docs/, for the same reason
# commands/__init__.py registers commands by hand: a glob would quietly admit
# docs/superpowers/, where the design specs already spell most of these needles
# out. Every test below would then pass while the user documentation said
# nothing at all - which is this module's own silent failure.
USER_DOCS = (
    "README.md",
    "docs/schedule.md",
    "docs/install-claude.md",
    "docs/config.md",
    "docs/upgrade.md",
    "docs/status.md",
    "docs/install/linux.md",
    "docs/install/macos.md",
    "docs/install/windows-cmd.md",
    "docs/install/windows-powershell.md",
)


def user_docs():
    """Every document a user is pointed at, as one string.

    A missing file raises here rather than shrinking what the tests can see,
    which is the loud half of the same rule.
    """
    return "\n\n".join((REPO / name).read_text(encoding="utf-8")
                        for name in USER_DOCS)


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
    assert set(doc["claude"]) == {"registry", "index", "cafile", "strict-ssl"}


def test_the_example_documents_the_schedule_backend(tmp_path):
    """The example is what a new site copies, so it documents the switch on
    day one - both that the key exists and that the value it carries is one
    the parser accepts. Two assertions rather than one: a `schedule` section
    that build_config tolerates but backend.parse refuses would be a file
    every new site starts broken with, and neither validator alone catches it.
    """
    from lmi.commands.schedule import backend
    doc = json.loads((REPO / "examples" / "lmi.json").read_text(encoding="utf-8"))
    assert set(doc["schedule"]) == {"mode"}
    mode, source = backend.of_document(doc, REPO / "examples" / "lmi.json")
    assert mode in backend.MODES
    assert source != backend.DEFAULT_SOURCE, \
        "the example must name a mode explicitly, not fall back to the default"


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

@pytest.mark.parametrize("where", ["examples"])
def test_the_shipped_settings_templates_are_accepted(tmp_path, where):
    """Both are copied and edited, so a rejected shape is a broken first day.

    Only examples/ is parametrised now. The checkout's config/ folder is gone -
    the packaged default-config/ is the one default that ships - and its own
    template is covered by test_defaults.py against defaults.TEMPLATE, which is
    the file that actually reaches a machine.
    """
    src = REPO / where / template.NAME
    assert src.is_file(), "%s/%s must exist" % (where, template.NAME)
    (tmp_path / template.NAME).write_bytes(src.read_bytes())
    doc, _ = template.load(tmp_path / "lmi.json")
    assert doc


@pytest.mark.parametrize("where", ["examples"])
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
    docs = user_docs()
    for needle in ("config/settings.json", "ANTHROPIC_AUTH_TOKEN"):
        assert needle in docs, "the user documentation must document %s" % needle


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
    docs = user_docs()
    for key in (claude_json.ONBOARDING_KEY, settings.MARKETPLACES_KEY,
                gitbash.VAR, "lmi install claude"):
        assert key in docs, "the user documentation must document %s" % key


def test_the_shipped_default_config_is_accepted_by_the_validator():
    """default-config/lmi.json is the only default that ships.

    It used to be the checkout's config/lmi.json; that folder is gone, and this
    is the file that reaches a machine with nothing else on it - the easy path
    failing where it is supposed to be easiest. Unlike examples/lmi.json it is
    not copied and edited first. It deliberately omits `cafile`: that key is
    checked to exist, so a placeholder path would be exit 2 on every machine.
    """
    shipped = defaults.CONFIG
    assert shipped.is_file(), "%s must exist" % shipped
    cfg = config.build_config(Args(str(shipped)))
    assert cfg.registry
    assert cfg.settings, "and the template beside it, which build_config loads"
    assert "cafile" not in json.loads(shipped.read_text(encoding="utf-8"))["claude"]


def test_the_packaged_config_folder_carries_the_statusline_it_declares():
    """MANDATORY. Silent failure: an install that provisions half a statusline.

    One folder ships now - lmi/commands/install/default-config/ - and a
    statusline is two files in it: the `statusLine` block in settings.json and
    the script its command runs. Either half alone reports success and shows no
    statusline: a command pointing at a file nothing writes, or a script in
    ~/.claude that nothing runs. It is a [WARN] at run time rather than an
    error, deliberately, which is exactly why the shipped pair needs pinning
    somewhere that fails.

    This replaces two earlier tests - one for the checkout's config/ folder,
    which no longer exists, and one asserting the packaged folder declared
    NO statusline, which was true only while it shipped no script. The rule
    they both served is unchanged: the halves must agree.
    """
    doc = json.loads(defaults.TEMPLATE.read_text(encoding="utf-8"))
    assert statusline.declares(doc), \
        "the packaged settings.json is expected to declare a statusline"
    assert statusline.find(defaults.CONFIG) is not None, \
        "%s must exist beside it" % statusline.NAME


def test_the_readme_documents_the_packaged_default():
    """The search order gained a fifth entry, and it is the easiest to leave
    stale: it is the one no operator can see in their own filesystem."""
    docs = user_docs()
    for needle in (defaults.DIR_NAME, "packaged default"):
        assert needle in docs, "the user documentation must document %s" % needle


def test_the_readme_documents_the_statusline_script():
    """Both halves, by name: the file to write and the key that runs it."""
    docs = user_docs()
    for needle in (statusline.NAME, statusline.SETTINGS_KEY,
                   "config/statusline.js"):
        assert needle in docs, "the user documentation must document %s" % needle


def test_the_shipped_default_config_is_rejected_by_the_upgrade_validator():
    """The mirror image of the test above, and load-bearing in the other
    direction: default-config/lmi.json must NOT carry an "lmi" section, because lmi is
    never published anywhere and a live index there could only ever resolve a
    stranger's package of that name. If someone re-adds one - even a
    placeholder - this catches it before it ships, rather than a checkout
    quietly starting to point `lmi upgrade` at public PyPI.
    """
    shipped = defaults.CONFIG
    assert "lmi" not in json.loads(shipped.read_text(encoding="utf-8"))
    with pytest.raises(LmiError) as exc:
        upgrade_config.build_config(Args(str(shipped)))
    assert exc.value.code == 2
    assert '"lmi"' in str(exc.value)


def test_the_readme_names_the_working_directory_default():
    """The search order is the first thing an operator reads and the easiest to
    leave stale: it moved from ./lmi.json into ./config/ once already."""
    docs = user_docs()
    assert config.CWD_CONFIG in docs


def test_the_example_switch_fragment_is_accepted(tmp_path):
    """It is copied and edited, so a rejected shape is a broken starting point."""
    from lmi.commands.config import fragment
    src = REPO / "examples" / "settings_switch.json"
    staged = tmp_path / "f.json"
    staged.write_bytes(src.read_bytes())
    doc, _ = fragment.load(str(staged))
    assert doc


def test_every_shipped_switch_file_is_accepted_and_selectable():
    """MANDATORY. A switch that ships and cannot be applied is invisible.

    The packaged folder now carries a gateway/direct pair, which `lmi config
    init` and `defaults.adopt` copy to ~/.lmi like every other file in it. Two
    things can go wrong there and neither is visible at run time: a fragment
    `fragment.read` refuses is a switch file that exits 2 the first time an
    operator tries it, and a name the catalog will not resolve - `origin` above
    all - is a file listed nowhere and appliable by no invocation (item 51).

    Read through catalog.scan rather than by naming the files, so a third
    shipped switch is covered the day it is added rather than the day somebody
    remembers this test.
    """
    from lmi.commands.config import fragment
    names, reserved = catalog.scan(defaults.DIR)
    assert [name for name, _ in names] == ["direct", "gateway"]
    assert reserved == [], \
        "a shipped %s%s%s could never be applied" % (
            catalog.PREFIX, catalog.RESERVED[0], catalog.SUFFIX)
    for _, path in names:
        doc, _ = fragment.read(path)
        assert doc


def test_the_readme_documents_config_init():
    """The command that fills ~/.lmi, and the fact that it never overwrites.

    Both halves matter to an operator: the first is how a deleted folder comes
    back without provisioning Claude Code again, and the second is why running
    it - or re-running an installer script, which runs it - is safe on a folder
    they have spent a year editing.
    """
    docs = user_docs()
    for needle in ("lmi config init", "~/.lmi"):
        assert needle in docs, "the user documentation must document %s" % needle


def test_the_readme_documents_config_switch():
    docs = user_docs()
    for needle in ("lmi config switch", "settings.json.lmi-origin",
                   "config/settings_switch.json"):
        assert needle in docs, "the user documentation must document %s" % needle


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
    docs = user_docs()
    for needle in ("Verbose mode", "-v", "--output-format stream-json"):
        assert needle in docs, "the user documentation must document %s" % needle


def test_the_readme_says_verbose_costs_no_tokens():
    """MANDATORY. The first thing anyone asks about -v is whether a bigger log
    grows the next iteration's context. It does not - the log is written by
    lmi and read back by nothing - but that is not deducible from the flag, so
    the answer has to be written down or it gets asked again."""
    docs = user_docs()
    start = docs.index("### Verbose mode")
    window = docs[start:start + 3000]
    assert "costs no tokens" in window or "no tokens" in window


# --- the two backends -----------------------------------------------------
#
# The README is the user-facing documentation and is accurate; these keep it
# that way for the one part of it a reader cannot check against anything else.
# A backend is invisible in the outcome - both exit 0 on success - so every
# fact about which one is running, and how to change it, exists only here and in
# one log line.

def test_the_readme_documents_the_backend_switch():
    """Everything a reader needs that the outcome of a run cannot tell them."""
    docs = user_docs()
    for needle in ("lmi config schedule",
                   # -f is forwarded in BOTH backends, and the four flags the
                   # SDK cannot forward are refused rather than dropped. Both
                   # halves are documented, because a reader who assumes either
                   # one wrongly loses flags silently.
                   "works in both backends",
                   "--permission-mode",
                   'pip install "lmi[sdk]"',
                   "no fallback between them at run time"):
        assert needle in docs, "the user documentation must document %s" % needle


def test_the_readme_says_sdk_mode_still_runs_a_claude_code_binary():
    """MANDATORY. The one thing a reader will otherwise assume.

    "SDK" reads as "a library instead of the binary", and it is not: the wheels
    bundle a Claude Code binary and spawn it, and where pip serves the source
    distribution instead the SDK looks for `claude` on PATH. Someone who
    believes otherwise concludes the npm half of `lmi install claude` is
    optional in SDK mode - and finds out on a machine that has no `claude`,
    which is the one place the mistake is expensive.
    """
    docs = user_docs()
    assert "SDK mode still runs a Claude Code binary" in docs
    start = docs.index("SDK mode still runs a Claude Code binary")
    window = docs[start:start + 700]
    assert "PATH" in window, "and that the sdist case falls back to PATH"


def test_the_readme_names_the_default_backend_as_the_code_defines_it():
    """The default is the one fact a reader is most likely to assume wrongly,
    and the only one that changes what happens when they configure nothing."""
    from lmi.commands.schedule import backend
    docs = user_docs()
    assert "| `%s` | **The default.**" % backend.DEFAULT in docs, \
        "the Backends table must mark `%s` as the default" % backend.DEFAULT
    for mode in backend.MODES:
        assert "`%s`" % mode in docs


def test_the_readme_says_cli_mode_needs_no_pip_install():
    """The 3.9 floor is the reason the SDK is an extra rather than a dependency,
    and a site running CLI mode needs to know it still holds for them."""
    docs = user_docs()
    start = docs.index("`cli` mode needs no pip install")
    window = docs[start:start + 400]
    assert "3.9" in window and "standard library" in window


def test_the_readme_documents_every_config_key_the_example_prints():
    """Generalised deliberately, so the next key is documented without anybody
    remembering this test exists.

    `claude.index` is what it catches today: a key an operator has to write by
    hand, in a config file, to get the default backend installed at all - and
    the config-file table is where they would look for it.
    """
    docs = user_docs()
    for key in json.loads(config.EXAMPLE)["claude"]:
        assert "`%s`" % key in docs, \
            "the user documentation must document the claude.%s config key" % key


def test_the_readme_and_the_runner_agree_on_the_header_line():
    """Item 33's line, quoted in the README as a sample log header.

    Pinned against the code because it is the only record of which backend ran:
    a reformat that left the README behind would leave a reader grepping their
    logs for a line that is not there, which is exactly when they are trying to
    work out why a run behaved unexpectedly.
    """
    docs = user_docs()
    runner = (REPO / "lmi" / "commands" / "schedule" / "runner.py").read_text(
        encoding="utf-8")
    for needle in ("Backend   : ", "(from "):
        assert needle in docs, "the user documentation must show %r" % needle
        assert needle in runner, "runner.py must write %r" % needle


def test_claude_md_records_that_the_user_settings_source_is_load_bearing():
    """MANDATORY. Item 40, and the sharpest asymmetry between the backends.

    The CLI read ~/.claude/settings.json by virtue of BEING the CLI; the SDK
    loads settings only from the sources it is told to. Omitting the user source
    is **silent**: SDK mode runs against the wrong endpoint with no credentials,
    while `lmi config switch` - whose entire purpose is changing that file -
    quietly stops affecting `lmi schedule` at all. One list literal, no symptom
    lmi can see, so CLAUDE.md has to carry the reason.
    """
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert "setting_sources" in text
    start = text.index("setting_sources")
    window = text[start:start + 900]
    assert "user" in window


def test_the_readme_lists_what_only_a_real_run_can_settle():
    """Task 57. The unverified list is load-bearing documentation here.

    Nothing about the two backends has been exercised against a real SDK, a
    real Artifactory or Windows, and a README that read as though it had would
    be the most expensive kind of stale: every silent failure in this area
    reports success.
    """
    docs = user_docs()
    for needle in ("read-only config file",
                   "pip show claude-agent-sdk",
                   "pip download --no-deps claude-agent-sdk"):
        assert needle in docs, \
            "docs/status.md must name %s" % needle


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


def test_the_readme_documents_keeping_the_existing_token():
    """The prompt grew an answer that does something, so it must be findable.

    A blank at this prompt is refused everywhere except one branch, and the
    only way to discover that branch exists is to re-install on a machine that
    already has a token - or to read this. The masked hint is documented with
    it because an operator who sees `sk-a...9f2c` and cannot find it in the
    README has to guess whether lmi just printed their credential.
    """
    docs = user_docs()
    for needle in ("blank to keep the existing one", "sk-a...9f2c", "****"):
        assert needle in docs, "the user documentation must document %s" % needle


def test_claude_md_records_what_a_blank_token_may_not_mean():
    """MANDATORY. Item 30 is now a refusal WITH an exception, which is the
    shape that rots: the four paths that must keep reaching the refusal are
    invisible in the code - each is simply an early `return None` - and three
    of them produce a settings.json that looks configured. The comparison
    against the run's own template is the load-bearing one and is named here
    because nothing else says why it is not a constant.
    """
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert "_existing_token" in text
    # Anchored on the comparison rather than on the function: `_existing_token`
    # is named twice, and the first mention is item 19's, which is about a
    # different rule entirely.
    assert "token_of(cfg.settings)" in text
    start = text.index("token_of(cfg.settings)")
    window = text[max(0, start - 1500):start + 1500]
    assert "placeholder" in window
    assert "no longer parses" in window or "unparseable" in window
    assert "exit 2" in window


def test_the_readme_documents_the_switch_file_convention():
    """A convention only works if it is written down in one findable place.

    The name is what an operator types and what they must call a file, and
    lmi cannot infer either half from the other: a file named wrongly is simply
    not listed, with nothing to say why.
    """
    docs = user_docs()
    assert catalog.PREFIX + "<name>" + catalog.SUFFIX in docs
    assert "lmi config switch <name>" in docs


def test_the_readme_says_the_reserved_name_cannot_be_selected():
    """MANDATORY. Item 51's silent half - a fragment nothing can ever apply."""
    docs = user_docs()
    for reserved in catalog.RESERVED:
        assert "%s%s%s" % (catalog.PREFIX, reserved, catalog.SUFFIX) in docs
    assert "reserved" in docs


# --- session continuity ----------------------------------------------------

def test_the_user_docs_document_session_continuity():
    docs = user_docs()
    assert "--no-session" in docs
    assert "schedule.session" in docs
    # The sidecar by name: an operator who finds this file beside their state
    # file has to be able to search the documentation for it.
    assert ".session.json" in docs


def test_the_user_docs_say_a_usage_limit_keeps_the_session():
    """The one fact the documentation must not leave out, because it is the
    reason the feature exists rather than a detail of it."""
    docs = user_docs()
    assert "usage limit" in docs
    assert "--resume" in docs


def test_claude_md_still_states_that_a_quota_failure_keeps_the_session():
    """MANDATORY - the same argument as the item-22 check above.

    This rule is one condition in one `if` in runner.py, has no symptom when
    inverted - the run still exits 0 and the log still reads clean - and
    CLAUDE.md is the only file that says why it is there.
    """
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert "A quota failure must not discard the session" in text
