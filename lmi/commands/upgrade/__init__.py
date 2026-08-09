"""`lmi upgrade` - install a newer lmi over this one.

The four-name command contract: NAME and HELP here, add_arguments from
config.py (validation lives with the command, not in cli.py) and run from
runner.py.
"""

from .config import add_arguments  # noqa: F401
from .runner import run  # noqa: F401

NAME = "upgrade"
HELP = "Upgrade lmi itself from the configured package index"
