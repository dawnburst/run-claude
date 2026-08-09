"""Asking a question at a terminal, and the guard against hanging without one.

One module, so the guard exists exactly once. A command that is interactive by
design cannot be driven from a script - that is a decision, not a bug. What it
must never do is *hang*: with no terminal, input() and getpass() raise EOFError,
and an unguarded call would block a provisioning run forever with nothing to
answer it. That is the difference between "not scriptable" and "wedged", and
only the second is a bug.

The no-terminal message is the caller's, because it should say which questions
that particular command asks. Note that these commands are the reason invariant
3 in CLAUDE.md names `lmi schedule` rather than lmi as a whole.
"""

import getpass

from .errors import EXIT_USAGE, LmiError

NO_TERMINAL = (
    "this command is interactive and needs a terminal.\n"
    "    Run it directly in a terminal, not from a script, a pipe or a build step."
)

CANCELLED = "cancelled - nothing was changed."


def confirm(question, default=False, no_terminal=NO_TERMINAL):
    """A yes/no question. Anything but y/yes is no."""
    hint = " [Y/n]: " if default else " [y/N]: "
    answer = _ask(input, question + hint, no_terminal).strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def text(question, default=None, no_terminal=NO_TERMINAL):
    """A free-text answer. Blank takes `default`, or "" when there is none."""
    hint = " [%s]: " % default if default else ": "
    answer = _ask(input, question + hint, no_terminal).strip()
    return answer or (default or "")


def secret(question, no_terminal=NO_TERMINAL):
    """A secret answer, never echoed.

    getpass, not input: an echoed token lands in the terminal scrollback and in
    any recording of the session.
    """
    return _ask(getpass.getpass, question + ": ", no_terminal).strip()


def _ask(reader, prompt, no_terminal):
    try:
        return reader(prompt)
    except EOFError:
        raise LmiError(no_terminal, EXIT_USAGE)
    except KeyboardInterrupt:
        # Every prompt is asked before anything is modified, so Ctrl-C here is
        # genuinely a no-op - say so rather than printing a traceback.
        raise LmiError(CANCELLED, EXIT_USAGE)
