"""The `lmi config` argument surface.

cli.py hands each command one subparser and calls add_arguments on it. The
second level is built here, inside that call, so cli.py keeps its single
subparser level and learns nothing about this command - the architecture rule
in CLAUDE.md section 2.

`origin` is a bare positional with choices=["origin"]; a path only ever arrives
behind --file. That is what removes the collision between the keyword and a file
of the same name: the two never occupy the same argument, so no precedence rule
is needed.
"""

NAME = "config"
HELP = "Switch Claude Code between configurations"

SWITCH_HELP = "apply a settings.json fragment, or restore the pristine settings"


def add_arguments(parser):
    sub = parser.add_subparsers(dest="config_command", metavar="<subcommand>")
    switch = sub.add_parser("switch", help=SWITCH_HELP, description=SWITCH_HELP)
    switch.add_argument(
        # metavar without brackets: argparse adds its own for nargs="?", so
        # "[origin]" renders as "[[origin]]" in usage and as "argument [origin]:"
        # in an error.
        "target", nargs="?", choices=["origin"], metavar="origin",
        help="restore the settings.json this machine had before the first switch",
    )
    switch.add_argument(
        "-f", "--file", dest="file", metavar="PATH",
        help="the settings.json fragment to apply. Default: config/settings_switch.json",
    )
    switch.set_defaults(_config_run="switch")
