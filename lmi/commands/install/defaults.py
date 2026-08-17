"""The config folder packaged inside lmi, and adopting it as the user's own.

`pip install lmi` is meant to be the whole installation: a machine that has the
wheel and nothing else can run `lmi install claude`. That needs a config folder
on a machine with nothing in the working directory and nothing in ~/.lmi, so one
ships inside the package - an lmi.json with the settings.json template beside
it, found by `template.load` exactly the way a site's own pair is, because it is
laid out the same way.

It is the LAST candidate discovery considers, after ~/.lmi/config.json, and the
`Config:` line the runner prints says which file it read. A packaged default
that outranked a file somebody put somewhere, or that read like one, would be
the wrong-registry provisioning that core/config.py's two refusals exist to
prevent, shipped as a feature: a mistyped working directory used to be exit 2,
"no config file found", and would silently become a successful install from
whatever registry the wheel was built with.

There is deliberately no statusline.js here, and the packaged template declares
no `statusLine`. statusline.py says why: one script inside the package would
give every site the same statusline and no way to vary it. The pair therefore
agrees with itself and item 32's two warnings stay quiet.

`adopt` is the other half, and the reason this is a module rather than three
constants in config.py. A file inside site-packages cannot be the one
`schedule.mode` is written to. It is replaced by the next `pip install
--upgrade`; it may sit on a read-only prefix; and `lmi schedule` never looks
there, because `core_config.find_optional` - the search *that* command uses -
has no packaged candidate and must not grow one, or `lmi config schedule --set`
would write into the wheel too. A mode written into it would be item 39's
silent failure exactly: a file with the right contents in it that nothing reads.

So the last thing `lmi install claude` does before writing the mode is copy the
packaged pair to ~/.lmi/. From then on the machine has an ordinary config
folder that every command already understands and the operator can edit, and
the second run of this command finds it by the ordinary search and never comes
back here.
"""

import shutil
from pathlib import Path

from . import statusline, template
from .exit_codes import EXIT_CONFIG_WRITE
from ...core import config as core_config, fs, jsonfile
from ...core.errors import LmiError

# A data directory, not a package: no __init__.py, and nothing imports from it.
# pyproject.toml has to name it under [tool.setuptools.package-data] or it is
# in the checkout and not in the wheel - see tests/test_packaging.py.
DIR_NAME = "default-config"
DIR = Path(__file__).resolve().parent / DIR_NAME

# Path(__file__) rather than importlib.resources: files() returns a Traversable,
# while every path here flows into Config.source, template.load and the error
# messages of both, all of which take a Path and outlive any as_file() context.
# pip never installs a zipped wheel, so __file__ is a real file on disk. This is
# the one place in lmi/ that reads its own location; keep it the only one.
CONFIG = DIR / core_config.CWD_CONFIG_NAME
TEMPLATE = DIR / template.NAME

ADOPTED = (
    "No config file was found, so the defaults packaged with lmi were used\n"
    "    and copied to a folder of your own:\n"
    "%s\n"
    "    Edit those - the registry above all - and run this again to install\n"
    "    from your own source. The packaged copies are replaced on every\n"
    "    upgrade of lmi and are not the place to keep a site's settings."
)

BACKED_UP = (
    "Backed up %d existing file%s from that folder first:\n"
    "      %s\n"
    "    Nothing there was deleted; the copies are never cleaned up."
)

# The folder adopt puts previous contents in, inside ~/.lmi so that one
# directory holds a config and its own history. Prefix, not a suffix, so a
# generation can be recognised without parsing the timestamp - which is what
# lets the next adoption skip it instead of copying it into itself.
BACKUP_PREFIX = "backup_"

BROKEN_PACKAGE = (
    "the config folder packaged inside lmi is incomplete: %s is missing from\n"
    "    %s\n"
    "    That is a broken installation of lmi itself, not a configuration\n"
    "    error. Reinstall lmi, or pass --config to name a folder of your own."
)


def is_packaged(path):
    """True when discovery fell all the way through to the packaged folder."""
    return path == CONFIG


