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

    Raises LockBusy immediately if another process holds it.
    """
    fh = open(path, "a+")
    try:
        _acquire(fh)
    except LockBusy:
        fh.close()
        raise
    try:
        yield
    finally:
        _release(fh)
        fh.close()
