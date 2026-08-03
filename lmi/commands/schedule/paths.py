"""Where the log and the state file go.

The folder-versus-file rules are copied from run-claude.bat's :resolve_log
and are load-bearing: an extension-less path that does not exist yet is a
FOLDER, not a log file. Getting rule 4 wrong makes `-l some/new/logdir`
create a file called logdir instead of a directory.
"""

from datetime import datetime
from pathlib import Path

from ...core.errors import EXIT_USAGE, LmiError

TS_FORMAT = "%Y%m%d-%H%M%S"
STATE_NAME = "run-claude-state.md"
LOG_PREFIX = "run-claude-"


def timestamp():
    return datetime.now().strftime(TS_FORMAT)


def has_extension(name):
    """Mirror cmd's %%~xF: a dot after the first character. '.hidden' has none."""
    return "." in name[1:]


def _ensure_parent(path, what):
    # The .bat attempts the mkdir and only fails if the directory is still
    # missing afterwards; a missing parent is not itself an error.
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if not path.parent.is_dir():
        raise LmiError(
            "the folder for the %s does not exist and could not be created: %s"
            % (what, path),
            EXIT_USAGE,
        )
    return path


def resolve_state(cfg):
    raw = cfg.state_arg or str(cfg.work_dir / STATE_NAME)
    return _ensure_parent(Path(raw).expanduser().absolute(), "state file")


def resolve_log(cfg, run_ts):
    name = LOG_PREFIX + run_ts + ".log"
    if cfg.log_arg is None:
        return _ensure_parent(cfg.work_dir / name, "log file")

    raw = cfg.log_arg
    trailing = raw.endswith("/") or raw.endswith("\\")
    path = Path(raw).expanduser().absolute()

    # Order matches run-claude.bat's :resolve_log exactly.
    if path.is_dir():                       # 1 existing directory
        return _ensure_parent(path / name, "log file")
    if trailing:                            # 2 folder, not yet created
        return _ensure_parent(path / name, "log file")
    if has_extension(path.name):            # 3 the log file itself
        return _ensure_parent(path, "log file")
    return _ensure_parent(path / name, "log file")   # 4 otherwise: folder
