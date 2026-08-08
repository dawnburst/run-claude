"""Finding Git Bash and persisting CLAUDE_CODE_GIT_BASH_PATH.

Windows-only behaviour, driven on any OS by patching gitbash.on_windows and the
environment variables the search reads. The point of the off-Windows tests is
the opposite one: proving nothing happens there.
"""

import os

import pytest

from lmi.commands.install import gitbash


@pytest.fixture
def winenv(tmp_path, monkeypatch):
    """A fake Windows filesystem layout, with every search root redirected."""
    monkeypatch.setattr(gitbash, "on_windows", lambda: True)
    monkeypatch.setattr(gitbash, "_registry_paths", lambda: [])
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    monkeypatch.delenv(gitbash.VAR, raising=False)
    empty = tmp_path / "nopath"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    return tmp_path


def make(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    return path


def test_the_variable_is_spelled_exactly():
    assert gitbash.VAR == "CLAUDE_CODE_GIT_BASH_PATH"


def test_is_valid_accepts_the_names_claude_code_accepts(tmp_path):
    for name in ("bash.exe", "sh.exe", "bash", "sh"):
        assert gitbash.is_valid(str(make(tmp_path / name)))


def test_is_valid_rejects_another_binary(tmp_path):
    """MANDATORY. Silent failure: Claude Code discards what we wrote.

    Claude Code checks the basename is bash/sh before honouring the variable,
    warns, and falls back to its own two-path search. Writing git.exe there is
    worse than writing nothing: it looks configured and is not.
    """
    assert gitbash.is_valid(str(make(tmp_path / "git.exe"))) is False


def test_is_valid_rejects_a_path_that_does_not_exist(tmp_path):
    assert gitbash.is_valid(str(tmp_path / "gone" / "bash.exe")) is False


def test_is_valid_rejects_empty_and_none():
    assert gitbash.is_valid("") is False
    assert gitbash.is_valid(None) is False


def test_is_valid_survives_an_impossible_path():
    """fs.kind, not Path.is_file(): an over-long name raises ENAMETOOLONG."""
    assert gitbash.is_valid("/" + "x" * 5000 + "/bash.exe") is False


def test_an_existing_valid_variable_wins(winenv, monkeypatch):
    already = make(winenv / "custom" / "bash.exe")
    monkeypatch.setenv(gitbash.VAR, str(already))
    make(winenv / "pf" / "Git" / "bin" / "bash.exe")
    assert gitbash.find() == str(already)


def test_an_existing_invalid_variable_is_ignored(winenv, monkeypatch):
    monkeypatch.setenv(gitbash.VAR, str(winenv / "gone" / "bash.exe"))
    expected = make(winenv / "pf" / "Git" / "bin" / "bash.exe")
    assert gitbash.find() == str(expected)


def test_the_registry_beats_program_files(winenv, monkeypatch):
    """HKLM\\SOFTWARE\\GitForWindows is authoritative; the fixed paths guess."""
    from_registry = make(winenv / "elsewhere" / "Git" / "bin" / "bash.exe")
    monkeypatch.setattr(gitbash, "_registry_paths", lambda: [str(from_registry)])
    make(winenv / "pf" / "Git" / "bin" / "bash.exe")
    assert gitbash.find() == str(from_registry)


@pytest.mark.parametrize("relative", [
    ("pf", "Git", "bin", "bash.exe"),
    ("pf86", "Git", "bin", "bash.exe"),
    ("pf", "Git", "usr", "bin", "bash.exe"),
    ("lad", "Programs", "Git", "bin", "bash.exe"),
])
def test_each_fixed_candidate_is_found_in_isolation(winenv, relative):
    expected = make(winenv.joinpath(*relative))
    assert gitbash.find() == str(expected)


def test_program_files_beats_the_per_user_install(winenv):
    make(winenv / "lad" / "Programs" / "Git" / "bin" / "bash.exe")
    expected = make(winenv / "pf" / "Git" / "bin" / "bash.exe")
    assert gitbash.find() == str(expected)


def test_derived_from_git_on_path(winenv, monkeypatch):
    """Git installed somewhere unusual, but on PATH: <root>/cmd/git -> <root>/bin/bash."""
    root = winenv / "opt" / "Git"
    make(root / "bin" / "bash.exe")
    git = make(root / "cmd" / "git.exe")
    monkeypatch.setattr(gitbash.shutil, "which", lambda name: str(git))
    assert gitbash.find() == str(root / "bin" / "bash.exe")


def test_nothing_installed_is_none(winenv):
    assert gitbash.find() is None


def test_off_windows_nothing_is_probed(tmp_path, monkeypatch):
    """MANDATORY. CLAUDE_CODE_GIT_BASH_PATH is read through path/win32.

    It is never consulted on Linux or macOS, so probing there and writing the
    key into settings.json would be pure noise in a file the user reads.
    """
    monkeypatch.setattr(gitbash, "on_windows", lambda: False)
    make(tmp_path / "pf" / "Git" / "bin" / "bash.exe")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    assert gitbash.candidates() == []
    assert gitbash.find() is None


def test_persist_off_windows_does_nothing(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("setx must not run off Windows")

    monkeypatch.setattr(gitbash, "on_windows", lambda: False)
    monkeypatch.setattr(gitbash.subprocess, "run", explode)
    assert gitbash.persist("/anything", [].append) is False


def test_persist_calls_setx_with_a_list_argv(monkeypatch):
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(gitbash, "on_windows", lambda: True)
    monkeypatch.setattr(gitbash.subprocess, "run",
                        lambda argv, **k: calls.append(argv) or Result())
    assert gitbash.persist(r"C:\Git\bin\bash.exe", [].append) is True
    assert calls == [["setx", "CLAUDE_CODE_GIT_BASH_PATH", r"C:\Git\bin\bash.exe"]]


def test_persist_reports_failure_without_raising(monkeypatch):
    """A failed setx must not fail the install: npm already succeeded."""
    class Result:
        returncode = 1

    monkeypatch.setattr(gitbash, "on_windows", lambda: True)
    monkeypatch.setattr(gitbash.subprocess, "run", lambda argv, **k: Result())
    said = []
    assert gitbash.persist(r"C:\Git\bin\bash.exe", said.append) is False
    assert any("WARN" in line for line in said)


def test_persist_survives_setx_being_absent(monkeypatch):
    monkeypatch.setattr(gitbash, "on_windows", lambda: True)

    def missing(argv, **kwargs):
        raise OSError("no setx")

    monkeypatch.setattr(gitbash.subprocess, "run", missing)
    assert gitbash.persist("x", [].append) is False
