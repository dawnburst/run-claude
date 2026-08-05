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
            "    for example: lmi schedule \"...\" -d %s%s"
            % (directory, reason, what, _example_dir(), _cmd_unc_hint(directory)),
            EXIT_USAGE,
        )
    raise LmiError(
        "cannot write to the folder for the %s: %s (%s)" % (what, directory, reason),
        EXIT_USAGE,
    )


def _example_dir():
    return "C:\\work" if os.name == "nt" else "~/work"


def _cmd_unc_hint(directory):
    r"""Name the real cause when the working directory is the Windows directory.

    A cmd.exe started in a \\server\share folder cannot hold that directory, so
    it prints a notice and substitutes the Windows directory - and by the time
    lmi runs, the UNC path is gone from the environment entirely and the UNC
    guard cannot see it. All that is left is an unwritable C:\Windows, which on
    its own reads like a bizarre choice of working directory rather than the
    consequence it is. Verified: a cmd launched in a \\wsl.localhost\... folder
    reports exactly this.
    """
    if not _on_windows():
        return ""
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or ""
    if not root:
        return ""
    here = str(directory).rstrip("\\").lower()
    root = root.rstrip("\\").lower()
    if here not in (root, root + "\\system32"):
        return ""
    return (
        "\n    If you started cmd in a \\\\server\\share folder, that is the "
        "cause: cmd.exe\n"
        "    cannot hold a UNC working directory and silently substitutes this "
        "one.\n"
        "    Note lmi cannot keep its state file on a share either - see "
        "-s in --help."
    )


def _on_windows():
    """os.name == "nt", in a form a test can override.

    Monkeypatching os.name itself is not an option: pathlib chooses its concrete
    class from it at instantiation, so setting it to "nt" on Linux makes every
    Path() raise NotImplementedError - including pytest's own.
    """
    return os.name == "nt"


def _reject_unc(path, implicit):
    r"""Refuse a state file on a Windows network share, before anything runs.

    The lock file is created next to the state file, and Windows byte-range
    locking is not supported on a share: on a WSL 9p mount msvcrt.locking fails
    with EINVAL, and core.lock cannot tell that apart from a lock somebody else
    holds. The result was a run that reported exit 3, "another run is working on
    this state file", with nothing else running at all - a phantom that took a
    measurement to explain. Failing here says what is actually wrong.

    Only the state file is rejected, deliberately: the log is written and never
    locked, and claude itself is happy with a UNC working directory. So keeping
    the working directory on the share and moving just the state file with -s is
    a real escape hatch, and the message offers it.

    Windows only. On POSIX a //-prefixed path is local and locks correctly.
    """
    if not _on_windows() or not fs.looks_like_unc(path):
        return
    if implicit:
        raise LmiError(
            "the working directory is on a network share (UNC path): %s\n"
            "    That is where the state file and its lock file would go, and "
            "Windows cannot\n"
            "    lock a file on a share - the attempt fails with \"Invalid "
            "argument\", which is\n"
            "    indistinguishable from another run holding the lock.\n"
            "    Either work from a local drive, or keep this working directory "
            "and put the\n"
            "    state file somewhere local:\n"
            "        lmi schedule \"...\" -s C:\\lmi\\run-claude-state.md"
            % path.parent, EXIT_USAGE,
        )
    raise LmiError(
        "the state file is on a network share (UNC path): %s\n"
        "    Its lock file goes in the same folder, and Windows cannot lock a "
        "file on a\n"
        "    share. Choose a path on a local drive, for example "
        "C:\\lmi\\run-claude-state.md."
        % path, EXIT_USAGE,
    )


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
    # Before touching the filesystem: a share cannot hold the lock, and finding
    # that out at lock time produced a phantom "another run is working on this
    # state file" instead of a diagnosis.
    _reject_unc(path, implicit)
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
