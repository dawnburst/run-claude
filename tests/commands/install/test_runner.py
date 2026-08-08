"""End-to-end orchestration, with npm and every prompt faked."""

import json
import os
import stat

import pytest

from lmi.commands.install import gitbash, prompts, runner, settings
from lmi.core.errors import LmiError
from tests.conftest import skip_as_root


class Args:
    def __init__(self, config, target="claude"):
        self.config = config
        self.target = target


@pytest.fixture
def cfg_file(tmp_path):
    path = tmp_path / "lmi.json"
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"claude": {
            "registry": "https://artifactory.corp.local/api/npm/npm/",
            "marketplaces": {"corp": {"source": {"source": "git",
                                                 "url": "https://g/c.git"}}},
        }}, fh)
    return path


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
    monkeypatch.setattr(prompts, "secret", lambda q: take("secret", q))
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
        ["config", "set", "strict-ssl", "false", "--global"],
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
    assert gitbash.VAR not in doc["env"], "Git Bash is Windows-only"

    marker = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    assert marker["hasCompletedOnboarding"] is True


def test_a_cafile_replaces_strict_ssl_false(
        tmp_path, fake_npm, home, answers, no_claude):
    pem = tmp_path / "ca.pem"
    pem.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    path = tmp_path / "lmi.json"
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"claude": {"registry": "https://r/", "cafile": str(pem)}}, fh)
    answers["secret"] = [""]

    assert runner.run(Args(str(path))) == 0
    flat = [" ".join(call) for call in fake_npm.calls()]
    assert any("cafile" in c for c in flat)
    assert not any("strict-ssl" in c for c in flat)


def test_no_cafile_warns_about_tls(
        fake_npm, home, cfg_file, answers, no_claude, capsys):
    answers["secret"] = [""]
    runner.run(Args(str(cfg_file)))
    out = capsys.readouterr().out
    assert "[WARN]" in out and "verification" in out


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
    assert doc["model"] == "opus[1m]", "unrelated keys must survive a repair"
    assert doc["theme"] == "dark"


def test_a_blank_token_leaves_an_existing_one_alone(
        fake_npm, home, cfg_file, answers, have_claude):
    (home / ".claude").mkdir()
    with open(str(home / ".claude" / "settings.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"env": {"ANTHROPIC_AUTH_TOKEN": "sk-old"}}, fh)
    answers["confirm"] = [True]
    answers["secret"] = [""]

    assert runner.run(Args(str(cfg_file))) == 0
    assert read_settings(home)["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-old"


def test_an_already_onboarded_file_is_not_rewritten(
        fake_npm, home, cfg_file, answers, no_claude):
    with open(str(home / ".claude.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"hasCompletedOnboarding": True, "projects": {}}, fh)
    before = (home / ".claude.json").read_bytes()
    answers["secret"] = [""]

    assert runner.run(Args(str(cfg_file))) == 0
    assert (home / ".claude.json").read_bytes() == before
    assert not any(".claude.json.bk_" in p.name for p in home.iterdir()), \
        "no write means no backup"


def test_onboarding_false_is_corrected(
        fake_npm, home, cfg_file, answers, no_claude):
    with open(str(home / ".claude.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"hasCompletedOnboarding": False}, fh)
    answers["secret"] = [""]

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
    therefore passes with runner._write_settings' token rule deleted outright -
    the mode it asserts is the birth mode, not the mode the token forced. An
    existing 0644 settings.json is the only state in which those two differ.
    Identical trap to CLAUDE.md item 20's
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
    answers["secret"] = [""]
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
    answers["secret"] = [""]

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
    answers["secret"] = [""]
    answers["text"] = [""]          # user declines to supply one

    assert runner.run(Args(str(cfg_file))) == 0
    assert any("bash.exe" in q for q in answers["asked"]), \
        "the path question must actually be asked"
    assert not answers["text"], "and the scripted answer consumed"
    assert runner.GIT_BASH_MISSING % gitbash.VAR in capsys.readouterr().out
    assert gitbash.VAR not in read_settings(home).get("env", {})
