"""`lmi config` - switch Claude Code between configurations.

The four-name command contract: NAME, HELP and add_arguments come from args.py,
run from runner.py. cli.py sees nothing else.
"""

from .args import HELP, NAME, add_arguments  # noqa: F401
from .runner import run  # noqa: F401
