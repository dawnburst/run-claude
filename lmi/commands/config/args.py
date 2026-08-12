"""The `lmi config` argument surface.

cli.py hands each command one subparser and calls add_arguments on it. The
second level is built here, inside that call, so cli.py keeps its single
subparser level and learns nothing about this command - the architecture rule
in CLAUDE.md section 2.

There is no subcommand-specific branching in this file. Each subcommand
describes its own arguments; this loop only knows the four-name contract and
the marker that records which one was chosen.
"""

from .subcommands import SUBCOMMANDS

NAME = "config"
HELP = "Switch Claude Code between configurations"

# The marker runner.py dispatches on. argparse leaves it unset when no
# subcommand was given, which is what makes bare `lmi config` a usage error
# rather than a silent no-op.
RUN_MARKER = "_config_run"


def add_arguments(parser):
    sub = parser.add_subparsers(dest="config_command", metavar="<subcommand>")
    for command in SUBCOMMANDS:
        child = sub.add_parser(
            command.NAME, help=command.HELP, description=command.HELP
        )
        command.add_arguments(child)
        child.set_defaults(**{RUN_MARKER: command.NAME})
