"""The one question `lmi upgrade` asks.

The mechanics and the no-terminal guard are lmi/core/prompts.py's. What is
here is this command's own NO_TERMINAL text - which must describe the question
this command asks and no other - and the single entry point that
tests/commands/upgrade/test_runner.py patches to drive the flow.
"""

from ...core import prompts as _prompts

NO_TERMINAL = (
    "lmi upgrade is interactive and needs a terminal.\n"
    "    It asks before replacing the installed lmi, because that replaces the\n"
    "    command you are running.\n"
    "    Run it directly in a terminal, not from a script, a pipe or a build step."
)


def confirm(question, default=False):
    return _prompts.confirm(question, default, NO_TERMINAL)
