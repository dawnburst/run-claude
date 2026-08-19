"""`lmi config init` - put the config folder lmi ships into ~/.lmi.

`lmi install claude` used to be the only thing that ever created that folder:
discovery falls through to the copy packaged in the wheel, and `defaults.adopt`
copies it to ~/.lmi as the last step of a successful provision. So an operator
who deleted ~/.lmi got it back by provisioning Claude Code all over again -
npm, the settings document, the onboarding keys - to recover four files that
were sitting inside the package the whole time. And a plain `pip install lmi`,
or either bootstrap script, created nothing at all, because a wheel has no
post-install hook to run any of this from.

This is that one step, on its own, and the installer scripts call it after they
install the wheel. It writes only ~/.lmi - deliberately not `--config`, which
would let a folder somewhere else be filled with files the operator would then
have to keep in step with the one discovery searches at the home level.

The whole behaviour is `defaults.fill`, which lives beside the packaged folder
rather than here so that where that folder is, and what lmi.json is renamed to,
have one spelling in lmi. This module is the argument surface and the report -
the same division `lmi config schedule` has with `schedule/backend.py`.

**Nothing already in the folder is overwritten**, and that is the rule to hold
on to. `adopt` may replace what it finds because it copies the folder into a
backup_<stamp>/ first; this command backs up nothing, and the installer scripts
run it on every install. An init that overwrote would silently replace a site's
edited settings.json - and the switch files it was written to deliver - with the
packaged examples, on a routine re-install, reporting success, with no copy of
the operator's version anywhere.
"""

from .exit_codes import EXIT_CONFIG_WRITE
from .output import say
from ..install import defaults
from ...core.errors import EXIT_OK

NAME = "init"
HELP = "copy the config folder lmi ships into ~/.lmi, keeping what is there"

NOTE = (
    "Those are lmi's defaults, not a site's: edit the registry in config.json,\n"
    "    the endpoint in the switch files, and re-run `lmi install claude` to\n"
    "    install from your own source."
)

NOTHING_TO_DO = "Everything lmi ships is already there; nothing was changed."


def add_arguments(parser):
    """No arguments at all.

    Deliberately no --config: the folder this fills is the one discovery
    searches at the home level, and that is the only folder whose absence this
    command exists to fix. A --config that pointed somewhere else would produce
    a second config folder for the operator to keep in step with the first.
    """


def run(args):                                  # noqa: ARG001 - registry shape
    folder = defaults.home_config().parent
    created, kept = defaults.fill(folder, EXIT_CONFIG_WRITE)

    say("Config folder: %s" % folder)
    for path in created:
        say("  created  %s" % path.name)
    for path in kept:
        # Named individually rather than counted, because "kept" is the answer
        # to "why did my file not change" and a number cannot be checked
        # against the folder.
        say("  kept     %s" % path.name)
    say("")
    say(NOTHING_TO_DO if not created else NOTE)
    return EXIT_OK
