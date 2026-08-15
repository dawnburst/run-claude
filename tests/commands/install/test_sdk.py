"""The pip half of `lmi install claude`, and the check that follows it.

Two things are being pinned here, and they fail in opposite directions.

The install must go to `sys.executable` and nowhere else, with no fallback of
any kind: every fallback available to pip - another index, --user, --target -
puts the package somewhere that exits 0 and is still not importable by the
interpreter that will run `lmi schedule`.

And the check afterwards must be the import, not pip's exit code. pip's rc
answers "did a package get installed somewhere", which is a different question
and is answered yes in exactly the cases this command must catch.
"""

import sys

import pytest

from lmi.commands.install import sdk
from tests.commands.install.conftest import make_install_config

INDEX = "https://artifactory.corp.local/api/pypi/pypi/simple/"


def said():
    lines = []
    return lines, lines.append


# --- the pip command ------------------------------------------------------

def test_the_install_runs_the_interpreter_that_will_import_it(sdk_pip, tmp_path):
    """MANDATORY. Silent failure: installed somewhere, importable nowhere.

    A `pip` from PATH belongs to whichever interpreter is first there. `lmi`
    from the bootstrap scripts lives in its own venv, so an install through
    that pip exits 0, reports success, writes mode `sdk` - and every scheduled
    run afterwards exits 2 because the venv's interpreter cannot import it.
    """
    lines, say = said()
    cfg = make_install_config(tmp_path, index=INDEX)

    assert sdk.install(cfg, say) == 0
    argv = sdk_pip.calls()[0]
    # calls() records argv[1:], so the interpreter itself is asserted through
    # the fact that this fake - and only this fake - recorded the call at all.
    assert argv[:2] == ["-m", "pip"]
    assert argv[2] == "install"
    assert argv[-1] == sdk.REQUIREMENT


def test_the_index_url_is_the_configured_one(sdk_pip, tmp_path):
    lines, say = said()
    sdk.install(make_install_config(tmp_path, index=INDEX), say)
    argv = sdk_pip.calls()[0]
    assert "--index-url" in argv
    assert argv[argv.index("--index-url") + 1] == INDEX


def test_a_cafile_becomes_cert_and_asks_for_no_trusted_host(sdk_pip, tmp_path):
    """pip's option is --cert; npm's is cafile. They are not interchangeable."""
    pem = tmp_path / "ca.pem"
    pem.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    lines, say = said()

    sdk.install(make_install_config(tmp_path, index=INDEX, cafile=pem), say)

    argv = sdk_pip.calls()[0]
    assert argv[argv.index("--cert") + 1] == str(pem)
    assert "--trusted-host" not in argv
    assert not any("[WARN]" in line for line in lines)


def test_strict_ssl_false_disables_verification_out_loud(sdk_pip, tmp_path):
    """The same trade _configure_npm makes for npm, and the same warning class.

    Not silent, and not a global change: --trusted-host applies to this one
    invocation. Nothing writes a pip.conf, deliberately - a global one would
    redirect every future pip on the machine, by any user, for any package.
    """
    lines, say = said()
    sdk.install(make_install_config(tmp_path, index=INDEX, strict_ssl=False),
                say)

    argv = sdk_pip.calls()[0]
    assert argv[argv.index("--trusted-host") + 1] == "artifactory.corp.local"
    assert any("[WARN]" in line for line in lines)


@pytest.mark.parametrize("strict_ssl", [None, True])
def test_neither_tls_key_leaves_pips_verification_alone(
        sdk_pip, tmp_path, strict_ssl):
    """MANDATORY. Item 49, on pip's side of the fence.

    The absence of a cafile used to be read as "verification cannot work here"
    and buy a --trusted-host. Right for an internal index behind a private CA,
    wrong for one whose certificate the machine already trusts - and once the
    packaged default named an index, it fired on every fallback install, which
    is where it was found. Only `"strict-ssl": false` turns it off now.
    """
    lines, say = said()
    sdk.install(
        make_install_config(tmp_path, index=INDEX, strict_ssl=strict_ssl), say)

    argv = sdk_pip.calls()[0]
    assert "--trusted-host" not in argv
    assert not any("[WARN]" in line for line in lines)


