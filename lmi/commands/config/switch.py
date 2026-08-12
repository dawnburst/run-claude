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

from . import fragment, origin
from .exit_codes import EXIT_CONFIG_WRITE
from .merge import deep_merge
from .output import say
from ...core import jsonfile
from ...core.claude import settings_path
from ...core.errors import EXIT_OK

NAME = "switch"
HELP = "apply a settings.json fragment, or restore the pristine settings"

TOKEN_KEY = "ANTHROPIC_AUTH_TOKEN"


def add_arguments(parser):
    """`origin` is a bare positional with choices=["origin"]; a path only ever
    arrives behind --file. That is what removes the collision between the
    keyword and a file of the same name: the two never occupy the same
    argument, so no precedence rule is needed."""
    parser.add_argument(
        # metavar without brackets: argparse adds its own for nargs="?", so
        # "[origin]" renders as "[[origin]]" in usage and as "argument [origin]:"
        # in an error.
        "target", nargs="?", choices=["origin"], metavar="origin",
        help="restore the settings.json this machine had before the first switch",
    )
    parser.add_argument(
        "-f", "--file", dest="file", metavar="PATH",
        help="the settings.json fragment to apply. Default: config/settings_switch.json",
    )


def run(args):
    # origin wins over --file: it is the more destructive of the two and the
    # user named it explicitly, so silently applying a fragment instead would
    # be the worse surprise.
    if getattr(args, "target", None) == "origin":
        return _restore()
    return _switch(getattr(args, "file", None))


def _switch(explicit):
    doc, source = fragment.load(explicit)
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
