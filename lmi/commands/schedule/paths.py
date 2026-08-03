"""Where the log and the state file go.

The folder-versus-file rules are copied from run-claude.bat's :resolve_log
and are load-bearing: an extension-less path that does not exist yet is a
FOLDER, not a log file. Getting rule 4 wrong makes `-l some/new/logdir`
create a file called logdir instead of a directory.
"""

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


def _ensure_parent(path, what):
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
    return path


def resolve_state(cfg):
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
    return _ensure_parent(path, "state file")


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