def test_no_pip_conf_is_written(sdk_pip, tmp_path, home):
    """The asymmetry with npm, asserted rather than described.

    npm's config writes are global because npm has no per-invocation registry
    flag. pip has one, so a written pip.conf would be lmi redirecting every
    future pip on the machine to get one package installed today.
    """
    lines, say = said()
    sdk.install(make_install_config(tmp_path, index=INDEX), say)

    assert not (home / ".pip").exists()
    assert not (home / ".config" / "pip").exists()


def test_a_failing_pip_returns_its_code_and_does_not_raise(sdk_pip, tmp_path,
                                                           monkeypatch):
    """The inversion of npm.install, at the seam rather than in the flow.

    npm.install raises, because npm failing means there is no Claude Code. This
    returns, because pip failing means one of two backends is unavailable and
    the other one - the one driving the binary npm just installed - works.
    """
    monkeypatch.setenv("FAKE_PIP_RC", "1")
    lines, say = said()

    assert sdk.install(make_install_config(tmp_path, index=INDEX), say) == 1


def test_a_failing_pip_is_never_retried(sdk_pip, tmp_path, monkeypatch):
    """MANDATORY. Silent failure: an unvetted package from the wrong site.

    Both anti-fallbacks at once, because both are spelled the same way here -
    as an absent second invocation. A --index-url https://pypi.org/simple/
    retry installs an unvetted package from a different source than every other
    package on the machine and exits 0, defeating the only reason this command
    exists; a --user or --target retry puts it somewhere sys.executable may not
    import from, which is the wrong-interpreter failure with a helpful-looking
    flag attached.
    """
    monkeypatch.setenv("FAKE_PIP_FAIL_PACKAGE", sdk.DISTRIBUTION)
    lines, say = said()

    assert sdk.install(make_install_config(tmp_path, index=INDEX), say) != 0
    assert sdk_pip.count() == 1, "exactly one pip invocation, whatever happened"
    flat = " ".join(sum(sdk_pip.calls(), []))
    for never in ("pypi.org", "--user", "--break-system-packages", "--target"):
        assert never not in flat


def test_the_package_is_named_in_exactly_one_module():
    """Task 16's two constants, and why they are two.

    A dash-to-underscore rule that happens to hold for this package is a
    coincidence, not a rule: pip is given the distribution name and the backend
    imports the module name, and deriving either from the other fails silently
    the first time a package does not follow the convention.
    """
    assert sdk.DISTRIBUTION == "claude-agent-sdk"
    assert sdk.MODULE == "claude_agent_sdk"


# --- the check that decides the mode --------------------------------------

def test_importable_asks_the_interpreter_in_a_subprocess(sdk_pip, monkeypatch):
    """MANDATORY. Silent failure: the mode decided by the wrong question.

    An in-process `import claude_agent_sdk` inside the process that just ran
    pip can be answered from an already-populated sys.path cache, so a check
    that looks stricter than pip's exit code while sharing this process is not
    actually stricter. The subprocess asks exactly what `lmi schedule` will
    ask later, in the same way, from the same interpreter.
    """
    monkeypatch.setenv("FAKE_IMPORTABLE", "1")

    assert sdk.importable() is True
    assert sdk_pip.probes() == ["import %s" % sdk.MODULE]
    assert sdk_pip.count() == 0, "the probe is not a pip invocation"


def test_importable_is_false_when_the_import_fails(sdk_pip):
    assert sdk.importable() is False
    assert sdk_pip.probes() == ["import %s" % sdk.MODULE]


def test_importable_is_false_when_the_interpreter_cannot_even_run(monkeypatch,
                                                                  tmp_path):
    """Every way of failing means the same thing to the decision it feeds.

    A missing interpreter raises OSError rather than returning a code, and an
    unhandled one here would turn "the SDK is unavailable" - a supported
    outcome that writes `cli` and exits 0 - into a crashed install.
    """
    monkeypatch.setattr(sys, "executable", str(tmp_path / "no-such-python"))
    assert sdk.importable() is False


def test_the_probe_is_not_confused_with_a_pip_call(sdk_pip, tmp_path,
                                                   monkeypatch):
    """The two subprocess shapes are told apart by the fake, not just by lmi.

    If they were not, `test_a_failing_pip_is_never_retried` would be satisfied
    by the probe and would stay green with a PyPI retry added - a false green
    on the assertion that keeps both anti-fallbacks honest.
    """
    lines, say = said()
    sdk.install(make_install_config(tmp_path, index=INDEX), say)
    sdk.importable()

    assert sdk_pip.count() == 1
    assert len(sdk_pip.probes()) == 1
