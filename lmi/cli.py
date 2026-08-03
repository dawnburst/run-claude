"""Top-level parser and dispatch.

This module deliberately knows nothing about any command beyond the four
names in the command contract (NAME, HELP, add_arguments, run). Adding a
command must never require editing this file.
"""

import argparse
import sys

from . import __version__
from .commands import COMMANDS
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
    try:
        return run(args)
    except LmiError as exc:
        print("[ERROR] " + str(exc), file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
