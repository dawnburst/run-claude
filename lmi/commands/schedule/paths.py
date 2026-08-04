"""Where the log and the state file go.

The folder-versus-file rules are copied from run-claude.bat's :resolve_log
and are load-bearing: an extension-less path that does not exist yet is a
FOLDER, not a log file. Getting rule 4 wrong makes `-l some/new/logdir`
create a file called logdir instead of a directory.
"""

import os
from datetime import datetime
from pathlib import Path

from ...core import fs
from ...core.errors import EXIT_USAGE, LmiError

TS_FORMAT = "%Y%m%d-%H%M%S"
# The stamp that appears in log lines and in the state template. One
# definition because it is a shared protocol detail: run-claude.bat's logs and
# lmi's are meant to be comparable, so it must not drift between the runner
# and the state file.
NOW_FORMAT = "%Y-%m-%d %H:%M:%S"
STATE_NAME = "run-claude-state.md"
LOG_PREFIX = "run-claude-"


def timestamp():
    """The stamp used in generated file names."""
    return datetime.now().strftime(TS_FORMAT)


def now_str(when=None):
    """The stamp used in log lines and in the state template."""
    return (when or datetime.now()).strftime(NOW_FORMAT)


def has_extension(name):
    """Mirror cmd's %%~xF: a dot after the first character. '.hidden' has none.

    Deliberately not `bool(Path(name).suffix)`, which looks equivalent and is
    not: pathlib reports no suffix for a trailing dot, so 'logs.' and '..'
    would flip from "use as the log file" to "create a directory". cmd's
    %%~xF yields '.' for 'logs.', so this hand-rolled form is the faithful
    one. The suite has no trailing-dot case, so the swap looks safe and is not.
    """
    return "." in name[1:]


def _classify(path, what):
    """fs.classify, but an unanswerable path is a usage error.

    Path.is_dir() raises ENAMETOOLONG rather than returning False, so an
    over-long -l or -s used to crash with a traceback and exit 1 - the code
    that means "a claude call failed". A bad path is exit 2.
    """
    kind, reason = fs.classify(path)
    if kind == fs.UNKNOWN:
        raise LmiError(
            "the %s path cannot be used: %s (%s)" % (what, path, reason),
            EXIT_USAGE,
        )
    return kind


def _expand(raw, what):
    """Path(raw).expanduser().absolute(), without the one way it can explode.

    expanduser() raises RuntimeError for a "~someuser" whose home it cannot
    look up - a typo in -s "~claude/state.md" is enough - and that reached the
    CLI as a traceback and exit 1, the code that means a claude call failed.
    The tilde expansion itself stays: it is what makes a quoted -s "~/x" work,
    since the shell never sees the tilde.
    """
    try:
        return Path(raw).expanduser().absolute()
    except RuntimeError as exc:
        raise LmiError(
            "the %s path cannot be expanded: %s (%s)" % (what, raw, exc),
            EXIT_USAGE,
        )


def _ensure_writable(directory, what, implicit):
    """Fail once, clearly, if we cannot write where this run's files must go.

    Without this the run got as far as the loop and then failed three separate
    times - the lock, the log, the state file - each with its own raw
    "Permission denied", which reads like three faults rather than one wrong
    directory.

    `implicit` says the directory came from the current working directory
    rather than from a flag, which changes the advice: the fix is to pass -d.
    That is the shape of the real report this was written for. On Windows,
    cmd.exe cannot hold a UNC working directory, so launching from
    \\\\wsl.localhost\\... silently leaves the process in C:\\Windows - and lmi
    then aimed its state file, log and lock at C:\\Windows. Denied there, which
    is lucky; a writable system directory would have been scribbled in instead.
    """
    probe = directory / (".lmi-write-test-%d" % os.getpid())
    try:
        probe.touch()
        probe.unlink()
        return
    except OSError as exc:
        # Bound inside the block on purpose: Python 3 deletes the name when the
        # except clause ends, so it cannot be read afterwards.
        reason = exc
    if implicit:
        raise LmiError(
            "cannot write to the working directory %s (%s).\n"
            "    That is where the %s would go. Pass -d with a directory you "
            "can write to,\n"
            "    for example: lmi schedule \"...\" -d %s"
            % (directory, reason, what, _example_dir()),
            EXIT_USAGE,
        )
    raise LmiError(
        "cannot write to the folder for the %s: %s (%s)" % (what, directory, reason),
        EXIT_USAGE,
    )


def _example_dir():
    return "C:\\work" if os.name == "nt" else "~/work"


def _ensure_parent(path, what, implicit=None):
    """implicit=None means do not check writability at all.

    Only the state file gets the check. An unwritable *log* must not abort the
    run - Logger deliberately degrades to console-only and warns once, matching
    run-claude.bat, and a guard here would undo that.
    """
    # The .bat attempts the mkdir and only fails if the directory is still
    # missing afterwards; a missing parent is not itself an error.
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if _classify(path.parent, what) != fs.DIR:
        raise LmiError(
            "the folder for the %s does not exist and could not be created: %s"
            % (what, path),
            EXIT_USAGE,
        )
    if implicit is not None:
        _ensure_writable(path.parent, what, implicit)
    return path


def resolve_state(cfg):
    # "implicit" below means the directory came from the working directory
    # rather than from a flag, which is what changes the advice on failure.
    implicit = cfg.state_arg is None
    raw = cfg.state_arg or str(cfg.work_dir / STATE_NAME)
    path = _expand(raw, "state file")
    # A directory would be renamed to <name>.<ts>.bak by the backup step -
    # os.replace happily moves directories - and a state file written in its
    # place, so `-s ~/notes` silently ate a whole folder. The prompt argument
    # already refuses a directory; so does this.
    if _classify(path, "state file") == fs.DIR:
        raise LmiError(
            "the state file path is an existing directory: %s" % path, EXIT_USAGE
        )
    return _ensure_parent(path, "state file", implicit)


def resolve_log(cfg, run_ts):
    name = LOG_PREFIX + run_ts + ".log"
    if cfg.log_arg is None:
        return _ensure_parent(cfg.work_dir / name, "log file")

    raw = cfg.log_arg
    trailing = raw.endswith("/") or raw.endswith("\\")
    path = _expand(raw, "log file")

    # Order matches run-claude.bat's :resolve_log exactly.
    if _classify(path, "log file") == fs.DIR:   # 1 existing directory
        return _ensure_parent(path / name, "log file")
    if trailing:                            # 2 folder, not yet created
        return _ensure_parent(path / name, "log file")
    if has_extension(path.name):            # 3 the log file itself
        return _ensure_parent(path, "log file")
    return _ensure_parent(path / name, "log file")   # 4 otherwise: folder
