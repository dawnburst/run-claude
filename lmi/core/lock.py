"""A single-instance lock that the OS releases when the process dies.

fcntl.flock on Unix, msvcrt.locking on Windows. Both are released by the
kernel on process exit, which is why there is no PID file and no staleness
check here: a hard kill cannot leave a lock behind. run-claude.bat gets the
same property from holding handle 9 open.
"""

import contextlib
import os


class LockBusy(Exception):
    """Another process holds the lock."""


class LockUnusable(Exception):
    """The lock file itself could not be opened - a bad path, not contention.

    Kept distinct from LockBusy so the caller can report it as the user path
    error it is (exit 2) rather than as an internal crash: an unwritable state
    directory fails here, before anything else gets a chance to complain.
    """


if os.name == "nt":
    import msvcrt

    def _acquire(fh):
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise LockBusy()

    def _release(fh):
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def _acquire(fh):
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise LockBusy()

    def _release(fh):
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


@contextlib.contextmanager
def single_instance_lock(path):
    """Hold an exclusive lock on `path` for the duration of the block.

    Raises LockBusy immediately if another process holds it, and LockUnusable
    if the lock file cannot be opened at all.
    """
    try:
        fh = open(path, "a+")
    except OSError as exc:
        raise LockUnusable(str(exc))
    try:
        # msvcrt.locking locks one byte at the CURRENT position, and "a+"
        # positions at end of file. Two runs whose lock files differ in size
        # would then lock different offsets and both proceed, breaking the
        # no-overlap invariant. Byte 0 is the only offset both runs agree on.
        # (fcntl.flock is whole-file and does not care, so this is harmless
        # there - hence no branch.)
        fh.seek(0)
        _acquire(fh)
    except LockBusy:
        fh.close()
        raise
    except OSError as exc:
        fh.close()
        raise LockUnusable(str(exc))
    try:
        yield
    finally:
        _release(fh)
        fh.close()
