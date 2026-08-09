"""Every question `lmi install` asks.

The mechanics and the no-terminal guard live in lmi/core/prompts.py, because
`lmi upgrade` needs the same guard and duplicating a guard is how one copy of
it comes to be missing. What stays here is this command's own NO_TERMINAL text
- which names the questions this command actually asks - and the three entry
points that tests/commands/install/test_runner.py patches to drive the flow.
"""

from ...core import prompts as _prompts
from ...core.prompts import CANCELLED  # noqa: F401

NO_TERMINAL = (
    "lmi install is interactive and needs a terminal.\n"
    "    It asks before repairing an existing install, for the Claude Code auth\n"
    "    token, and for the Git Bash path when it cannot find one.\n"
    "    Run it directly in a terminal, not from a script, a pipe or a build step."
)


def confirm(question, default=False):
    return _prompts.confirm(question, default, NO_TERMINAL)


def text(question, default=None):
    return _prompts.text(question, default, NO_TERMINAL)


def secret(question):
    return _prompts.secret(question, NO_TERMINAL)
