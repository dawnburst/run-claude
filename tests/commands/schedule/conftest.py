"""Shared helpers for the `lmi schedule` tests.

`Config` has ten fields and several test modules need one; building it in each
of them meant two copies that had already drifted apart.
"""

import sys

import pytest

from lmi.commands.schedule import backend, paths, sdk
from lmi.commands.schedule.config import Config

from . import sdk_fake

# Captured at import time, before `sdk_mode` replaces it with the refusal
# below. `fake_sdk` puts it back - it is the function under test, and the
# refusal exists only to catch a test that forgot to make it safe to call.
_REAL_SDK_CALL = sdk.call
_REAL_SDK_REQUIRE = sdk.require

# And the real resolver, for the tests of `backend.resolve` itself - which the
# autouse guard below would otherwise replace with the refusal, making the one
# function whose job is resolving a mode the one function that cannot be
# tested.
_REAL_RESOLVE = backend.resolve

# The same, for the session key. Kept separately because the two are resolved
# separately: one run reads both, and a test of either must be able to reach
# the real thing.
_REAL_RESOLVE_SESSION = backend.resolve_session

# A fixed run timestamp, so a resolved log file name is predictable.
TS = "20260803-101500"

# What a mode fixture reports as the source, so a header assertion has
# something stable to match and cannot accidentally pass on "default".
FIXTURE_SOURCE = "the test's mode fixture"

UNDECLARED_MODE = """\
this test resolved a `lmi schedule` backend without declaring which one.

The default is now `sdk`, so a test written against the CLI path that does not
say so would silently change backend under itself - passing or failing for
reasons unrelated to what it asserts, and leaving one backend untested while
the suite still looks complete.

Take one of these fixtures:

    cli_mode   the subprocess + stdout path, with `fake_claude`
    sdk_mode   the Claude Agent SDK path, with `fake_sdk`

Nothing here reads the developer's real ~/.lmi/config.json either, which is the
other half of what this guard buys: a mode set on this machine cannot change
what the suite tests."""

NO_SDK_FAKE = """\
this test asked for `sdk_mode` but not for `fake_sdk`, and then tried to call
the SDK for real.

That is a spend-real-money bug, not a test failure. PATH replacement protects
nothing once the call is a Python import: the SDK spawns a bundled Claude Code
binary, so an un-faked SDK-mode test would reach the real service. Add the
`fake_sdk` fixture."""


@pytest.fixture(autouse=True)
def _mode_must_be_declared(monkeypatch):
    """Refuse to resolve a backend for a test that did not name one.

    Deliberately a patch of `backend.resolve` rather than an inspection of
    `request.fixturenames`: this way the guard fires for exactly the tests that
    actually resolve a mode, and the many tests in this directory that never go
    near a backend - paths, prompt composition, the state file, the JSON
    renderer - are left alone rather than made to declare something irrelevant.

    Autouse fixtures are set up before explicitly requested ones at the same
    scope, so `cli_mode` and `sdk_mode` below reliably override this.
    """
    def _refuse(explicit_config=None):
        pytest.fail(UNDECLARED_MODE, pytrace=False)

    monkeypatch.setattr(backend, "resolve", _refuse)


def _force(monkeypatch, mode):
    monkeypatch.setattr(
        backend, "resolve", lambda explicit_config=None: (mode, FIXTURE_SOURCE)
    )
    return mode


@pytest.fixture(autouse=True)
def _session_is_hermetic(monkeypatch):
    """Answer `backend.resolve_session` from the documented default, never from
    this machine's config file.

    Deliberately a default rather than the refusal `_mode_must_be_declared`
    installs, and the asymmetry is the point. A test that does not name a
    backend is testing an unknown one, because there are two and they behave
    differently; a test that does not mention continuity is testing the
    behaviour every run gets, which is `on`. What must NOT happen either way is
    reading the developer's own ~/.lmi/config.json - a `"session": false` there
    would quietly leave the whole feature untested while the suite stayed
    green.
    """
    monkeypatch.setattr(
        backend, "resolve_session",
        lambda explicit_config=None: (backend.SESSION_DEFAULT, FIXTURE_SOURCE),
    )


