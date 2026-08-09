"""Reading, backing up and atomically writing one JSON document.

Nothing here knows what Claude Code is, which is why it lives in core/ rather
than in the command that first needed it. It was promoted out of
commands/install/ when `lmi config switch` became the second caller - the
moment CLAUDE.md section 2 names for promoting, rather than in advance.

Every function takes the exit `code` to raise with, because core/ cannot know
a command's codes and two commands must be free to disagree about them. Both
current callers pass 3.

Every write is atomic - a temp file beside the target, then os.replace, which
is atomic on POSIX and on Windows. A half-written settings.json is invalid
JSON and Claude Code cannot start without it.
"""

import json
import os
import shutil
import stat as _stat
from datetime import datetime

from . import fs, text
from .errors import LmiError

# Re-declared rather than imported from commands/schedule/paths.py: commands do
# not import each other, and promoting a format string to core/ in advance is
# the thing the architecture rule warns against.
TS_FORMAT = "%Y%m%d-%H%M%S"

BACKUP_SUFFIX = ".bk_"


def timestamp():
    return datetime.now().strftime(TS_FORMAT)


def read(path, what, code):
    """The document, or {} when the file is absent or empty.

    An unparseable file is an error rather than an empty document: treating it
    as {} would write over settings the user hand-edited and silently discard
    every one of them.
    """
    if fs.kind(path) != fs.FILE:
        return {}
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LmiError(
            "the %s file cannot be read: %s (%s)" % (what, path, exc),
            code,
        )
    if not raw.strip():
        return {}
    try:
        doc = json.loads(text.decode_with_bom(raw))
    except (UnicodeDecodeError, ValueError) as exc:
        raise LmiError(
            "the %s file is not valid JSON: %s (%s)\n"
            "    Refusing to overwrite it - fix or move the file and run this "
            "again." % (what, path, exc),
            code,
        )
    if not isinstance(doc, dict):
        raise LmiError(
            "the %s file must contain a JSON object: %s\n"
            "    Refusing to overwrite it." % (what, path),
            code,
        )
    return doc


def backup(path, stamp, what, code):
    """Copy `path` beside itself as <name>.bk_<stamp>. None if there is nothing.

    copy2, not copy: it preserves the mode, and ~/.claude.json is 0600 and holds
    per-project history. A backup at the default 0644 would publish it.
    """
    if fs.kind(path) != fs.FILE:
        return None
    dest = path.with_name(path.name + BACKUP_SUFFIX + stamp)
    try:
        shutil.copy2(str(path), str(dest))
    except OSError as exc:
        raise LmiError(
            "could not back up the %s file: %s -> %s (%s)\n"
            "    Nothing was changed: modifying a file we cannot preserve is "
            "not worth the risk." % (what, path, dest, exc),
            code,
        )
    return dest


def write(path, doc, what, code, mode=None):
    """Replace `path` with `doc`, atomically.

    `mode` forces a permission; without it an existing file's mode is preserved.

    The temp file is *created* 0600, rather than created at the umask default
    and chmod-ed once the content is in it. settings.json can hold an auth
    token, and open() followed by a later chmod leaves that token in a
    world-readable file for the whole duration of the write - ~/.claude/ is
    0755, so every user on the box can read it while it is being written.

    Born private, then relaxed. The chmod before os.replace stays, and is not
    redundant: `effective` may be WIDER than 0600 - 0644 for a settings.json
    with no token in it - and widening after the content is written is safe
    where narrowing after would not be. It must also stay BEFORE the replace,
    so the document never becomes visible under its real name at the wrong mode.

    A file created from nothing therefore ends up 0600 rather than at the umask
    default, since there is no `existing` mode to relax to. Deliberate: both
    documents this command writes may hold a credential or the user's project
    history, and neither has a reason to be group- or world-readable.
    """
    existing = _mode_of(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Not fatal on its own - the open below produces the better message.
        pass

    tmp = path.with_name("%s.lmi-tmp-%d" % (path.name, os.getpid()))
    # O_BINARY where it exists (Windows only): an fd opened in the CRT's text
    # mode translates "\n" to "\r\n" underneath the io layer, which would undo
    # newline="\n" below. It is absent on POSIX, where getattr yields 0.
    flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(str(tmp), flags, 0o600)
        # fdopen, not open(), so the descriptor carries the 0600 from creation.
        # Not Path.write_text(newline=...): that parameter arrived in 3.10 and
        # the floor here is 3.9.
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        effective = mode if mode is not None else existing
        if effective is not None:
            os.chmod(str(tmp), effective)
        os.replace(str(tmp), str(path))
    except OSError as exc:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise LmiError(
            "could not write the %s file: %s (%s)" % (what, path, exc),
            code,
        )


def _mode_of(path):
    if fs.kind(path) != fs.FILE:
        return None
    try:
        return _stat.S_IMODE(os.stat(str(path)).st_mode)
    except OSError:
        return None
