"""Top-level parser and dispatch.

This module deliberately knows nothing about any command beyond the four
names in the command contract (NAME, HELP, add_arguments, run). Adding a
command must never require editing this file.

It has exactly one exception, and it is not a command: `upgrade/notice.py`,
which prints at most one line a day saying that a newer lmi exists. That line
belongs to no command - the machines that need it are the ones running
`lmi schedule` unattended, where nobody types `lmi upgrade` speculatively - and
everything it needs to know (the package, the repo URL, the `lmi` config
section, how two versions compare) is defined in that package already. A second
spelling of any of those would be a notice suggesting an upgrade to something
`lmi upgrade` would not install. The registry rule above is untouched: no
command is named here, and adding one still requires no edit to this file.
"""

import argparse
import sys

from . import __version__
from .commands import COMMANDS
from .commands.upgrade import notice
from .core.errors import EXIT_USAGE, LmiError


def build_parser():
    parser = argparse.ArgumentParser(
        prog="lmi", description="Helper CLI for the Claude Code CLI."
    )
    parser.add_argument("--version", action="version", version="lmi " + __version__)
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    for command in COMMANDS:
        sp = sub.add_parser(command.NAME, help=command.HELP, description=command.HELP)
        command.add_arguments(sp)
        sp.set_defaults(_run=command.run)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    run = getattr(args, "_run", None)
    if run is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    # Before the command, not after: a notice printed after a four-hour
    # `lmi schedule` run is a notice nobody reads, and printed here it lands in
    # that run's log beside the header an operator already looks at. It cannot
    # raise - see notice.maybe_say - so it needs no guard of its own, and it
    # must not grow one that hides a bug in this file.
    notice.maybe_say(args.command)
    try:
        return run(args)
    except LmiError as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
