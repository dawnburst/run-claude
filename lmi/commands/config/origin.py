"""The pristine snapshot of settings.json, and putting it back.

`switch origin` means "the settings this machine had before the first switch",
not "undo the last switch". That distinction lives entirely in capture(): the
snapshot is written ONLY if it does not already exist.

Get that backwards and the command still works, in the sense that nothing
errors. `origin` silently becomes undo-one-step while still being spelled
origin, and the user's real settings are unrecoverable after the second switch -
with the file present either way and a single switch behaving identically, so
nothing afterwards shows which of the two you built.
"""

import os

from ...core import fs, jsonfile
from ...core.claude import settings_path
from ...core.errors import EXIT_USAGE, LmiError

SUFFIX = ".lmi-origin"

NOTHING_TO_RESTORE = (
    "there is nothing to restore: no switch has been made on this machine,\n"
    "    so lmi has no record of what settings.json looked like before one.\n"
    "    `lmi config switch --file <fragment>` takes that snapshot the first\n"
    "    time it runs."
)


def path():
    """~/.claude/settings.json.lmi-origin - beside the file it protects."""
    settings = settings_path()
    return settings.with_name(settings.name + SUFFIX)


def exists():
    return fs.kind(path()) == fs.FILE


def capture(settings, code):
    """Snapshot `settings` if no snapshot exists. True if one was written.

    The `if not exists()` is the whole mechanism - see the module docstring.
    Do not "simplify" it into an unconditional write.

    0600 because settings.json can carry ANTHROPIC_AUTH_TOKEN and ~/.claude/ is
    0755, so a snapshot at the umask default would publish it to every user on
    the box.
    """
    if exists():
        return False
    jsonfile.write(path(), settings, "origin snapshot", code, mode=0o600)
    return True


def restore(code):
    """Put the snapshot back over settings.json and remove it. Returns its path.

    Removed afterwards so the next switch establishes a fresh pristine point,
    and so a second `origin` says there is nothing left rather than silently
    repeating itself.
    """
    if not exists():
        raise LmiError(NOTHING_TO_RESTORE, EXIT_USAGE)

    snapshot = path()
    target = settings_path()
    doc = jsonfile.read(snapshot, "origin snapshot", code)
    # The snapshot is 0600, and the file it restores must not be looser.
    jsonfile.write(target, doc, "Claude Code settings", code, mode=0o600)
    try:
        os.unlink(str(snapshot))
    except OSError as exc:
        raise LmiError(
            "settings.json was restored but the snapshot could not be removed: "
            "%s (%s)\n"
            "    Delete it by hand, or the next switch will not take a fresh one."
            % (snapshot, exc),
            code,
        )
    return target
