"""Locating npm, and running one npm command.

Every invocation is a list argv through subprocess.run, with the shell never
invoked: the registry URL comes from a config file and must never reach a
shell. Output is inherited rather than captured, so npm's own progress and
errors reach the user as they happen, and check=False so a non-zero exit
returns instead of raising.
"""

import shutil
import subprocess

from .config import PACKAGE
from .exit_codes import EXIT_NPM_FAILED
from ...core.errors import EXIT_USAGE, LmiError

NO_NPM = (
    "npm was not found on PATH.\n"
    "    `lmi install claude` installs Claude Code through npm, so a Node.js\n"
    "    runtime has to be present first. Install Node.js 18 or newer, open a\n"
    "    new terminal, and run this again.\n"
    "    lmi deliberately does not install Node.js itself."
)

# Three hypotheses, not one. The registry clause is first because this command
# exists for air-gapped machines: the likeliest failure by far is that the
# internal registry is unreachable or has never mirrored the package, and
# populating it is explicitly not lmi's job. Answering that with "try sudo"
# sends the operator to the wrong side of the building. npm's own output is
# inherited and appears immediately above this, so keep the clauses short.
# The TLS clause became reachable when lmi stopped turning strict-ssl off for
# any config without a "cafile": a private CA the machine does not trust now
# fails here, loudly, instead of being silently waved through.
INSTALL_FAILED = (
    "npm install -g %s failed (exit %d).\n"
    "    npm's own output above says which of these it was:\n"
    "      - the registry, if npm reported a network error or a 404. Check the\n"
    "        \"registry\" value in the config file, and that Artifactory really\n"
    "        mirrors this package - lmi does not populate it.\n"
    "      - permissions, if the global node_modules directory is owned by root.\n"
    "        Either re-run this command with sudo (an Administrator shell on\n"
    "        Windows), or give npm a prefix you own:\n"
    "          npm config set prefix ~/.npm-global\n"
    "        and put ~/.npm-global/bin on your PATH, then run this again.\n"
    "    lmi never invokes sudo itself."
)


def find():
    """The npm executable, or a usage error naming what to install."""
    found = shutil.which("npm")
    if found is None:
        raise LmiError(NO_NPM, EXIT_USAGE)
    return found


def config_set(npm_exe, key, value, say):
    """`npm config set key value`, --global first, then user level.

    --global writes the npmrc under `npm prefix -g`, which on a system-wide Node
    install is root-owned. Retrying without the flag writes ~/.npmrc, which needs
    no root and still governs every `npm install -g` that user runs - a correct
    fallback, not a degraded one.
    """
    args = ["config", "set", key, value]
    if _run(npm_exe, args + ["--global"], say) == 0:
        return
    say("  --global failed; retrying at user level (~/.npmrc)")
    code = _run(npm_exe, args, say)
    if code != 0:
        raise LmiError(
            "npm config set %s failed (exit %d)" % (key, code), EXIT_NPM_FAILED
        )


def install(npm_exe, say):
    """`npm install -g @anthropic-ai/claude-code`.

    Deliberately NO fallback. Do not simplify this into config_set's
    retry-without-the-flag shape: dropping -g does not degrade, it does
    something else entirely - it installs into ./node_modules of whatever
    directory the user happened to be in, creates no `claude` command, and
    exits 0. A silent wrong-install is worse than a clean failure.
    """
    code = _run(npm_exe, ["install", "-g", PACKAGE], say)
    if code != 0:
        raise LmiError(INSTALL_FAILED % (PACKAGE, code), EXIT_NPM_FAILED)


def _run(npm_exe, args, say):
    say("  $ npm " + " ".join(args))
    return subprocess.run([npm_exe] + args).returncode
