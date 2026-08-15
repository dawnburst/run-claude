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

from pathlib import Path

from . import statusline, template
from .exit_codes import EXIT_CONFIG_WRITE
from ...core import config as core_config

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
    "      %s\n"
    "      %s\n"
    "    Edit those - the registry above all - and run this again to install\n"
    "    from your own source. The packaged copies are replaced on every\n"
    "    upgrade of lmi and are not the place to keep a site's settings."
)


def is_packaged(path):
    """True when discovery fell all the way through to the packaged folder."""
    return path == CONFIG


def adopt(source, say):
    """The config file the mode should be written to, materialising it if needed.

    Returns `source` unchanged for every config a human put somewhere, which is
    every case but one. For the packaged folder it copies both files to ~/.lmi/
    and returns the copy, so `backend.write` lands in the file `lmi schedule`
    resolves rather than in the wheel.

    Both halves, not just the config: an operator who later edits
    ~/.lmi/config.json alone would meet "no settings template found" from a
    folder lmi itself created.

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
    # statusline.install, because it is already the atomic byte-for-byte copy
    # this needs - O_BINARY, a temp file, os.replace - and a second one here
    # would be a second chance to get the Windows text-mode trap wrong. Bytes
    # are right for a JSON document too: the copy is what the operator will
    # edit, and lmi has no business rewriting its line endings on the way.
    statusline.install(CONFIG, home, "config file", EXIT_CONFIG_WRITE)
    statusline.install(
        TEMPLATE, home.parent / template.NAME, "settings template",
        EXIT_CONFIG_WRITE,
    )
    say("")
    say(ADOPTED % (home, home.parent / template.NAME))
    return home
