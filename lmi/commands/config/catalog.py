"""Where switch files live, and what they are called.

`fragment.py` owns one switch file - reading it, validating it. This owns the
*collection*: the folder they sit in, the name convention that turns
`lmi config switch gateway` into a path, and the listing a bare
`lmi config switch` prints. The two are separate for the reason install's
`template.py` and `settings.py` are: the reasons a file on disk can be wrong
are not the same concern as what a settings document should contain.

The folder is the one holding the `lmi.json` that discovery resolves - exactly
the relationship `settings.json` has to it in `lmi install claude`, and for the
same reason. A site keeps its configuration in one folder, and `--config` and
`$LMI_CONFIG` then move the switch files with it rather than leaving them
behind in whatever directory the operator happened to be standing in. That is
the whole point of the convention: a switch works from any path.

Deliberately NO packaged fallback in `folder()`. `core_config.find` grows one
only for `lmi install claude`, which ships defaults of its own; no switch file
ships inside the wheel, and passing a fallback here would point a bare
`lmi config switch` at site-packages - the same shape as item 39, a file with
the right contents in it that nothing the operator can edit ever reads.
"""

import re

from ...core import config as core_config, fs
from ...core.errors import EXIT_USAGE, LmiError

PREFIX = "settings_switch_"
SUFFIX = ".json"

# `origin` is the restore keyword and cannot also select a file. The two
# meanings share one argument, so one of them has to win; the keyword does,
# because it is what every switch prints as the way back and what docs/config.md
# documents. A file named for it is reported by `scan` and refused by
# `path_for` rather than silently shadowed - see item 51.
RESERVED = ("origin",)

# The name becomes a filename, so it must not be able to be a path. Refusing
# separators is the point; the rest of the character class is narrow because a
# name is typed at a shell and lives in docs/config.md.
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# `.` and `..` match the class above and are not names. Listed rather than
# excluded by a cleverer pattern, so that what is refused is readable.
_NOT_NAMES = (".", "..")

PURPOSE = (
    "`lmi config switch` reads its switch files from the folder that file "
    "is in."
)

EXAMPLE = """{
  "claude": {
    "registry": "https://artifactory.example.com/api/npm/npm/"
  }
}"""


def folder(explicit):
    """The directory the switch files live in. A usage error if there is none."""
    return core_config.find(explicit, PURPOSE, EXAMPLE).parent


def path_for(directory, name):
    """`directory`/settings_switch_<name>.json, for a name that may be one."""
    _validate(name)
    return directory / ("%s%s%s" % (PREFIX, name, SUFFIX))


def scan(directory):
    """(sorted [(name, path)], sorted [reserved names found]). Never raises.

    A folder that does not exist reads the same as an empty one: the caller
    turns both into the same "there are none here" message, and there is
    nothing an exception would let it say that the empty list does not.
    """
    entries = []
    reserved = []
    for path in _listing(directory):
        name = _name_of(path)
        if name is None:
            continue
        if fs.kind(path) != fs.FILE:
            continue
        if name in RESERVED:
            reserved.append(name)
        else:
            entries.append((name, path))
    return sorted(entries), sorted(reserved)


def _listing(directory):
    try:
        return sorted(directory.iterdir())
    except OSError:
        # Missing, unreadable, or not a directory at all. Each is "no switch
        # files here", and each is the caller's message to write.
        return []


def _name_of(path):
    """The name inside settings_switch_<name>.json, or None if it is not one."""
    if not path.name.startswith(PREFIX) or not path.name.endswith(SUFFIX):
        return None
    name = path.name[len(PREFIX):-len(SUFFIX)]
    # An empty name is `settings_switch_.json`, which is not selectable - there
    # is no argument that produces it - so listing it would offer the operator
    # something they cannot ask for.
    return name or None


def _validate(name):
    if name in _NOT_NAMES or not _NAME_RE.match(name or ""):
        raise LmiError(
            "not a switch name: %r\n"
            "    A name is the part between %s and %s in a file name, and may\n"
            "    hold letters, digits, dot, dash and underscore - it is a name,\n"
            "    not a path. Run `lmi config switch` to list the ones you have."
            % (name, PREFIX, SUFFIX),
            EXIT_USAGE,
        )
    if name in RESERVED:
        raise LmiError(
            "`%s` is the restore keyword, not a switch name.\n"
            "    `lmi config switch %s` restores the settings this machine had\n"
            "    before the first switch, so a %s%s%s cannot be selected.\n"
            "    Rename that file to switch to it."
            % (name, name, PREFIX, name, SUFFIX),
            EXIT_USAGE,
        )
