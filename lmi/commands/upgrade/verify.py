"""Confirming the upgrade by running the command that was just installed.

Never lmi.__version__. This process imported that BEFORE pip ran, so it reports
the old version no matter what is now on disk - a command that read its own
in-memory version and announced an upgrade would be the stale-wheel bug
rebuilt deliberately: success reported, old code installed, nothing on screen
to suggest otherwise. The only honest answer is a fresh process.
"""

import re
import subprocess

from .exit_codes import EXIT_VERIFY_FAILED
from ...core.errors import LmiError

# What `lmi --version` prints: argparse's version action, "lmi " + __version__.
VERSION_RE = re.compile(r"^lmi\s+(\S+)\s*$")

DID_NOT_RUN = (
    "pip reported success, but the installed command did not run:\n"
    "      %s\n"
    "      %s\n"
    "    The machine has already changed. Re-run the install script for this\n"
    "    platform to put a known-good lmi back."
)

UNREADABLE = (
    "pip reported success, but the installed command did not report a version:\n"
    "      %s\n"
    "      said: %s\n"
    "    The machine has already changed."
)

WRONG_VERSION = (
    "pip reported success, but the installed command is still the old one.\n"
    "      expected: %s\n"
    "      got:      %s\n"
    "      command:  %s\n"
    "    Something else on this machine is providing lmi, or pip installed\n"
    "    somewhere this command does not reach. Do not trust a later\n"
    "    `lmi --version` from this shell either - run it in a new one."
)


def confirm(script, expected):
    """The version `script --version` reports, checked against `expected`.

    `expected` may be None, which happens only when the index could not be
    asked what the newest version is. Verification is then weaker - it still
    catches an install that does not run, just not one that is stale.

    stderr is captured SEPARATELY from stdout, and every line of stdout is a
    candidate for the version line - not just the first. A DeprecationWarning,
    a .pth file's own output, a locale complaint or a sitecustomize message
    lands on stderr (or ahead of the version line on stdout) before argparse's
    version action ever runs, and none of that is claude's prose: it is a
    two-token line the program itself emits, so there is no reason to accept
    only line 1 the way schedule/state.check_complete deliberately does for
    claude's restated protocol sentence. The combined text is used only for
    the DID_NOT_RUN / UNREADABLE diagnostics, so a failure still shows the
    operator everything the command said.
    """
    try:
        done = subprocess.run([str(script), "--version"],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    except OSError as exc:
        raise LmiError(DID_NOT_RUN % (script, exc), EXIT_VERIFY_FAILED)

    out = done.stdout.decode("utf-8", "replace")
    err = done.stderr.decode("utf-8", "replace")
    combined = (out + err).strip()
    if done.returncode != 0:
        raise LmiError(
            DID_NOT_RUN % (script, combined or "exit %d" % done.returncode),
            EXIT_VERIFY_FAILED,
        )

    match = None
    for line in out.splitlines():
        # A BOM some interpreters/launchers prepend, and stray leading/trailing
        # whitespace, are not "prose" the way schedule's problem is - strip
        # them before matching rather than failing on cosmetics.
        candidate = line.lstrip("\ufeff").strip()
        match = VERSION_RE.match(candidate)
        if match:
            break
    if match is None:
        raise LmiError(UNREADABLE % (script, combined or "nothing"),
                       EXIT_VERIFY_FAILED)

    got = match.group(1)
    if expected is not None and got != expected:
        raise LmiError(WRONG_VERSION % (expected, got, script),
                       EXIT_VERIFY_FAILED)
    return got
