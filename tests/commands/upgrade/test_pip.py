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


# --- installing from the repo ----------------------------------------------

REPO = "https://github.com/dawnburst/run-claude.git"


def repo_cfg(index=INDEX, cafile=None):
    return config.Config(index=index, cafile=cafile, source=Path("lmi.json"),
                         repo=REPO, source_kind=config.SOURCE_REPO)


def test_a_repo_install_is_one_pip_command_naming_the_tag(fake_pip):
    pip.install(fake_pip.installation(), repo_cfg(), "v0.3.0", said([]))
    argv = fake_pip.calls()[0]
    assert argv[:3] == ["-m", "pip", "install"]
    assert argv[-1] == "lmi @ git+%s@v0.3.0" % REPO
    # pip does the clone, the build and the install. lmi runs no git of its own
    # here, and needs no build toolchain of its own.
    assert "--no-deps" in argv


def test_a_bare_version_becomes_the_v_tag(fake_pip):
    """`--version 0.3.0` and `--version v0.3.0` are the same request. The `v`
    is added here, in one place, rather than being something an operator has to
    know about the repository's tagging habit."""
    pip.install(fake_pip.installation(), repo_cfg(), "0.3.0", said([]))
    assert fake_pip.calls()[0][-1] == "lmi @ git+%s@v0.3.0" % REPO


def test_the_index_is_passed_on_a_repo_install(fake_pip):
    """MANDATORY - item 60.

    pip's build isolation resolves setuptools from an index, so a bare
    `git+https://` install on an air-gapped machine clones successfully and then
    fails fetching build dependencies - at a point that reads like a build error
    rather than a network one. The site's own index is what makes the build
    resolvable, and dropping this makes the feature work only where there is
    internet.
    """
    pip.install(fake_pip.installation(), repo_cfg(), "v0.3.0", said([]))
    argv = fake_pip.calls()[0]
    assert "--index-url" in argv
    assert argv[argv.index("--index-url") + 1] == INDEX


def test_a_cafile_is_passed_on_a_repo_install_too(fake_pip, tmp_path):
    """Same reason: the build dependencies come over the same TLS as everything
    else, so a private CA has to reach this install as well."""
    ca = tmp_path / "ca.pem"
    ca.write_text("x")
    pip.install(fake_pip.installation(), repo_cfg(cafile=ca), "v0.3.0", said([]))
    argv = fake_pip.calls()[0]
    assert "--cert" in argv
    assert argv[argv.index("--cert") + 1] == str(ca)


def test_a_repo_only_config_passes_no_index_arguments(fake_pip):
    """A config naming a repo and no index is the internet-connected case, and
    the only possible behaviour for it: pip resolves build dependencies from its
    own default. Inventing one here would be item 38's inference."""
    pip.install(fake_pip.installation(), repo_cfg(index=None), "v0.3.0", said([]))
    argv = fake_pip.calls()[0]
    assert "--index-url" not in argv
    assert argv[-1] == "lmi @ git+%s@v0.3.0" % REPO


def test_a_repo_install_with_no_version_asks_for_the_default_branch(fake_pip):
    """`newest_tag` answering None must not become `@None` or a bare `lmi`: the
    source is the repo, so the fallback is the repo's own default branch."""
    pip.install(fake_pip.installation(), repo_cfg(), None, said([]))
    argv = fake_pip.calls()[0]
    assert argv[-1] == "lmi @ git+%s" % REPO
    assert "--upgrade" in argv


def test_a_failing_repo_install_names_the_repo_not_the_index(fake_pip, monkeypatch):
    """The hypotheses printed have to match what was actually tried, or they
    send the operator to check a URL this command never used."""
    monkeypatch.setenv("FAKE_PIP_RC", "1")
    with pytest.raises(LmiError) as exc:
        pip.install(fake_pip.installation(), repo_cfg(), "v0.3.0", said([]))
    assert exc.value.code == 1
    message = str(exc.value)
    assert REPO in message
    assert "git" in message
