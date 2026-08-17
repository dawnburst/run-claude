"""`lmi config switch` - apply a settings.json fragment, or restore the origin.

Moved out of runner.py when `lmi config schedule` became the second subcommand
and runner.py became a dispatcher. The flow below is unchanged, including the
order that makes it safe, and `fragment.py`, `merge.py` and `origin.py` stayed
where they are - they were always this subcommand's rather than the command's.

Order matters: everything is read and validated before anything is written, so
a malformed fragment leaves the machine exactly as it was. The snapshot is taken
before the merge is written, so a failure part-way still leaves a recoverable
state - and it is taken only after the fragment has been accepted, or a bad
fragment would freeze the wrong moment as 'pristine'.

The sibling modules are imported as modules, not as the names inside them, so
that patching `origin.capture` in a test reaches the call made here. Do not
simplify `from . import origin` into `from .origin import capture`.
"""

from . import catalog, fragment, origin
from .exit_codes import EXIT_CONFIG_WRITE
from .merge import deep_merge
from .output import say
from ...core import config as core_config, fs, jsonfile
from ...core.claude import settings_path
from ...core.errors import EXIT_OK, EXIT_USAGE, LmiError

NAME = "switch"
HELP = "apply a settings.json fragment, or restore the pristine settings"

TOKEN_KEY = "ANTHROPIC_AUTH_TOKEN"

BOTH_SOURCES = (
    "a switch name and --file are two sources for one merge, and only one of\n"
    "    them can be applied. Give one:\n"
    "      lmi config switch %s\n"
    "      lmi config switch --file %s"
)

UNKNOWN_NAME = (
    "no switch file named %r.\n"
    "    Looked for: %s\n"
    "%s"
)

NONE_FOUND = (
    "no switch files in %s\n"
    "    A switch file is named %s<name>%s and lives beside the lmi.json that\n"
    "    discovery resolved, so `lmi config switch <name>` works from any\n"
    "    directory. Create one:\n\n%s\n"
    "    then: lmi config switch <name>"
)

RESERVED_WARN = (
    "[WARN] %s cannot be selected:\n"
    "       `%s` is the keyword that restores the settings from before the\n"
    "       first switch, so no switch can ever reach that file. Rename it\n"
    "       to be able to switch to it."
)


def add_arguments(parser):
    """One positional carries both a name and the `origin` keyword.

    They used to be separated - `choices=["origin"]` on the positional, paths
    only ever behind --file - precisely so no precedence rule was needed. Named
    switch files put them back in one slot, so the keyword is reserved instead:
    `catalog.RESERVED` refuses it as a name and the listing warns about a file
    that claims it. See item 51.
    """
    parser.add_argument(
        "target", nargs="?", metavar="<name>",
        help="the switch file to apply: %s<name>%s beside the lmi.json that "
             "discovery resolves. Omit to list them. `origin` restores the "
             "settings.json this machine had before the first switch"
             % (catalog.PREFIX, catalog.SUFFIX),
    )
    parser.add_argument(
        "-f", "--file", dest="file", metavar="PATH",
        help="a settings.json fragment at a path of your own, instead of a "
             "named one. Default: %s" % fragment.DEFAULT_NAME,
    )
    core_config.add_argument(parser)


def run(args):
    target = getattr(args, "target", None)
    explicit_file = getattr(args, "file", None)
    explicit_config = getattr(args, "config", None)

    # origin wins over --file: it is the more destructive of the two and the
    # user named it explicitly, so silently applying a fragment instead would
    # be the worse surprise.
    if target == catalog.RESERVED[0]:
        return _restore()
    if target is not None:
        if explicit_file:
            raise LmiError(
                BOTH_SOURCES % (target, explicit_file), EXIT_USAGE
            )
        return _switch_named(target, explicit_config)
    if explicit_file:
        return _switch(explicit_file)
    # The unnamed working-directory default keeps working. Checked before the
    # listing so that a bare switch which used to apply a fragment still does,
    # rather than printing a list and exiting 0 - which would be a script that
    # silently stopped switching while reporting success.
    if fs.kind(fragment.default_path()) == fs.FILE:
        return _switch(None)
    return _list(explicit_config)


