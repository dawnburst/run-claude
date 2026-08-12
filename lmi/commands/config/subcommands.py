"""The `lmi config` subcommand registry.

`commands/__init__.py` one level down. A subcommand is a module exposing the
same four names a command does - NAME, HELP, add_arguments, run - and is
registered by one import and one list entry here. Adding a third must not
require editing args.py or runner.py, and must not require cli.py to learn
anything at all.

Explicit rather than pkgutil discovery, for the reasons the command registry
gives: discovery makes --help ordering non-deterministic, imports every
subcommand on every startup, and turns a typo into a silently missing
subcommand. The list order is the --help order, so it is alphabetical and
stays that way.
"""

from . import schedule, switch

SUBCOMMANDS = [schedule, switch]
