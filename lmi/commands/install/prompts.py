"""Every question `lmi install` asks.

One module, so the no-terminal guard exists once and the tests have a single
seam to drive the whole interactive flow.

`lmi install` is interactive by design and has no --yes flag, which means it
cannot be driven from a script. What it must not do is *hang*: with no
terminal, input() and getpass() raise EOFError, and an unguarded call would
block a provisioning run forever with nothing to answer it. That is the
difference between "not scriptable" and "wedged", and only the second is a bug.

Note this command is the reason invariant 3 in CLAUDE.md names `lmi schedule`
rather than lmi as a whole.
"""

import getpass

from ...core.errors import EXIT_USAGE, LmiError

NO_TERMINAL = (
    "lmi install is interactive and needs a terminal.\n"
    "    It asks before repairing an existing install, for the Claude Code auth\n"
    "    token, and for the Git Bash path when it cannot find one.\n"
    "    Run it directly in a terminal, not from a script, a pipe or a build step."
)

CANCELLED = "cancelled - nothing was changed."


def confirm(question, default=False):
    """A yes/no question. Anything but y/yes is no."""
    hint = " [Y/n]: " if default else " [y/N]: "
    answer = _ask(input, question + hint).strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def text(question, default=None):
    """A free-text answer. Blank takes `default`, or "" when there is none."""
    hint = " [%s]: " % default if default else ": "
    answer = _ask(input, question + hint).strip()
    return answer or (default or "")


def secret(question):
    """A secret answer, never echoed.

    getpass, not input: an echoed token lands in the terminal scrollback and in
    any recording of the session.
    """
    return _ask(getpass.getpass, question + ": ").strip()


def _ask(reader, prompt):
    try:
        return reader(prompt)
    except EOFError:
        raise LmiError(NO_TERMINAL, EXIT_USAGE)
    except KeyboardInterrupt:
        # Every prompt is asked before anything is modified, so Ctrl-C here is
        # genuinely a no-op - say so rather than printing a traceback.
        raise LmiError(CANCELLED, EXIT_USAGE)
