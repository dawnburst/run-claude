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

# Hypotheses, not one, and the ORDER is load-bearing - each clause is guarded by
# "if npm reported X", so the list is read top-down until one matches, and a
# clause that misdirects costs the operator a whole attempt.
#
# The busy clause is first. It is the only one whose failure mode is undone in
# ten seconds, and - more importantly - it is the one the permissions clause
# below actively answers wrongly: EBUSY is a file lock, an Administrator shell
# cannot clear a file lock, and an operator who reads "try Administrator" first
# spends their retry on it and fails identically. That is exactly the "wrong
# side of the building" this list was already ordered to avoid; it simply
# arrives through a different clause. It is also unreachable on a first
# install - there is nothing to overwrite - so it costs a fresh-machine
# operator two lines they can see do not apply to them.
#
# The registry clause stays ahead of permissions for its original reason: this
# command exists for air-gapped machines, where an unreachable internal registry
# or one that never mirrored the package is the likeliest failure by far, and
# populating it is explicitly not lmi's job.
#
# The TLS clause became reachable when lmi stopped turning strict-ssl off for
# any config without a "cafile": a private CA the machine does not trust now
# fails here, loudly, instead of being silently waved through.
#
# npm's own output is inherited and appears immediately above this - lmi never
# sees it and so can never say which of these it was, which is why the clauses
# quote the words npm prints rather than describing them. Keep them short.
INSTALL_FAILED = (
    "npm install -g %s failed (exit %d).\n"
    "    npm's own output above says which of these it was:\n"
    # "resource busy or locked" is npm's own wording and must stay on ONE line:
    # the operator matches this clause against the text on their screen, and a
    # phrase broken across a wrap is not findable by eye or by search.
    "      - Claude Code is running, if npm reported EBUSY or\n"
    "        \"resource busy or locked\". A running program's files cannot be\n"
    "        replaced, so installing over an existing one fails until it is\n"
    "        closed. This is NOT a permissions problem, and an Administrator\n"
    "        shell will not fix it. Close every Claude Code session - other\n"
    "        terminals, your editor's extension, any `lmi schedule` run - and\n"
    "        run this again.\n"
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