@pytest.fixture
def cli_mode(monkeypatch):
    """Run this test against the `claude` command line. Pair with fake_claude."""
    return _force(monkeypatch, backend.CLI)


@pytest.fixture
def sdk_mode(monkeypatch):
    """Run this test against the SDK backend. Pair with fake_sdk.

    `sdk.require` is stubbed out, so the suite does not need the extra
    installed to exercise the mode. `sdk.call` is replaced with a refusal
    rather than left alone, so that forgetting `fake_sdk` fails loudly here
    instead of reaching the real service - see NO_SDK_FAKE.
    """
    monkeypatch.setattr(sdk, "require", lambda: None)

    def _refuse(*a, **k):
        pytest.fail(NO_SDK_FAKE, pytrace=False)

    monkeypatch.setattr(sdk, "call", _refuse)
    return _force(monkeypatch, backend.SDK)


@pytest.fixture
def fake_sdk(tmp_path, monkeypatch, sdk_mode):
    """A whole fake `claude_agent_sdk`, and the SDK backend really running.

    Takes `sdk_mode` rather than being combinable with it, so that `fake_sdk`
    alone is enough to write an SDK-mode test and the two can never be
    requested in the wrong order. `sdk_mode` is set up first (it is this
    fixture's own dependency), which is what lets the two lines below put the
    real `sdk.call` and `sdk.require` back: the refusal it installs exists only
    to catch a test that never made calling them safe, and installing the fake
    module IS making it safe.

    The containment is `sys.modules`, not a PATH replacement and not the SDK's
    `query(transport=...)` hook - see sdk_fake.py's docstring. `sdk._import()`
    does a plain `import claude_agent_sdk` inside a function, so this entry is
    what that import resolves to, on a machine with the real package installed
    just as much as on one without it. No line of the real package runs.
    """
    monkeypatch.setattr(sdk, "call", _REAL_SDK_CALL)
    monkeypatch.setattr(sdk, "require", _REAL_SDK_REQUIRE)

    recdir = tmp_path / "rec"
    if not recdir.exists():
        recdir.mkdir()
    recorder = sdk_fake.Recorder(recdir, tmp_path / "count.txt")
    monkeypatch.setitem(sys.modules, "claude_agent_sdk",
                        sdk_fake.build_module(recorder))
    # `dir` and `count_file` are named after fake_claude's, so a test that
    # reads the composed prompt or counts the calls is written the same way in
    # both modes.
    return recorder


@pytest.fixture
def on_windows(monkeypatch):
    """Take the Windows branch of paths.py.

    paths._on_windows is patched rather than os.name, which cannot be patched:
    pathlib picks its concrete class from os.name at instantiation, so forcing
    it to "nt" here makes every Path() raise NotImplementedError.
    """
    monkeypatch.setattr(paths, "_on_windows", lambda: True)


@pytest.fixture
def deny_touch(monkeypatch):
    """Make the writability probe fail the way C:\\Windows does."""
    def _throw(self, *a, **k):
        raise PermissionError(13, "denied")

    monkeypatch.setattr(paths.Path, "touch", _throw)


@pytest.fixture
def make_cfg():
    """Return a factory: make_cfg(tmp_path, **overrides) -> Config."""

    def _make(work_dir, **overrides):
        fields = dict(
            prompt_text="write a haiku",
            prompt_file=None,
            at=None,
            interval_min=0,
            max_runs=1,
            work_dir=work_dir,
            user_flags=[],
            log_arg=None,
            state_arg=None,
            resume=False,
            # Spelled out rather than left to the dataclass default, so a
            # Config built here says which backend it is for. The default is
            # `sdk`; a factory that silently produced one would put every test
            # using it on the backend it probably did not mean.
            mode=backend.CLI,
            mode_source=FIXTURE_SOURCE,
        )
        fields.update(overrides)
        return Config(**fields)

    return _make
