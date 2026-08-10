"""The statusline script: finding it, and copying it into ~/.claude.

A `settings.json` may carry a `statusLine` block whose command runs a script -
the shipped template runs `node ~/.claude/statusline.js`. The settings document
alone cannot put that script there, so this module carries the second half:
a **statusline.js beside the lmi.json that discovery resolved**, installed as
`~/.claude/statusline.js` byte for byte.

Beside the config file, exactly like the settings template and for the same
reason: `--config /site/lmi.json` gets `/site/statusline.js`, so one folder is
one site and a template can never be paired with another site's script. Not
shipped inside the `lmi` package, which would give every site the same
statusline and no way to vary it; not read from the checkout's `scripts/`,
which does not exist once lmi is installed from a wheel.

Unlike the template it is **optional** - a site that wants no statusline simply
has no such file, and an existing config folder keeps working untouched. What
is not allowed is for the two halves to disagree in silence, so the runner says
out loud when a template declares a `statusLine` and no script was found, and
when a script was found and the template declares no `statusLine`. Neither is
an error: only the operator knows whether the command points at this file.

`declares` lives here rather than in template._validate on purpose. That
validator's contract is that every key but `env` passes through unexamined, and
a warning is not validation - nothing here can reject a template, and a site
whose `statusLine` runs something else entirely still installs cleanly.
"""

import os

from ...core import fs
from ...core.claude import config_dir
from ...core.errors import EXIT_USAGE, LmiError

# Beside the lmi.json that discovery resolved - see template.NAME.
NAME = "statusline.js"

# The settings.json key whose presence means the operator wants a statusline.
SETTINGS_KEY = "statusLine"


def find(config_path):
    """The statusline script beside `config_path`, or None if there is none.

    None is a normal outcome, not a failure: the file is optional. An
    unanswerable path is still exit 2, because a path lmi cannot classify is a
    question the operator has to settle.
    """
    path = config_path.parent / NAME
    kind, reason = fs.classify(path)
    if kind == fs.UNKNOWN:
        raise LmiError(
            "the statusline script path cannot be used: %s (%s)" % (path, reason),
            EXIT_USAGE,
        )
    return path if kind == fs.FILE else None


def declares(template):
    """True when the settings template asks for a statusline at all."""
    return isinstance(template, dict) and SETTINGS_KEY in template


def path():
    """~/.claude/statusline.js - where the template's command expects it."""
    return config_dir() / NAME


def install(src, dest, what, code):
    """Copy `src` over `dest`, atomically and byte for byte.

    Bytes, not text: this is somebody's script and lmi has no business
    normalising its line endings, its encoding or its trailing newline. A
    statusline whose CRLF became LF on the way through is a script lmi edited
    without being asked to.

    Atomic for the same reason jsonfile.write is: a half-copied statusline.js
    is a syntax error that Claude Code runs on every keystroke, and the window
    for it is a `settings.json` that already names the file.
    """
    try:
        data = src.read_bytes()
    except OSError as exc:
        raise LmiError(
            "the %s cannot be read: %s (%s)" % (what, src, exc), EXIT_USAGE
        )

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Not fatal on its own - the open below produces the better message.
        pass

    tmp = dest.with_name("%s.lmi-tmp-%d" % (dest.name, os.getpid()))
    # O_BINARY where it exists (Windows only), for the reason spelled out in
    # core/jsonfile.py: without it the CRT hands back a text-mode descriptor
    # and rewrites every "\n" on the way out, which is exactly the editing this
    # function promises not to do.
    flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(str(tmp), flags, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        # chmod rather than a mode argument to os.open, which the umask masks.
        # The source's mode is carried over so a script the operator made
        # executable stays executable - a template may run it directly rather
        # than through `node`.
        mode = _mode_of(src)
        if mode is not None:
            os.chmod(str(tmp), mode)
        os.replace(str(tmp), str(dest))
    except OSError as exc:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise LmiError(
            "could not write the %s: %s (%s)" % (what, dest, exc), code
        )


def _mode_of(path_):
    try:
        return os.stat(str(path_)).st_mode & 0o777
    except OSError:
        return None