def adopt(source, say):
    """The config file the mode should be written to, materialising it if needed.

    Returns `source` unchanged for every config a human put somewhere, which is
    every case but one. For the packaged folder it copies **every file in it**
    to ~/.lmi/ and returns the config copy, so `backend.write` lands in the file
    `lmi schedule` resolves rather than in the wheel.

    Every file, not the two it used to name: the packaged folder is the one
    default that ships, so a `statusline.js` or a `settings_switch_<name>.json`
    in it is part of that default. Copying only lmi.json and settings.json
    leaves the rest inside site-packages, where `lmi config switch` never looks
    and the next `pip install --upgrade` replaces it - and an operator who edits
    the config lmi just made them would meet "no settings template found" from
    a folder lmi itself created.

    Item 39's re-check is satisfied by construction rather than by a second
    search. Discovery reached the packaged folder only because $LMI_CONFIG,
    ./config/lmi.json and ~/.lmi/config.json all had nothing in them, and
    nothing in this command creates one of those, so the file written here is
    the file the next search finds.

    Called at the end of the run rather than while the Config is built: until
    the last Claude write has succeeded this command has changed nothing the
    user did not agree to, and a config folder created for an install that then
    failed would be a machine described as provisioned by a file that provisioned
    nothing.
    """
    if not is_packaged(source):
        return source

    home = core_config.expand(core_config.HOME_CONFIG)
    folder = home.parent
    packaged = _packaged_files()

    # Before the first write, and fatal if it fails - see _back_up.
    saved, into = _back_up(folder, say)

    landed = []
    for path in packaged:
        # lmi.json becomes config.json: that is the name discovery looks for at
        # the home level, and adopting it under its packaged name would produce
        # a folder the next search walks straight past.
        dest = home if path.name == core_config.CWD_CONFIG_NAME else \
            folder / path.name
        # statusline.install, because it is already the atomic byte-for-byte
        # copy this needs - O_BINARY, a temp file, os.replace, the source's mode
        # preserved - and a second one here would be a second chance to get the
        # Windows text-mode trap wrong. Bytes are right for a JSON document too:
        # the copy is what the operator will edit, and lmi has no business
        # rewriting its line endings on the way.
        statusline.install(path, dest, "packaged %s" % path.name,
                           EXIT_CONFIG_WRITE)
        landed.append(dest)

    say("")
    say(ADOPTED % "\n".join("      %s" % p for p in landed))
    if saved:
        say("")
        say(BACKED_UP % (saved, "" if saved == 1 else "s", into))
    return home


def _packaged_files():
    """Every file in the packaged folder, config and template first.

    Order only matters for the report. What matters here is the refusal: a
    folder missing either half is a broken lmi rather than a misconfiguration,
    and copying whatever is left would produce a config folder that fails at
    the next step with a message pointing at the operator instead of at the
    install.
    """
    for required in (CONFIG, TEMPLATE):
        if fs.kind(required) != fs.FILE:
            raise LmiError(
                BROKEN_PACKAGE % (required.name, DIR), EXIT_CONFIG_WRITE
            )
    rest = sorted(p for p in DIR.iterdir()
                  if p.is_file() and p not in (CONFIG, TEMPLATE))
    return [CONFIG, TEMPLATE] + rest


def _back_up(folder, say):
    """Copy what is already in `folder` into folder/backup_<stamp>/.

    (how many were saved, where). Both zero and None when there was nothing,
    so a fresh machine does not grow an empty backup directory.

    adopt runs when discovery found no config *file*, which is not the same as
    an empty folder: a ~/.lmi holding only a settings.json, or only switch
    files, or one of these backups, still falls through to the packaged default
    and is copied into. Those files are about to be overwritten and this copy is
    the only version of them that survives - so a failure here is fatal, for
    exactly the reason jsonfile.backup's is (item 31). Nothing is lost by
    stopping: the packaged default is still in the wheel and the command can be
    run again.

    Earlier backups are skipped, not copied. They live inside the folder being
    backed up, so including them would nest every generation inside the next -
    the directory doubling on each adoption, with the oldest copy sinking a
    level deeper each time.
    """
    if fs.kind(folder) != fs.DIR:
        return 0, None
    existing = sorted(p for p in folder.iterdir() if p.is_file())
    if not existing:
        return 0, None

    into = folder / (BACKUP_PREFIX + jsonfile.timestamp())
    try:
        into.mkdir(parents=True, exist_ok=True)
        for path in existing:
            shutil.copy2(str(path), str(into / path.name))
    except OSError as exc:
        raise LmiError(
            "could not back up the existing config folder: %s -> %s (%s)\n"
            "    Nothing was changed. Overwriting files we cannot preserve is "
            "not worth the risk." % (folder, into, exc),
            EXIT_CONFIG_WRITE,
        )
    return len(existing), into
