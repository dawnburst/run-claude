"""`lmi config schedule` - read and write which backend `lmi schedule` uses.

The vocabulary is not this module's. The valid names, the default, the parser
and the writer all live in `lmi/commands/schedule/backend.py`, because
`schedule` owns what the value means and three commands now write it. This
module is the argument surface and the two flows: show, and set.

Showing exists as much for debugging as for the user. It is the only thing that
answers "which of four discoverable config files is my `lmi schedule` actually
reading, and where would a change go?" - which is the question behind every
silent failure in this area.
"""

from .exit_codes import EXIT_CONFIG_WRITE
from .output import say
from ..schedule import backend
from ...core import config as core_config
from ...core.errors import EXIT_OK, EXIT_USAGE, LmiError

NAME = "schedule"
HELP = "show or set the backend `lmi schedule` runs Claude through"

# Where a mode is written when discovery found no config file at all. The
# home-level file rather than ./config/lmi.json: a mode is a property of the
# machine, not of whichever directory the operator happened to be standing in,
# and a config file created inside a checkout would be committed by accident.
CREATE_AT = core_config.HOME_CONFIG

SHADOWED = (
    "the mode was written to %s, but that is NOT the file `lmi schedule` will\n"
    "    read. Discovery resolves %s first, so this machine would keep its old\n"
    "    backend for ever while this command reported success.\n"
    "    Either set it in the file that wins:\n\n"
    "        lmi config schedule --mode %s --config %s\n\n"
    "    or remove the file just written: %s"
)


def add_arguments(parser):
    parser.add_argument(
        # Deliberately NO choices=: argparse would reject a bad value with its
        # own message, and a wrong mode must read identically here and in
        # `lmi schedule`. One template, in backend.parse, with one list of
        # valid names in it.
        "--mode", dest="mode", metavar="MODE",
        help="the backend to use: %s. Omit to show the current one"
             % ", ".join(backend.MODES),
    )
    core_config.add_argument(parser)


def run(args):
    explicit = getattr(args, "config", None)
    mode = getattr(args, "mode", None)
    if mode is None:
        return _show(explicit)
    return _set(explicit, mode)


def _show(explicit):
    path, _ = core_config.find_optional(explicit)
    if path is None:
        current, source = backend.DEFAULT, backend.DEFAULT_SOURCE
    else:
        current, source = backend.of_document(core_config.load(path), path)
    say("Backend    : %s" % current)
    say("Chosen by  : %s" % source)
    # The third line is the one that is not deducible from the other two: the
    # file a --mode would land in is not necessarily the file the mode came
    # from, because an absent key falls back to the default without naming a
    # file at all.
    say("--mode goes to: %s" % (path if path is not None else _create_at()))
    if path is None:
        say("             (no config file exists yet; it would be created)")
    return EXIT_OK


def _set(explicit, mode):
    # Validated before anything is looked up, let alone written, so a typo
    # touches no file at all - and reads exactly as it does from `lmi schedule`.
    backend.parse(mode, "--mode")

    path, _ = core_config.find_optional(explicit)
    created = path is None
    if created:
        path = _create_at()

    backend.write(path, mode, EXIT_CONFIG_WRITE)
    say("Backend    : %s" % mode)
    say("Written to : %s" % path)

    if created:
        _confirm_it_wins(path, explicit, mode)
    return EXIT_OK


def _confirm_it_wins(written, explicit, mode):
    """The file we just created must be the one discovery now resolves.

    Only for a file this command created: when discovery found something, that
    IS the winner by definition. Creating one is the case where it might not
    be - and a mode written into a shadowed file is the worst shape of failure
    here, because the command reports success, the file is there with the right
    contents, and `lmi schedule` goes on using the old backend for ever. The
    only thing that would ever reveal it is the header line the runner prints.
    """
    found, _ = core_config.find_optional(explicit)
    if found is not None and found == written:
        return
    raise LmiError(
        SHADOWED % (written, found, mode, found, written), EXIT_USAGE
    )


def _create_at():
    return core_config.expand(CREATE_AT)
