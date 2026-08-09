"""The command registry.

One import and one list entry per command. Deliberately explicit rather
than pkgutil discovery: discovery makes --help ordering non-deterministic,
imports every command on every startup, and turns a typo into a silently
missing command.
"""

from . import config, install, schedule, upgrade

COMMANDS = [config, install, schedule, upgrade]
