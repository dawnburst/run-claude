"""End-to-end orchestration, with npm and every prompt faked."""

import json
import os
import stat

import pytest

from lmi.commands.install import (defaults, gitbash, prompts, runner, sdk,
                                  settings, statusline)
from lmi.commands.schedule import backend
from lmi.core.errors import LmiError
from tests.conftest import skip_as_root


class Args:
    def __init__(self, config, target="claude"):
        self.config = config
        self.target = target


PLACEHOLDER = "<Token from the user input>"

# What a site's config folder holds beside its lmi.json. Shaped like the shipped
# one: the 256K profile, a marketplace, and the token placeholder that
# _ask_for_token's refusal of a blank answer exists to keep out of ~/.claude.
TEMPLATE = {
    "env": {
        "ANTHROPIC_AUTH_TOKEN": PLACEHOLDER,
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000",
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "204800",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000",
    },
    "extraKnownMarketplaces": {
        "corp": {"source": {"source": "git", "url": "https://g/c.git"}}
    },
    "theme": "dark",
}


def write_json(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh)
    return path


@pytest.fixture
def cfg_file(tmp_path):
    """A config folder: the lmi.json, and the settings.json beside it."""
    write_json(tmp_path / "settings.json", TEMPLATE)
    return write_json(tmp_path / "lmi.json", {"claude": {
        "registry": "https://artifactory.corp.local/api/npm/npm/",
    }})


INDEX = "https://artifactory.corp.local/api/pypi/pypi/simple/"


@pytest.fixture
def cfg_with_index(tmp_path):
    """The same config folder, with a "claude.index" - so the SDK is offered.

    Separate from cfg_file rather than added to it, because an lmi.json with no
    index is not a degenerate case: it is the shape a site that only wants the
    `cli` backend writes, and the older shape every config folder written
    before this feature existed still has.
    """
    write_json(tmp_path / "settings.json", TEMPLATE)
    return write_json(tmp_path / "lmi.json", {"claude": {
        "registry": "https://artifactory.corp.local/api/npm/npm/",
        "index": INDEX,
    }})


def read_mode(cfg_file):
    """`schedule.mode` as it was written into the lmi.json, or None."""
    doc = json.loads(cfg_file.read_text(encoding="utf-8"))
    return doc.get("schedule", {}).get("mode")


@pytest.fixture
def answers(monkeypatch):
    """Script the interactive flow; record what was asked."""
    state = {"confirm": [], "secret": [], "text": [], "asked": []}

    def take(kind, question, *rest):
        state["asked"].append(question)
        queue = state[kind]
        if not queue:
            raise AssertionError("unscripted %s: %r" % (kind, question))
        return queue.pop(0)

    monkeypatch.setattr(prompts, "confirm",
                        lambda q, default=False: take("confirm", q))
    # .strip(), because the real prompts.secret strips: a scripted "  " has to
    # reach the runner the way a spacebar-and-enter answer would.
    monkeypatch.setattr(prompts, "secret", lambda q: take("secret", q).strip())
    monkeypatch.setattr(prompts, "text",
                        lambda q, default=None: take("text", q))
    # Off Windows by default: Git Bash is Windows-only.
    monkeypatch.setattr(gitbash, "on_windows", lambda: False)
    return state


@pytest.fixture
def no_claude(monkeypatch):
    """`claude` is not installed - the fresh-install path."""
    real = runner.shutil.which

    def which(name):
        return None if name == "claude" else real(name)

    monkeypatch.setattr(runner.shutil, "which", which)


@pytest.fixture
def have_claude(monkeypatch):
    """`claude` is already installed - the repair path.

    Only `claude` is answered from here; every other name still goes through the
    real shutil.which, and so through fake_npm's exclusive PATH. Faking which()
    wholesale would resolve `npm` to the machine's own npm, outside that PATH,
    and the suite would run a real `npm config set --global` and a real
    `npm install -g @anthropic-ai/claude-code` against a real registry.
    """
    real = runner.shutil.which

    def which(name):
        return "/usr/bin/claude" if name == "claude" else real(name)

    monkeypatch.setattr(runner.shutil, "which", which)


