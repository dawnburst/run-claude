"""The `lmi config` dispatcher.

It knows the four-name contract and nothing else: which subcommand ran is a
marker argparse set, and what that subcommand does is its own module's. The
flows themselves live in switch.py and schedule.py.

The exception wrapper stays here rather than in each subcommand, so that every
`lmi config` failure reports the same way whichever verb produced it.
"""

from .args import RUN_MARKER
from .exit_codes import EXIT_INTERNAL
from .output import say  # noqa: F401 - re-exported; callers know this name
from .subcommands import SUBCOMMANDS
from ...core.errors import EXIT_USAGE, LmiError

NO_SUBCOMMAND = (
    "lmi config needs a subcommand.\n"
    "    lmi config init                    copy lmi's own config folder to ~/.lmi\n"
    "    lmi config switch                  apply config/settings_switch.json\n"
    "    lmi config switch --file PATH      apply that fragment\n"
    "    lmi config switch origin           restore the pristine settings.json\n"
    "    lmi config schedule                show which backend lmi schedule uses\n"
    "    lmi config schedule --mode MODE    set it"
)


def run(args):
    try:
        return _run(args)
    except LmiError:
        # Already carries its exit code and a message cli.main will print.
        raise
    except Exception as exc:                    # noqa: BLE001 - deliberate
        raise LmiError(
            "unexpected failure in lmi config: %s: %s" % (type(exc).__name__, exc),
            EXIT_INTERNAL,
        )


def _run(args):
    chosen = getattr(args, RUN_MARKER, None)
    if chosen is None:
        raise LmiError(NO_SUBCOMMAND, EXIT_USAGE)
    for command in SUBCOMMANDS:
        if command.NAME == chosen:
            return command.run(args)
    # Unreachable through argparse, which rejects an unknown verb itself. It is
    # here because the alternative - falling off the end and returning None -
    # would make the console script exit 0 for a command that did nothing.
    raise LmiError(NO_SUBCOMMAND, EXIT_USAGE)
