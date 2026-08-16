"""Running npm: argv shape, the --global fallback, and failure handling."""

import pytest

from lmi.commands.install import npm
from lmi.core.errors import LmiError


def test_find_returns_the_npm_on_path(fake_npm):
    assert npm.find()


def test_find_without_npm_is_a_usage_error(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    with pytest.raises(LmiError) as exc:
        npm.find()
    assert exc.value.code == 2
    assert "Node" in str(exc.value)


def test_config_set_tries_global_first(fake_npm):
    npm.config_set(npm.find(), "registry", "https://r/", [].append)
    assert fake_npm.calls() == [["config", "set", "registry", "https://r/", "--global"]]


def test_config_set_falls_back_to_user_level(fake_npm, monkeypatch):
    """A root-owned global npmrc is the normal case on a system Node install.

    Dropping --global writes ~/.npmrc, which needs no root and still governs
    every `npm install -g` that user runs. A correct fallback, not a degraded one.
    """
    monkeypatch.setenv("FAKE_NPM_FAIL_GLOBAL", "1")
    said = []
    npm.config_set(npm.find(), "registry", "https://r/", said.append)
    assert fake_npm.calls() == [
        ["config", "set", "registry", "https://r/", "--global"],
        ["config", "set", "registry", "https://r/"],
    ]
    assert any("user level" in line for line in said)


def test_config_set_failing_both_ways_is_exit_1(fake_npm, monkeypatch):
    monkeypatch.setenv("FAKE_NPM_RC", "1")
    with pytest.raises(LmiError) as exc:
        npm.config_set(npm.find(), "registry", "https://r/", [].append)
    assert exc.value.code == 1
    assert fake_npm.count() == 2


def test_install_uses_the_package_constant(fake_npm):
    npm.install(npm.find(), [].append)
    assert fake_npm.calls() == [["install", "-g", "@anthropic-ai/claude-code"]]


def test_install_is_never_retried_without_g(fake_npm, monkeypatch):
    """MANDATORY. Silent failure: a package in ./node_modules and no `claude`.

    Dropping --global from `npm config set` is a correct fallback. Dropping -g
    from `npm install -g` is not a fallback at all - it installs into the
    current directory and creates no claude command, while npm exits 0. The
    only safe behaviour is to fail, so this pins that the retry never happens.
    """
    monkeypatch.setenv("FAKE_NPM_FAIL_GLOBAL", "1")
    monkeypatch.setenv("FAKE_NPM_RC", "0")
    with pytest.raises(LmiError) as exc:
        npm.install(npm.find(), [].append)
    assert exc.value.code == 1
    assert fake_npm.count() == 1
    assert fake_npm.calls()[0] == ["install", "-g", "@anthropic-ai/claude-code"]


def test_install_failure_names_both_ways_forward(fake_npm, monkeypatch):
    """Both hypotheses, not just the permissions one.

    On the air-gapped machines this command is for, an unreachable registry or
    an Artifactory that never mirrored the package is the likelier failure, and
    a message that answers it with "try sudo" sends the operator the wrong way.
    """
    monkeypatch.setenv("FAKE_NPM_RC", "1")
    with pytest.raises(LmiError) as exc:
        npm.install(npm.find(), [].append)
    message = str(exc.value)
    assert "registry" in message
    assert "Artifactory" in message
    assert "sudo" in message
    assert "prefix" in message


def test_install_failure_names_the_running_claude_code_case(fake_npm, monkeypatch):
    """MANDATORY. The one cause the rest of this message actively misdirects on.

    Windows cannot overwrite the files of a running program, so a repair run
    with a Claude Code session open anywhere fails with EBUSY. Nothing in lmi
    can see that - npm's output is inherited, not captured - so the clause has
    to be in the list of hypotheses, and it has to quote the words npm actually
    prints, or the operator cannot match it to what is on their screen.
    """
    monkeypatch.setenv("FAKE_NPM_RC", "1")
    with pytest.raises(LmiError) as exc:
        npm.install(npm.find(), [].append)
    message = str(exc.value)
    assert "EBUSY" in message
    # On one line: a phrase broken across a wrap is findable by neither eye
    # nor search, which is the whole purpose of quoting npm's own wording.
    assert "resource busy or locked" in message
    assert "running" in message.lower()
    assert "Close every Claude Code" in message


def test_the_busy_clause_comes_before_the_permissions_one(fake_npm, monkeypatch):
    """MANDATORY. Order is the whole value of the clause.

    Each clause is guarded by "if npm reported X", so the list is read top-down
    until one matches. The permissions clause says to re-run in an
    Administrator shell, and an Administrator shell cannot clear a file lock -
    an operator who reads that first spends their next attempt on it, fails
    identically, and has learned nothing. That is the same "wrong side of the
    building" this list was already ordered to avoid, arriving through a
    different clause.
    """
    monkeypatch.setenv("FAKE_NPM_RC", "1")
    with pytest.raises(LmiError) as exc:
        npm.install(npm.find(), [].append)
    message = str(exc.value)
    assert message.index("EBUSY") < message.index("Administrator")


def test_a_registry_with_shell_metacharacters_is_passed_through_literally(fake_npm):
    """A list argv, never shell=True: a config value must not reach a shell."""
    nasty = "https://r/;rm -rf ~;#"
    npm.config_set(npm.find(), "registry", nasty, [].append)
    assert fake_npm.calls()[0][3] == nasty


def test_the_module_never_uses_shell_true():
    """MANDATORY. shell=True would make the registry URL executable."""
    import inspect
    assert "shell=True" not in inspect.getsource(npm)
