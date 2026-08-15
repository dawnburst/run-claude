"""Installing the Claude Agent SDK, and finding out whether it worked.

The only module in `lmi install` that names the SDK package, in either of its
two spellings. They are two constants rather than one derived from the other
because the check below gates on the *module* name while pip is given the
*distribution* name, and a dash-to-underscore rule that happens to hold for one
package is not a rule - it is a coincidence that fails silently the first time
it does not hold.

Neither is a config key. `install/config.py`'s PACKAGE says why: a command
whose target is configurable is a different command. Only the *index* the
package comes from is configuration.
"""

import subprocess
import sys
from urllib.parse import urlsplit

from ...core import pip as core_pip

# What pip is asked for.
DISTRIBUTION = "claude-agent-sdk"

# The floor, and it must be ASKED FOR rather than merely declared.
#
# pyproject.toml's `sdk` extra carries the same bound, but that constraint only
# applies to `pip install "lmi[sdk]"` - it has no effect on this command, which
# names the distribution directly. Installing a bare `claude-agent-sdk` here
# therefore accepted whatever version the index happened to offer, and an index
# mirroring one too old to have `ClaudeAgentOptions.setting_sources` would
# install cleanly, import cleanly, get written `sdk` - and then raise a
# TypeError on every single iteration afterwards. `importable()` cannot see
# that: importing the package is not the same as being able to build its
# options.
#
# 0.2.136 is the version lmi's shapes were verified against field by field (see
# tests/commands/schedule/test_sdk_fake_shapes.py). Lower it only after running
# that module against the version your index actually carries.
# tests/test_packaging.py pins this string and the extra's to each other, so
# they cannot drift.
SPECIFIER = ">=0.2.136"
REQUIREMENT = DISTRIBUTION + SPECIFIER

# What `lmi schedule`'s backend actually imports, and therefore the only
# question worth asking after pip returns. See importable().
MODULE = "claude_agent_sdk"

TLS_WARNING = (
    "[WARN] \"strict-ssl\" is false, so certificate verification is OFF for this\n"
    "       one pip invocation. Anyone who can answer as %s can\n"
    "       serve the package that is about to be installed.\n"
    "       Set \"cafile\" to your internal CA and drop \"strict-ssl\" to close\n"
    "       this."
)


def install(cfg, say):
    """Run pip once. Returns its exit code and never raises for a non-zero one.

    Deliberately the opposite of npm.install, and the inversion is the point.
    npm failing means there is no Claude Code and the command has failed; pip
    failing means one of two supported backends is unavailable and the other
    one works. So this reports and the caller degrades - see runner._install_sdk.

    Into `sys.executable`, never a pip found on PATH. `lmi` installed by the
    bootstrap scripts lives in ~/.local/share/lmi/venv, and `lmi schedule` will
    run from that interpreter - so that is the interpreter the SDK has to be
    importable from. A pip from PATH installs into a different one, exits 0,
    and leaves the backend unable to import a package that is definitely
    installed somewhere.

    Two anti-fallbacks, and both must stay:

      - NO retry against public PyPI when the configured index 404s. On an
        air-gapped machine that is a timeout; on one with egress it installs an
        unvetted package and exits 0, from a different source than every other
        package on the machine. lmi does not populate Artifactory and must not
        route around it.
      - NO --user, --break-system-packages or --target retry. Each of those
        puts the package somewhere `sys.executable` may not import from, which
        is the wrong-interpreter failure above with a helpful-looking flag
        attached: pip exits 0, the import still fails, and the flag makes it
        look like the problem was solved.
    """
    argv = core_pip.prefix(sys.executable) + ["install"] \
        + _index_argv(cfg, say) + [REQUIREMENT]
    return core_pip.run(argv, say)


def _index_argv(cfg, say):
    """--index-url and the TLS decision, mirroring _configure_npm's shape.

    Nothing is inferred, which is item 49 applied on this side of the fence.
    With a cafile, pip is pointed at it with --cert. Verification is turned off
    only when the config asks for it - `"strict-ssl": false`, the same key that
    governs npm, because it is one decision about one pair of hosts and two
    spellings for it would be two chances to configure only half a machine. A
    config that says neither leaves pip's default verification alone.

    The absence of a cafile used to be enough on its own, which is right for an
    internal index behind a private CA and wrong for one whose certificate the
    machine already trusts - and once the packaged default named an index, that
    guess ran on every fallback install. The cost of not guessing is that a
    private CA now fails here, loudly, rather than being waved through.

    The asymmetry with npm is deliberate and is a feature: npm's config writes
    are global because npm has no per-invocation registry flag, and pip does.
    So `--trusted-host` covers this one command and nothing here writes a
    pip.conf. A global pip.conf would silently redirect every future pip on
    this machine, by any user, for any package.
    """
    argv = core_pip.index_argv(cfg.index, cfg.cafile)
    if cfg.strict_ssl is not False:
        return argv
    host = urlsplit(cfg.index).hostname
    if host:
        argv += ["--trusted-host", host]
    say(TLS_WARNING % (host or "the index host"))
    return argv


def importable():
    """Can the interpreter that will run `lmi schedule` import the SDK?

    THE check. Not pip's exit code, and not an import in this process, for two
    separate reasons:

      - pip can exit 0 having installed into a different interpreter from the
        one that will run `lmi schedule`. Its exit code answers "did a package
        get installed somewhere", which is not the question.
      - an in-process import inside the process that just ran pip can be misled
        by an already-populated sys.path cache, so a check that looks stricter
        than pip's rc while sharing this process is not actually stricter.

    A subprocess of `sys.executable` answers exactly the question the runner
    will ask later, in the same way, from the same interpreter.

    Any failure at all is False. This decides which mode to write, and every
    way of failing to import means the same thing to that decision.
    """
    try:
        done = subprocess.run(
            [sys.executable, "-c", "import %s" % MODULE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return done.returncode == 0
