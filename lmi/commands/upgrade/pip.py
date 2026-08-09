"""The one pip command, and the read-only probe that precedes it.

Every invocation is a list argv through subprocess.run, with the shell never
invoked: the index URL comes from a config file and must never reach a shell.
The install's output is inherited rather than captured, so pip's own progress
and errors reach the user as they happen, and check=False so a non-zero exit
returns instead of raising.

Note this module is named `pip` and lives inside a package, so `import pip`
elsewhere still finds the real one; nothing here imports pip as a library.
"""

import os
import re
import subprocess

from .config import PACKAGE
from .exit_codes import EXIT_PIP_FAILED
from ...core.errors import LmiError

# `pip index versions lmi` answers with "lmi (0.9.0)" on the first line and
# "Available versions: ..." on the second. Anchored per line, and any failure
# to match is None rather than an error - see latest().
LATEST_RE = re.compile(r"^\s*%s\s*\((.+?)\)\s*$" % re.escape(PACKAGE), re.MULTILINE)

# Two hypotheses, not one, and pip's own output is inherited so it appears
# immediately above this. The Windows clause is printed on every Windows
# failure without inspecting pip's text: pattern-matching an error message to
# decide whether to offer help is a guess that goes stale with the next pip
# release, and an extra clause on a platform where it is plausible costs
# nothing.
INSTALL_FAILED = (
    "pip install %s failed (exit %d).\n"
    "    pip's own output above says which of these it was:\n"
    "      - the index, if pip reported a network error or a 404. Check the\n"
    '        "index" value in the config file, and that it really carries lmi -\n'
    "        lmi does not populate it.\n"
)

WINDOWS_CLAUSE = (
    "      - the lmi.exe being replaced is the one running this command. If pip\n"
    "        reported a permission or access error, run this from a shell where\n"
    "        no lmi is live:\n\n"
    "          python -m pip install --user --upgrade --index-url %s lmi\n"
)


def _index_argv(cfg):
    argv = ["--index-url", cfg.index]
    if cfg.cafile:
        # pip's option is --cert. npm's is cafile; they are not interchangeable.
        argv += ["--cert", str(cfg.cafile)]
    return argv


def latest(inst, cfg):
    """The newest version the index offers, or None if it cannot say.

    Best-effort by design. `pip index` is an experimental subcommand that an
    older pip does not have at all, and its output could change. Every failure
    is None, which degrades the question the user is asked - it must never
    degrade the command, because a diagnostic that blocks the thing it
    diagnoses is worse than no diagnostic.
    """
    argv = inst.pip_prefix + ["index", "versions", PACKAGE] + _index_argv(cfg)
    try:
        done = subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL)
    except OSError:
        return None
    if done.returncode != 0:
        return None
    match = LATEST_RE.search(done.stdout.decode("utf-8", "replace"))
    return match.group(1).strip() if match else None


def install(inst, cfg, version, say):
    """Install `version`, or the newest when it is None."""
    argv = inst.pip_prefix + ["install"]
    if inst.user_flag:
        argv.append("--user")
    argv += _index_argv(cfg)
    # --no-deps: lmi declares no dependencies and tests/test_packaging.py fails
    # if that stops being true, so this changes nothing about a correct install
    # - and it means a wrong or tampered package on the index cannot pull
    # anything else onto the machine.
    argv.append("--no-deps")
    if version is None:
        argv += ["--upgrade", PACKAGE]
    else:
        argv.append("%s==%s" % (PACKAGE, version))

    say("  $ " + " ".join(argv))
    code = subprocess.run(argv).returncode
    if code != 0:
        what = PACKAGE if version is None else "%s==%s" % (PACKAGE, version)
        message = INSTALL_FAILED % (what, code)
        if os.name == "nt":
            message += WINDOWS_CLAUSE % cfg.index
        raise LmiError(message, EXIT_PIP_FAILED)