def read_settings(home):
    path = home / ".claude" / "settings.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_fresh_install_runs_npm_then_writes_both_files(
        fake_npm, home, cfg_file, answers, no_claude, capsys):
    answers["secret"] = ["sk-corp-token"]
    assert runner.run(Args(str(cfg_file))) == 0

    assert fake_npm.calls() == [
        ["config", "set", "registry",
         "https://artifactory.corp.local/api/npm/npm/", "--global"],
        ["install", "-g", "@anthropic-ai/claude-code"],
    ]

    doc = read_settings(home)
    assert doc["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-corp-token"
    assert doc["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "256000"
    assert doc["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "204800"
    assert doc["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "64000"
    assert "corp" in doc["extraKnownMarketplaces"]
    assert doc["theme"] == "dark", "the template is installed whole"
    assert gitbash.VAR not in doc["env"], "Git Bash is Windows-only"

    marker = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    assert marker["hasCompletedOnboarding"] is True


def test_the_placeholder_token_never_reaches_the_settings_file(
        fake_npm, home, cfg_file, answers, no_claude):
    """MANDATORY. Silent failure: every Claude Code call 401s.

    The template ships with a placeholder where the token goes. If it were
    installed verbatim - which is what a blank answer accepted at the prompt
    would produce - ~/.claude/settings.json would look fully configured, the
    install would report success, and the error the user eventually hit would
    point at the gateway rather than at lmi.
    """
    answers["secret"] = ["sk-corp-token"]
    assert runner.run(Args(str(cfg_file))) == 0

    written = (home / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert PLACEHOLDER not in written
    assert "sk-corp-token" in written


def test_a_cafile_replaces_strict_ssl_false(
        tmp_path, fake_npm, home, answers, no_claude):
    pem = tmp_path / "ca.pem"
    pem.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    write_json(tmp_path / "settings.json", TEMPLATE)
    path = write_json(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/", "cafile": str(pem)}})
    answers["secret"] = ["sk-x"]

    assert runner.run(Args(str(path))) == 0
    flat = [" ".join(call) for call in fake_npm.calls()]
    assert any("cafile" in c for c in flat)
    assert not any("strict-ssl" in c for c in flat)


def test_the_packaged_default_installs_with_no_config_file_at_all(
        tmp_path, monkeypatch, fake_npm, sdk_pip, home, answers, no_claude,
        capsys):
    """`pip install lmi`, then `lmi install claude`, with nothing else on disk.

    The whole point of the packaged folder, end to end: no lmi.json, no
    settings.json, no ~/.lmi - and a machine that ends up with Claude Code
    installed, a real settings file, and a config folder of its own to edit.
    """
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.setenv("FAKE_IMPORTABLE", "1")
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    answers["secret"] = ["sk-x"]
    answers["confirm"] = [True]           # the packaged config names an index

    assert runner.run(Args(None)) == 0

    assert ["install", "-g", "@anthropic-ai/claude-code"] in fake_npm.calls()
    assert sdk_pip.calls()[0][-1] == sdk.REQUIREMENT
    doc = read_settings(home)
    assert doc["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-x"
    assert doc["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "256000"

    out = capsys.readouterr().out
    assert "(packaged default)" in out, \
        "the one config nobody chose has to say so before npm runs"


def test_the_packaged_statusline_is_installed_into_the_claude_folder(
        tmp_path, monkeypatch, fake_npm, sdk_pip, home, answers, no_claude,
        capsys):
    """MANDATORY. Both halves of the packaged statusline reach the machine.

    The packaged folder ships a `statusline.js` and a template whose
    `statusLine` command runs it. The script has to arrive at
    ~/.claude/statusline.js, byte for byte, or the command points at nothing
    and item 32's warning fires - on every machine that falls through to the
    default, which is every machine installed from a bare `pip install lmi`.
    Silent: the install reports success and the statusline simply is not there.
    """
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.setenv("FAKE_IMPORTABLE", "1")
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    answers["secret"] = ["sk-x"]
    answers["confirm"] = [True]

    assert runner.run(Args(None)) == 0

    landed = home / ".claude" / statusline.NAME
    assert landed.is_file(), "%s must be installed" % statusline.NAME
    assert landed.read_bytes() == (defaults.DIR / statusline.NAME).read_bytes()
    # And the other half: the template that declares the command that runs it.
    assert statusline.declares(read_settings(home))
    # Item 32's two warnings specifically, not any [WARN]: the fake npm never
    # creates a real `claude`, so "not on PATH" always fires in this harness.
    out = capsys.readouterr().out
    assert "found beside it" not in out, "the script was found, so no warning"
    assert "nothing will run it" not in out, "the template declares it"


def test_the_packaged_default_is_adopted_before_the_mode_is_written(
        tmp_path, monkeypatch, fake_npm, sdk_pip, home, answers, no_claude,
        capsys):
    """MANDATORY. Silent failure: a mode written where nothing reads it.

    `_write_mode` must not write `schedule.mode` into site-packages - `lmi
    schedule` never searches there and the next `pip install --upgrade`
    replaces it, so the machine would keep the default backend for ever with a
    correct-looking file to prove otherwise. The packaged pair is copied to
    ~/.lmi first, and the mode lands in the copy.
    """
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.setenv("FAKE_IMPORTABLE", "1")
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    answers["secret"] = ["sk-x"]
    answers["confirm"] = [True]

    assert runner.run(Args(None)) == 0

    adopted = home / ".lmi" / "config.json"
    assert adopted.is_file()
    assert (home / ".lmi" / "settings.json").is_file()
    assert json.loads(adopted.read_text(encoding="utf-8"))["schedule"]["mode"] \
        == backend.SDK
    packaged = json.loads(defaults.CONFIG.read_text(encoding="utf-8"))
    assert "schedule" not in packaged, "the wheel is not a place to keep state"


def test_the_final_report_names_the_adopted_file_not_the_packaged_one(
        tmp_path, monkeypatch, fake_npm, sdk_pip, home, answers, no_claude,
        capsys):
    """Found by a real run, which is the only place it was visible.

    `_write_mode` wrote to the ~/.lmi copy correctly while `_report` still
    printed cfg.source, so the closing line told the operator their backend had
    been "written to" a file inside site-packages. Not silent - it says the
    wrong thing out loud - but it sends someone to edit a file the next
    `pip install --upgrade` replaces, and the mode they set there would never
    be read.
    """
    monkeypatch.delenv("LMI_CONFIG", raising=False)
    monkeypatch.setenv("FAKE_IMPORTABLE", "1")
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    answers["secret"] = ["sk-x"]
    answers["confirm"] = [True]

    assert runner.run(Args(None)) == 0

    report = capsys.readouterr().out.rsplit("backend:", 1)[-1]
    assert str(home / ".lmi" / "config.json") in report
    assert str(defaults.CONFIG) not in report


def test_neither_tls_key_leaves_npm_alone(
        fake_npm, home, cfg_file, answers, no_claude, capsys):
    """MANDATORY. A config that says nothing about TLS must change nothing.

    `npm config set strict-ssl false` is global and permanent: it covers every
    later `npm install` by that user, for every package. lmi used to run it for
    any config without a "cafile", inferring from the absence of one key that
    verification could not work - true of a private CA, false of every registry
    the machine already trusts, and with a packaged default to fall through to
    it became what a bare `pip install lmi` did to a machine. Not lmi's to
    guess at.
    """
    answers["secret"] = ["sk-x"]
    runner.run(Args(str(cfg_file)))

    flat = [" ".join(call) for call in fake_npm.calls()]
    assert not any("strict-ssl" in c for c in flat)
    # The unrelated "claude is not on PATH" warning is expected here, so match
    # the TLS one by its own wording rather than by [WARN].
    assert "verification is now OFF" not in capsys.readouterr().out


def test_strict_ssl_false_turns_verification_off_and_warns(
        tmp_path, fake_npm, home, answers, no_claude, capsys):
    """Off is still available - it just has to be asked for now."""
    write_json(tmp_path / "settings.json", TEMPLATE)
    cfg = write_json(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/", "strict-ssl": False}})
    answers["secret"] = ["sk-x"]

    assert runner.run(Args(str(cfg))) == 0
    assert ["config", "set", "strict-ssl", "false", "--global"] in fake_npm.calls()
    assert "verification is now OFF" in capsys.readouterr().out


def test_strict_ssl_true_puts_verification_back(
        tmp_path, fake_npm, home, answers, no_claude, capsys):
    """The repair path for a machine an older lmi turned it off on.

    Leaving npm alone is right for a fresh machine and not enough for one
    already carrying `strict-ssl=false` in its npmrc from a previous run -
    there, doing nothing preserves the very setting this change exists to stop
    making.
    """
    write_json(tmp_path / "settings.json", TEMPLATE)
    cfg = write_json(tmp_path / "lmi.json", {"claude": {
        "registry": "https://r/", "strict-ssl": True}})
    answers["secret"] = ["sk-x"]

    assert runner.run(Args(str(cfg))) == 0
    assert ["config", "set", "strict-ssl", "true", "--global"] in fake_npm.calls()
    assert "verification is now OFF" not in capsys.readouterr().out


def test_declining_repair_changes_nothing(
        fake_npm, home, cfg_file, answers, have_claude, capsys):
    """MANDATORY. Silent failure: a machine reconfigured after the user said no.

    "Already installed - repair?" answered no must be a complete no-op: no npm
    command, no settings written, no backup, no onboarding flag. Exit 0, because
    the user answered the question rather than hitting an error.
    """
    answers["confirm"] = [False]

    assert runner.run(Args(str(cfg_file))) == 0
    assert fake_npm.count() == 0
    assert not (home / ".claude" / "settings.json").exists()
    assert not (home / ".claude.json").exists()


def test_accepting_repair_backs_up_and_reports_both_files(
        fake_npm, home, cfg_file, answers, have_claude, capsys):
    (home / ".claude").mkdir()
    with open(str(home / ".claude" / "settings.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"model": "opus[1m]", "theme": "dark"}, fh)
    with open(str(home / ".claude.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"projects": {"/x": {}}}, fh)

    answers["confirm"] = [True]
    answers["secret"] = ["sk-new"]

    assert runner.run(Args(str(cfg_file))) == 0

    backups = sorted(p.name for p in (home / ".claude").iterdir()
                     if ".bk_" in p.name)
    assert len(backups) == 1 and backups[0].startswith("settings.json.bk_")
    assert any(".claude.json.bk_" in p.name for p in home.iterdir())

    out = capsys.readouterr().out
    assert "settings.json.bk_" in out
    assert ".claude.json.bk_" in out

    doc = read_settings(home)
    assert doc == settings.compose(TEMPLATE, "sk-new", None), \
        "the template replaces what was there; it is not merged into it"
    assert "model" not in doc


def test_the_previous_settings_survive_only_in_the_backup(
        fake_npm, home, cfg_file, answers, have_claude):
    """Replacing wholesale makes the backup the sole record of the old file.

    Under the old merge the user's own keys survived in the merged document, so
    a lost backup cost little. It is now the entire safety net, which is why
    jsonfile.backup stays before the write and stays fatal on failure.
    """
    (home / ".claude").mkdir()
    write_json(home / ".claude" / "settings.json", {"model": "opus[1m]"})
    answers["confirm"] = [True]
    answers["secret"] = ["sk-new"]

    assert runner.run(Args(str(cfg_file))) == 0
    backup = next(p for p in (home / ".claude").iterdir() if ".bk_" in p.name)
    assert json.loads(backup.read_text(encoding="utf-8")) == {"model": "opus[1m]"}


def test_an_unparseable_previous_settings_file_is_replaced_not_refused(
        fake_npm, home, cfg_file, answers, have_claude):
    """The narrowed half of CLAUDE.md item 19.

    Hand-corrupted JSON used to be exit 3 with nothing written, because the file
    had to be parsed before it could be merged into. Nothing parses it now, and
    the backup preserves it byte for byte, so the install proceeds. The rule
    stands unchanged for ~/.claude.json, which is still read.
    """
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text('{"env": }', encoding="utf-8")
    answers["confirm"] = [True]
    answers["secret"] = ["sk-new"]

    assert runner.run(Args(str(cfg_file))) == 0
    assert read_settings(home)["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-new"
    backup = next(p for p in (home / ".claude").iterdir() if ".bk_" in p.name)
    assert backup.read_text(encoding="utf-8") == '{"env": }'


def test_a_blank_token_is_re_asked_and_then_refused(
        fake_npm, home, cfg_file, answers, no_claude):
    """MANDATORY. Silent failure: the placeholder token installed verbatim.

    There is nothing for a blank answer to mean any more. The template is
    installed whole, so "keep the one that is there" is not on offer, and the
    only document a blank could produce is one carrying the placeholder. It is
    re-asked first, because a half-pasted token is the common case.
    """
    answers["secret"] = ["", "  ", ""]

    with pytest.raises(LmiError) as exc:
        runner.run(Args(str(cfg_file)))
    assert exc.value.code == 2
    assert not answers["secret"], "every attempt must be used before refusing"
    assert not (home / ".claude" / "settings.json").exists()
    assert fake_npm.count() == 0, "the refusal comes before anything changes"


def test_a_re_typed_token_after_a_blank_one_is_accepted(
        fake_npm, home, cfg_file, answers, no_claude):
    answers["secret"] = ["", "sk-second-try"]

    assert runner.run(Args(str(cfg_file))) == 0
    assert read_settings(home)["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-second-try"


# --- keeping the token a previous install left behind ---------------------

INSTALLED_TOKEN = "sk-existing-corp-token-value"


def install_settings(home, doc):
    """A ~/.claude/settings.json already on the machine, as a re-run finds it."""
    return write_json(home / ".claude" / "settings.json", doc)


def installed_token(token):
    return {"env": {"ANTHROPIC_AUTH_TOKEN": token}, "theme": "light"}


def test_a_blank_answer_keeps_the_token_already_on_the_machine(
        fake_npm, home, cfg_file, answers, no_claude):
    """The second install on a machine should not need the token to hand.

    A blank answer means exactly one thing, and only here: keep the token this
    command can see in the file it is about to replace. Everywhere else - no
    file, no token, an unreadable file, the template's placeholder - blank is
    still refused, because there is nothing to keep.
    """
    install_settings(home, installed_token(INSTALLED_TOKEN))
    answers["secret"] = [""]

    assert runner.run(Args(str(cfg_file))) == 0
    assert read_settings(home)["env"]["ANTHROPIC_AUTH_TOKEN"] == INSTALLED_TOKEN


def test_keeping_a_token_still_installs_the_rest_of_the_template(
        fake_npm, home, cfg_file, answers, no_claude):
    """Keeping the token is not keeping the settings file.

    The template is still installed whole. Only the one value lmi cannot get
    from the template survives the replacement - the previous file's "theme"
    must not, or "keep the token" has quietly become "merge".
    """
    install_settings(home, installed_token(INSTALLED_TOKEN))
    answers["secret"] = [""]

    assert runner.run(Args(str(cfg_file))) == 0
    doc = read_settings(home)
    assert doc["theme"] == "dark", "the template's value, not the old file's"
    assert doc["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "256000"
    assert "corp" in doc["extraKnownMarketplaces"]


def test_the_prompt_offers_to_keep_it_and_shows_only_a_mask(
        fake_npm, home, cfg_file, answers, no_claude, capsys):
    """MANDATORY. Silent failure: a stale credential kept without knowing.

    Enter is offered, so the operator has to be told what Enter will do and
    which token it will keep. The mask is the whole of what may be printed: the
    answer to this question is never echoed either, and a hint that carries the
    credential into terminal scrollback is worse than no hint.
    """
    install_settings(home, installed_token(INSTALLED_TOKEN))
    answers["secret"] = [""]

    assert runner.run(Args(str(cfg_file))) == 0
    asked = " ".join(answers["asked"])
    assert "blank to keep the existing one" in asked
    out = capsys.readouterr().out
    assert "sk-e...alue" in out
    assert INSTALLED_TOKEN not in out


def test_a_typed_token_still_replaces_the_one_on_the_machine(
        fake_npm, home, cfg_file, answers, no_claude):
    install_settings(home, installed_token(INSTALLED_TOKEN))
    answers["secret"] = ["sk-brand-new"]

    assert runner.run(Args(str(cfg_file))) == 0
    assert read_settings(home)["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-brand-new"


def test_the_placeholder_on_the_machine_is_not_a_token_to_keep(
        fake_npm, home, cfg_file, answers, no_claude):
    """MANDATORY. Silent failure: the placeholder installed verbatim.

    The one way "keep the existing one" reopens the failure it was carved out
    of. A settings.json holding the template's own placeholder - copied there
    by hand, or by an lmi old enough to have written it - is not a configured
    machine, and offering to keep it would install a document that looks
    configured and 401s on every call. Blank stays refused here.
    """
    install_settings(home, installed_token(PLACEHOLDER))
    answers["secret"] = ["", "", ""]

    with pytest.raises(LmiError) as exc:
        runner.run(Args(str(cfg_file)))
    assert exc.value.code == 2
    assert not answers["secret"], "every attempt must be used before refusing"
    assert fake_npm.count() == 0, "the refusal comes before anything changes"


def test_an_unreadable_settings_file_offers_nothing_to_keep(
        fake_npm, home, cfg_file, answers, no_claude, capsys):
    """MANDATORY. Silent failure: a blank accepted with nothing behind it.

    Nothing else in this command parses ~/.claude/settings.json, deliberately -
    it is backed up byte for byte and replaced, so a file hand-edited into
    invalid JSON must not block an install that is about to overwrite it. That
    stays true: the read fails, it is said out loud, and the question goes back
    to the one that has no blank answer.
    """
    install_settings(home, installed_token(INSTALLED_TOKEN))
    (home / ".claude" / "settings.json").write_text('{"env": }', encoding="utf-8")
    answers["secret"] = ["", "", ""]

    with pytest.raises(LmiError) as exc:
        runner.run(Args(str(cfg_file)))
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "[WARN]" in out
    assert "blank to keep" not in " ".join(answers["asked"])


def test_the_previous_token_is_kept_but_the_previous_file_is_still_backed_up(
        fake_npm, home, cfg_file, answers, no_claude):
    """Reading the file is not a substitute for preserving it (item 31)."""
    install_settings(home, installed_token(INSTALLED_TOKEN))
    answers["secret"] = [""]

    assert runner.run(Args(str(cfg_file))) == 0
    backup = next(p for p in (home / ".claude").iterdir()
                  if ".bk_" in p.name and p.name.startswith("settings.json"))
    assert json.loads(backup.read_text(encoding="utf-8"))["theme"] == "light"


def test_an_already_onboarded_file_is_not_rewritten(
        fake_npm, home, cfg_file, answers, no_claude):
    with open(str(home / ".claude.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"hasCompletedOnboarding": True, "projects": {}}, fh)
    before = (home / ".claude.json").read_bytes()
    answers["secret"] = ["sk-x"]

    assert runner.run(Args(str(cfg_file))) == 0
    assert (home / ".claude.json").read_bytes() == before
    assert not any(".claude.json.bk_" in p.name for p in home.iterdir()), \
        "no write means no backup"


def test_onboarding_false_is_corrected(
        fake_npm, home, cfg_file, answers, no_claude):
    with open(str(home / ".claude.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"hasCompletedOnboarding": False}, fh)
    answers["secret"] = ["sk-x"]

    assert runner.run(Args(str(cfg_file))) == 0
    doc = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    assert doc["hasCompletedOnboarding"] is True


def test_a_failed_npm_install_touches_no_config_file(
        fake_npm, home, cfg_file, answers, no_claude, monkeypatch):
    """MANDATORY. Silent failure: settings seeded for a claude that is absent.

    If the config steps ran anyway, the machine would look provisioned - the
    256K profile, the marketplaces, onboarding skipped - with no claude binary.

    FAKE_NPM_FAIL_GLOBAL, not FAKE_NPM_RC: do not simplify this back. FAKE_NPM_RC
    fails every npm call, so the run dies at the first `npm config set` and never
    reaches `npm install` - which pins only "no config write before the FIRST npm
    command" and leaves the failure this test is named for untested. Moving the
    two writes to between _configure_npm and npm.install would keep it green.
    Failing only the global-scope calls lets config_set succeed through its
    documented user-level fallback, so the run reaches `npm install -g` and fails
    there, which is the ordering that matters.
    """
    monkeypatch.setenv("FAKE_NPM_FAIL_GLOBAL", "1")
    answers["secret"] = ["sk-x"]

    with pytest.raises(LmiError) as exc:
        runner.run(Args(str(cfg_file)))
    assert exc.value.code == 1
    assert not (home / ".claude" / "settings.json").exists()
    assert not (home / ".claude.json").exists()


def test_every_question_is_asked_before_npm_runs(
        fake_npm, home, cfg_file, answers, have_claude, monkeypatch):
    """A user who abandons the command at a prompt leaves nothing half-done."""
    seen = []
    real_run = runner.npm.install

    def spy(npm_exe, say):
        seen.append(("npm", len(answers["asked"])))
        return real_run(npm_exe, say)

    monkeypatch.setattr(runner.npm, "install", spy)
    answers["confirm"] = [True]
    answers["secret"] = ["sk-x"]

    runner.run(Args(str(cfg_file)))
    assert seen and seen[0][1] == len(answers["asked"]), \
        "no question may be asked after the first npm command"


@skip_as_root
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_a_written_token_forces_mode_600(
        fake_npm, home, cfg_file, answers, no_claude):
    """The 0644 pre-creation is what makes this test discriminating.

    jsonfile.write preserves an existing file's mode and, with nothing to
    preserve, creates the file 0600 anyway. Against a fresh HOME this test
    therefore passes with the `mode=0o600` dropped from _write_settings
    outright - the mode it asserts is then the birth mode, not the mode lmi
    asked for, and a settings.json the user had left at 0644 would keep its
    token world-readable. An existing 0644 file is the only state in which
    those two differ. Identical trap to CLAUDE.md item 20's
    test_the_mode_is_set_before_the_file_becomes_visible; do not drop the chmod.
    """
    (home / ".claude").mkdir()
    path = home / ".claude" / "settings.json"
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"theme": "dark"}, fh)
    os.chmod(str(path), 0o644)

    answers["secret"] = ["sk-secret"]
    runner.run(Args(str(cfg_file)))

    assert read_settings(home)["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-secret"
    assert stat.S_IMODE(os.stat(str(path)).st_mode) == 0o600


def test_a_missing_claude_afterwards_warns_but_exits_0(
        fake_npm, home, cfg_file, answers, no_claude, capsys):
    """PATH in this process cannot see an npmrc prefix change made a second ago.

    Exiting non-zero here would fail runs that in fact succeeded.
    """
    answers["secret"] = ["sk-x"]
    assert runner.run(Args(str(cfg_file))) == 0
    # The specific warning, not just "[WARN]": this config has no cafile, so
    # _configure_npm prints TLS_WARNING, which also starts "[WARN]" and would
    # satisfy a bare check even with _report's branch deleted outright.
    assert runner.NO_CLAUDE_ON_PATH in capsys.readouterr().out


def test_windows_writes_the_git_bash_path_into_settings(
        fake_npm, home, cfg_file, answers, no_claude, monkeypatch, tmp_path):
    bash = tmp_path / "Git" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_text("", encoding="utf-8")
    monkeypatch.setattr(gitbash, "on_windows", lambda: True)
    monkeypatch.setattr(gitbash, "find", lambda: str(bash))
    persisted = []
    monkeypatch.setattr(gitbash, "persist",
                        lambda p, say: persisted.append(p) or True)
    answers["secret"] = ["sk-x"]

    assert runner.run(Args(str(cfg_file))) == 0
    assert read_settings(home)["env"][gitbash.VAR] == str(bash)
    assert persisted == [str(bash)]


def test_windows_without_git_bash_asks_then_warns(
        fake_npm, home, cfg_file, answers, no_claude, monkeypatch, capsys):
    """The ask and the warning, not only the absent key.

    Asserting just that gitbash.VAR is missing from env passes with the whole
    prompt-and-warn block deleted from runner._resolve_git_bash: the `answers`
    fixture raises when a queue is empty, never when one is left undrained, so
    a question that is never asked is silent. A Windows box with Git somewhere
    the seven candidates miss would then never be asked for the path, never be
    warned that the variable is unset, and the run would report success.
    """
    monkeypatch.setattr(gitbash, "on_windows", lambda: True)
    monkeypatch.setattr(gitbash, "find", lambda: None)
    answers["secret"] = ["sk-x"]
    answers["text"] = [""]          # user declines to supply one

    assert runner.run(Args(str(cfg_file))) == 0
    assert any("bash.exe" in q for q in answers["asked"]), \
        "the path question must actually be asked"
    assert not answers["text"], "and the scripted answer consumed"
    assert runner.GIT_BASH_MISSING % gitbash.VAR in capsys.readouterr().out
    assert gitbash.VAR not in read_settings(home).get("env", {})


# --- the statusline script ------------------------------------------------

STATUSLINE = b"#!/usr/bin/env node\nprocess.stdout.write('hi');\n"

STATUSLINE_BLOCK = {"type": "command", "command": "node ~/.claude/statusline.js"}


def with_statusline(cfg_file, script=STATUSLINE, declare=True):
    """Complete the config folder: the script, the block in the template, or both.

    The two halves are written in two different files by hand, so every test
    below is a combination of "is the script there" and "does the template ask
    for one".
    """
    if script is not None:
        with open(str(cfg_file.parent / "statusline.js"), "wb") as fh:
            fh.write(script)
    doc = json.loads(json.dumps(TEMPLATE))
    if declare:
        doc["statusLine"] = STATUSLINE_BLOCK
    write_json(cfg_file.parent / "settings.json", doc)
    return cfg_file


def test_the_statusline_script_is_installed_beside_the_settings(
        fake_npm, home, cfg_file, answers, no_claude):
    """The half a settings.json cannot carry.

    The template's command runs ~/.claude/statusline.js; writing the block and
    not the script it names gives Claude Code a command that is not there.
    """
    with_statusline(cfg_file)
    answers["secret"] = ["sk-x"]

    assert runner.run(Args(str(cfg_file))) == 0

    script = home / ".claude" / "statusline.js"
    assert script.read_bytes() == STATUSLINE
    assert read_settings(home)["statusLine"] == STATUSLINE_BLOCK


def test_a_config_folder_with_no_statusline_installs_as_before(
        fake_npm, home, cfg_file, answers, no_claude, capsys):
    """The script is optional, and an older config folder must not break.

    cfg_file is exactly that folder: an lmi.json and a settings.json, written
    before this feature existed and declaring no statusLine.
    """
    answers["secret"] = ["sk-x"]

    assert runner.run(Args(str(cfg_file))) == 0

    assert not (home / ".claude" / "statusline.js").exists()
    assert read_settings(home)["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-x"
    assert runner.NO_STATUSLINE % "statusline.js" in capsys.readouterr().out


def test_a_declared_statusline_with_no_script_warns(
        fake_npm, home, cfg_file, answers, no_claude, capsys):
    """MANDATORY. Silent failure: half a statusline, and no sign of it.

    The block installs cleanly, the run reports success, and Claude Code runs
    `node ~/.claude/statusline.js` against a file nobody wrote - which shows
    up as no statusline at all, with nothing on screen tying it to the install.
    It is a warning rather than exit 2 because only the operator knows what
    their command actually runs, and refusing would break a site whose
    statusLine runs something else entirely.
    """
    with_statusline(cfg_file, script=None, declare=True)
    answers["secret"] = ["sk-x"]

    assert runner.run(Args(str(cfg_file))) == 0

    assert not (home / ".claude" / "statusline.js").exists()
    out = capsys.readouterr().out
    assert runner.STATUSLINE_MISSING % (
        "statusLine", "statusline.js", cfg_file.parent / "statusline.js") in out


def test_a_script_the_template_never_asks_for_warns(
        fake_npm, home, cfg_file, answers, no_claude, capsys):
    """MANDATORY. Silent failure: the same one from the other side.

    An operator who drops statusline.js into the config folder and forgets the
    block gets a script correctly installed in ~/.claude and no statusline,
    with the install reporting success. It is still copied - the file is where
    it was asked to go - and said out loud.
    """
    with_statusline(cfg_file, declare=False)
    answers["secret"] = ["sk-x"]

    assert runner.run(Args(str(cfg_file))) == 0

    dest = home / ".claude" / "statusline.js"
    assert dest.read_bytes() == STATUSLINE
    assert runner.STATUSLINE_UNUSED % (
        "statusline.js", "statusLine", dest,
        cfg_file.parent / "settings.json",
    ) in capsys.readouterr().out


def test_a_previous_statusline_is_backed_up_and_reported(
        fake_npm, home, cfg_file, answers, have_claude, capsys):
    """It may be one the operator wrote by hand, and it is replaced whole."""
    with_statusline(cfg_file)
    (home / ".claude").mkdir()
    (home / ".claude" / "statusline.js").write_bytes(b"// mine\n")
    answers["confirm"] = [True]
    answers["secret"] = ["sk-x"]

    assert runner.run(Args(str(cfg_file))) == 0

    backup = next(p for p in (home / ".claude").iterdir()
                  if p.name.startswith("statusline.js.bk_"))
    assert backup.read_bytes() == b"// mine\n"
    assert (home / ".claude" / "statusline.js").read_bytes() == STATUSLINE
    assert backup.name in capsys.readouterr().out


def test_the_script_is_written_before_the_settings_that_name_it(
        fake_npm, home, cfg_file, answers, no_claude, monkeypatch):
    """MANDATORY. Silent failure: settings naming a script that is not there.

    If the copy fails, the machine must keep the settings it had rather than
    end up with a fresh settings.json whose statusLine command points at
    nothing. Ordering is the whole guard, so it is asserted directly.
    """
    with_statusline(cfg_file)
    order = []
    real_install = runner.statusline.install
    real_write = runner.jsonfile.write

    def install(*a, **kw):
        order.append("statusline")
        return real_install(*a, **kw)

    def write(path, *a, **kw):
        if path.name == "settings.json":
            order.append("settings")
        return real_write(path, *a, **kw)

    monkeypatch.setattr(runner.statusline, "install", install)
    monkeypatch.setattr(runner.jsonfile, "write", write)
    answers["secret"] = ["sk-x"]

    assert runner.run(Args(str(cfg_file))) == 0
    assert order == ["statusline", "settings"]


def test_a_statusline_copy_failure_leaves_the_settings_alone(
        fake_npm, home, cfg_file, answers, have_claude, monkeypatch):
    """The consequence of the order above, at the exit code."""
    with_statusline(cfg_file)
    (home / ".claude").mkdir()
    write_json(home / ".claude" / "settings.json", {"model": "opus[1m]"})

    def boom(*a, **kw):
        raise LmiError("no", 4)

    monkeypatch.setattr(runner.statusline, "install", boom)
    answers["confirm"] = [True]
    answers["secret"] = ["sk-x"]

    with pytest.raises(LmiError):
        runner.run(Args(str(cfg_file)))
    assert read_settings(home) == {"model": "opus[1m]"}


# --- the SDK, and the backend this machine ends up with -------------------
#
# The whole difficulty of this half is that pip exiting 0 does not mean the
# backend will work, and every test below exists because treating it as if it
# did produces the failure this project keeps paying for: a machine that looks
# provisioned and is not. Nothing in the outcome reveals a wrong mode - both
# backends exit 0 when they work - so the mode written into the lmi.json is
# read back directly in almost every one of them.


def test_the_sdk_is_offered_installed_and_the_mode_written_sdk(
        fake_npm, sdk_pip, home, cfg_with_index, answers, no_claude,
        monkeypatch):
    """MANDATORY. Silent failure: `sdk` written on a machine without the SDK.

    The happy path, and the third of task 22's three cases. It is MANDATORY
    with the other two because the three only mean something together: a check
    that always answered `cli` would pass both failure tests on its own.
    """
    monkeypatch.setenv("FAKE_IMPORTABLE", "1")
    answers["secret"] = ["sk-x"]
    answers["confirm"] = [True]

    assert runner.run(Args(str(cfg_with_index))) == 0

    assert sdk_pip.calls()[0][-1] == sdk.REQUIREMENT
    assert sdk_pip.probes() == ["import %s" % sdk.MODULE]
    assert read_mode(cfg_with_index) == backend.SDK


def test_a_failing_pip_writes_cli_warns_and_still_exits_0(
        fake_npm, sdk_pip, home, cfg_with_index, answers, no_claude,
        monkeypatch, capsys):
    """MANDATORY. Silent failure: a degradation nobody is told about.

    This inverts npm.install's rule deliberately. npm failing means there is no
    Claude Code and the command has failed; pip failing means one of two
    supported backends is unavailable and the other one - the one that drives
    the binary npm just installed - works. So exit 0, mode `cli`, and every
    other document still written. What it must never be is quiet: a silent
    degradation is indistinguishable from success, and nothing afterwards
    reveals which backend the machine got.
    """
    monkeypatch.setenv("FAKE_PIP_FAIL_PACKAGE", sdk.DISTRIBUTION)
    answers["secret"] = ["sk-x"]
    answers["confirm"] = [True]

    assert runner.run(Args(str(cfg_with_index))) == 0

    assert read_mode(cfg_with_index) == backend.CLI
    out = capsys.readouterr().out
    assert runner.SDK_FAILED % (
        backend.CLI, sdk.DISTRIBUTION, INDEX, backend.SDK) in out
    # Everything else still happened: this is a degraded install, not a failed
    # one, and a machine missing its settings would be a different bug wearing
    # this one's exit code.
    assert read_settings(home)["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-x"
    assert json.loads(
        (home / ".claude.json").read_text(encoding="utf-8")
    )["hasCompletedOnboarding"] is True


def test_a_pip_that_exits_0_without_an_importable_package_writes_cli(
        fake_npm, sdk_pip, home, cfg_with_index, answers, no_claude,
        monkeypatch, capsys):
    """MANDATORY. Silent failure: the case pip's exit code cannot see.

    pip can exit 0 having installed into a different interpreter from the one
    that will run `lmi schedule` - which is precisely why the check is an
    import in a subprocess of that interpreter and not `rc == 0`. Gate on the
    exit code instead and this machine is written `sdk`, reports success, and
    every scheduled run afterwards exits 2.
    """
    answers["secret"] = ["sk-x"]
    answers["confirm"] = [True]

    assert runner.run(Args(str(cfg_with_index))) == 0

    assert sdk_pip.count() == 1, "pip ran, and reported success"
    assert read_mode(cfg_with_index) == backend.CLI
    out = capsys.readouterr().out
    assert runner.SDK_NOT_IMPORTABLE % (sdk.MODULE, sdk.DISTRIBUTION) in out


def test_declining_the_sdk_installs_nothing_and_writes_cli(
        fake_npm, sdk_pip, home, cfg_with_index, answers, no_claude, capsys):
    """Declining is a decision about the mode, so it writes one.

    Deliberately unlike declining the repair question, which changes nothing at
    all: there, nothing had been asked for. Here the operator chose a backend,
    and leaving the mode unset would leave the default pointing at the one they
    just declined to install - `lmi schedule` exiting 2 on a machine this
    command reported as provisioned.
    """
    answers["secret"] = ["sk-x"]
    answers["confirm"] = [False]

    assert runner.run(Args(str(cfg_with_index))) == 0

    assert sdk_pip.count() == 0 and sdk_pip.probes() == []
    assert read_mode(cfg_with_index) == backend.CLI
    assert runner.SDK_DECLINED % (backend.CLI, backend.CLI) \
        in capsys.readouterr().out


def test_the_sdk_question_is_asked_before_anything_changes(
        fake_npm, sdk_pip, home, cfg_with_index, answers, no_claude,
        monkeypatch):
    """It belongs in the ask-everything block, with the token and Git Bash."""
    seen = []
    real_install = runner.npm.install

    def spy(npm_exe, say):
        seen.append(len(answers["asked"]))
        return real_install(npm_exe, say)

    monkeypatch.setattr(runner.npm, "install", spy)
    answers["secret"] = ["sk-x"]
    answers["confirm"] = [True]

    runner.run(Args(str(cfg_with_index)))

    assert any("SDK" in q for q in answers["asked"]), \
        "the question must actually be asked"
    assert seen and seen[0] == len(answers["asked"]), \
        "and asked before the first npm command, like every other question"


def test_no_index_means_no_sdk_and_no_question(
        fake_npm, sdk_pip, home, cfg_file, answers, no_claude, capsys):
    """MANDATORY. Silent failure: an unvetted package from public PyPI.

    An absent "claude.index" is an ANSWER, not an omission: it means the SDK is
    not installed and the machine is set to `cli`. Defaulting it to pypi.org
    would be a timeout on an air-gapped machine and, on one with egress, an
    unvetted package from a different source than everything else here - at
    exit 0, defeating the only reason this command exists.

    There is also nothing to ask about, so nothing is asked: the outcome is
    already decided, and a question whose answer changes nothing is worse than
    no question.
    """
    answers["secret"] = ["sk-x"]

    assert runner.run(Args(str(cfg_file))) == 0

    assert sdk_pip.count() == 0 and sdk_pip.probes() == []
    assert not any("SDK" in q for q in answers["asked"])
    assert read_mode(cfg_file) == backend.CLI
    out = capsys.readouterr().out
    assert "pypi.org" not in out
    assert runner.NO_INDEX % (
        cfg_file, backend.CLI, backend.CLI, backend.SDK) in out


def test_a_failed_npm_install_reaches_no_pip(
        fake_npm, sdk_pip, home, cfg_with_index, answers, no_claude,
        monkeypatch):
    """MANDATORY. Silent failure: an SDK on a machine with no Claude Code.

    Item 15's order, extended on the same logic. The SDK drives Claude Code; it
    does not replace it. A machine carrying the Python package and no binary is
    the same "looks provisioned, is not" that keeps the config writes after npm.

    FAKE_NPM_FAIL_GLOBAL rather than FAKE_NPM_RC, for the reason spelled out in
    test_a_failed_npm_install_touches_no_config_file: failing every npm call
    dies at the first `npm config set` and never reaches `npm install` at all.
    """
    monkeypatch.setenv("FAKE_NPM_FAIL_GLOBAL", "1")
    answers["secret"] = ["sk-x"]
    answers["confirm"] = [True]

    with pytest.raises(LmiError) as exc:
        runner.run(Args(str(cfg_with_index)))

    assert exc.value.code == 1
    assert sdk_pip.count() == 0 and sdk_pip.probes() == []
    assert read_mode(cfg_with_index) is None


def test_the_mode_is_written_after_every_claude_config_write(
        fake_npm, sdk_pip, home, cfg_with_index, answers, no_claude,
        monkeypatch):
    """MANDATORY. Silent failure: `sdk` on a machine pip never finished on.

    The key must only ever appear on a machine that got all the way through.
    An earlier failure leaves the lmi.json untouched, which means the default -
    `sdk` - on a machine where the install did not complete: that is
    `lmi schedule`'s loud exit 2 rather than a silently wrong backend, and it
    is the right side to fail on.
    """
    monkeypatch.setenv("FAKE_IMPORTABLE", "1")

    def boom(*a, **kw):
        raise LmiError("settings write failed", 4)

    monkeypatch.setattr(runner.settings, "compose", boom)
    answers["secret"] = ["sk-x"]
    answers["confirm"] = [True]

    with pytest.raises(LmiError):
        runner.run(Args(str(cfg_with_index)))

    assert read_mode(cfg_with_index) is None, \
        "the mode must not outlive the install that was writing it"


def test_the_mode_write_leaves_the_rest_of_the_config_file_alone(
        fake_npm, sdk_pip, home, cfg_with_index, answers, no_claude,
        monkeypatch):
    """The lmi.json carries two other commands' sections.

    It is merged into, never replaced - writing only what this command knows
    about would silently unprovision the machine for `lmi install` itself and
    for `lmi upgrade`.
    """
    monkeypatch.setenv("FAKE_IMPORTABLE", "1")
    doc = json.loads(cfg_with_index.read_text(encoding="utf-8"))
    doc["lmi"] = {"index": "https://artifactory.corp.local/api/pypi/pypi/simple/"}
    write_json(cfg_with_index, doc)
    answers["secret"] = ["sk-x"]
    answers["confirm"] = [True]

    assert runner.run(Args(str(cfg_with_index))) == 0

    after = json.loads(cfg_with_index.read_text(encoding="utf-8"))
    assert after["claude"]["index"] == INDEX
    assert after["lmi"] == doc["lmi"]
    assert after["schedule"] == {"mode": backend.SDK}


def test_the_report_states_the_backend_and_why(
        fake_npm, sdk_pip, home, cfg_with_index, answers, no_claude,
        monkeypatch, capsys):
    """The report is where an operator looks to see what happened.

    By the time the command ends, the line that decided the backend has
    scrolled past a pip install, so it is stated again here - and when it is
    `cli`, why, and the one command that changes it.
    """
    monkeypatch.setenv("FAKE_IMPORTABLE", "1")
    answers["secret"] = ["sk-x"]
    answers["confirm"] = [True]

    runner.run(Args(str(cfg_with_index)))
    out = capsys.readouterr().out
    assert runner.MODE_REPORT % (backend.SDK, cfg_with_index) in out


def test_the_report_explains_a_cli_machine(
        fake_npm, sdk_pip, home, cfg_with_index, answers, no_claude,
        monkeypatch, capsys):
    monkeypatch.setenv("FAKE_PIP_FAIL_PACKAGE", sdk.DISTRIBUTION)
    answers["secret"] = ["sk-x"]
    answers["confirm"] = [True]

    runner.run(Args(str(cfg_with_index)))
    out = capsys.readouterr().out
    assert runner.MODE_REPORT_CLI % (
        backend.CLI, cfg_with_index, backend.CLI, backend.SDK) in out
