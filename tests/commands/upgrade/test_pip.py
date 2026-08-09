"""Building and running the one pip command, and the version probe."""

import os
from pathlib import Path

import pytest

from lmi.commands.upgrade import config, pip
from lmi.core.errors import LmiError

INDEX = "https://artifactory.example.com/api/pypi/pypi-virtual/simple/"


def cfg(cafile=None):
    return config.Config(index=INDEX, cafile=cafile, source=Path("lmi.json"))


def said(lines):
    return lambda message="": lines.append(message)


def test_install_pins_the_version_and_names_the_index(fake_pip):
    lines = []
    pip.install(fake_pip.installation(), cfg(), "0.2.0", said(lines))

    argv = fake_pip.calls()[0]
    assert argv[:3] == ["-m", "pip", "install"]
    assert "--index-url" in argv
    assert argv[argv.index("--index-url") + 1] == INDEX
    assert "--extra-index-url" not in argv
    assert "--no-deps" in argv
    assert argv[-1] == "lmi==0.2.0"
    assert "--user" not in argv


def test_no_version_becomes_upgrade_lmi(fake_pip):
    pip.install(fake_pip.installation(), cfg(), None, said([]))
    argv = fake_pip.calls()[0]
    assert argv[-2:] == ["--upgrade", "lmi"]


def test_a_cafile_becomes_cert_not_cafile(fake_pip, tmp_path):
    """pip's option is --cert. npm's is cafile; they are not the same flag."""
    pem = tmp_path / "ca.pem"
    pem.write_bytes(b"x")
    pip.install(fake_pip.installation(), cfg(cafile=pem), "0.2.0", said([]))
    argv = fake_pip.calls()[0]
    assert argv[argv.index("--cert") + 1] == str(pem)
    assert "cafile" not in argv


def test_the_user_flag_appears_only_for_a_user_site_install(fake_pip):
    pip.install(fake_pip.installation(user_flag=True), cfg(), "0.2.0", said([]))
    assert "--user" in fake_pip.calls()[0]


def test_a_failing_pip_is_exit_1_and_names_the_index(fake_pip, monkeypatch):
    monkeypatch.setenv("FAKE_PIP_RC", "1")
    with pytest.raises(LmiError) as exc:
        pip.install(fake_pip.installation(), cfg(), "0.2.0", said([]))
    assert exc.value.code == 1
    assert "index" in str(exc.value)


@pytest.mark.skipif(os.name != "nt", reason="the clause is Windows-only")
def test_the_windows_failure_names_the_running_exe(fake_pip, monkeypatch):
    monkeypatch.setenv("FAKE_PIP_RC", "1")
    with pytest.raises(LmiError) as exc:
        pip.install(fake_pip.installation(), cfg(), "0.2.0", said([]))
    assert "lmi.exe" in str(exc.value)


def test_the_probe_reads_the_newest_version(fake_pip, monkeypatch):
    monkeypatch.setenv("FAKE_PIP_LATEST", "0.9.0")
    assert pip.latest(fake_pip.installation(), cfg()) == "0.9.0"
    argv = fake_pip.calls()[0]
    assert argv[:4] == ["-m", "pip", "index", "versions"]
    assert argv[4] == "lmi"
    assert argv[argv.index("--index-url") + 1] == INDEX


def test_a_probe_that_fails_is_none_not_an_error(fake_pip, monkeypatch):
    """An older pip has no `index` subcommand. That must degrade the question,
    never fail the command - a diagnostic may not block the thing it
    diagnoses."""
    monkeypatch.delenv("FAKE_PIP_LATEST", raising=False)
    assert pip.latest(fake_pip.installation(), cfg()) is None


def test_a_probe_that_cannot_even_run_is_none(fake_pip, tmp_path):
    gone = fake_pip.installation()
    broken = type(gone)(gone.kind, [str(tmp_path / "nope")] + gone.pip_prefix[1:],
                        gone.user_flag, gone.script, gone.where)
    assert pip.latest(broken, cfg()) is None