def _switch_named(name, explicit_config):
    directory = catalog.folder(explicit_config)
    path = catalog.path_for(directory, name)
    if fs.kind(path) != fs.FILE:
        raise LmiError(
            UNKNOWN_NAME % (name, path, _available(directory)), EXIT_USAGE
        )
    return _apply(*fragment.read(path))


def _list(explicit_config):
    """The names, or a usage error when there are none.

    Not exit 0 when the folder is empty. A bare `lmi config switch` that lists
    nothing has done nothing, and reporting that as success is the shape every
    silent failure in this project has in common.
    """
    directory = catalog.folder(explicit_config)
    entries, reserved = catalog.scan(directory)
    if not entries:
        # Before the raise, not after: nothing else will print, and a folder
        # whose only switch file is the unreachable one is precisely the case
        # the operator needs told about.
        _warn_reserved(reserved)
        raise LmiError(
            NONE_FOUND % (directory, catalog.PREFIX, catalog.SUFFIX,
                          _example(directory)),
            EXIT_USAGE,
        )
    say("Switch files in %s:" % directory)
    width = max(len(name) for name, _ in entries)
    for name, path in entries:
        say("  %-*s  %s" % (width, name, path.name))
    # After the list rather than before it: the warning is about a file that is
    # NOT in the list above, and reading it first invites the operator to look
    # for the name among the ones that follow.
    _warn_reserved(reserved)
    say("")
    say("Apply one with: lmi config switch <name>")
    say("Restore with:   lmi config switch %s" % catalog.RESERVED[0])
    return EXIT_OK


def _warn_reserved(reserved):
    for name in reserved:
        say("")
        say(RESERVED_WARN
            % ("%s%s%s" % (catalog.PREFIX, name, catalog.SUFFIX), name))


def _available(directory):
    entries, _ = catalog.scan(directory)
    if not entries:
        return "    There are none in that folder.\n"
    return ("    The ones that are there:\n%s\n"
            % "\n".join("      %s" % name for name, _ in entries))


def _example(directory):
    return "      %s" % catalog.path_for(directory, "gateway")


def _switch(explicit):
    return _apply(*fragment.load(explicit))


def _apply(doc, source):
    """The flow, from a fragment that has already been read and validated.

    Unchanged, including the order that makes it safe - everything is read and
    validated before anything is written, and the snapshot is taken after the
    fragment has been accepted so that a bad one cannot freeze the wrong moment
    as 'pristine'. Only where `doc` comes from is new.
    """
    say("Fragment: %s" % source)

    target = settings_path()
    current = jsonfile.read(target, "Claude Code settings", EXIT_CONFIG_WRITE)

    if origin.capture(current, EXIT_CONFIG_WRITE):
        say("Saved your current settings as the restore point: %s" % origin.path())

    merged = deep_merge(current, doc)
    jsonfile.write(
        target, merged, "Claude Code settings", EXIT_CONFIG_WRITE,
        mode=_mode_for(merged),
    )

    say("Wrote %s" % target)
    for key in sorted(doc):
        say("  %s" % key)
    say("Restore with: lmi config switch origin")
    return EXIT_OK


def _restore():
    # origin.restore returns the file it OVERWROTE - settings.json - not the
    # snapshot it consumed. That is the file this message must name.
    target = origin.restore(EXIT_CONFIG_WRITE)
    say("Restored %s to the settings from before the first switch." % target)
    say("The restore point is used up; the next switch will take a new one.")
    return EXIT_OK


def _mode_for(doc):
    """0600 when the document holds a credential, else leave the mode alone.

    On Windows os.chmod only toggles the read-only bit and grants no protection;
    lmi does not claim otherwise there.
    """
    env = doc.get("env")
    if isinstance(env, dict) and env.get(TOKEN_KEY):
        return 0o600
    return None
