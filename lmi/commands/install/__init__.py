"""`lmi install` - install and configure a coding agent CLI.

The four-name command contract: NAME and HELP here, add_arguments from
config.py (validation lives with the command, not in cli.py) and run from
runner.py.
"""

from .config import add_arguments  # noqa: F401
from .runner import run  # noqa: F401

NAME = "install"
HELP = "Install and configure the Claude Code CLI"
