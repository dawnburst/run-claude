"""Asking the filesystem "what is this?" without ever raising.

`pathlib`'s is_dir() / is_file() only look like predicates. They swallow
exactly ENOENT, ENOTDIR, EBADF and ELOOP; every other OSError propagates.
The one that matters in practice is **ENAMETOOLONG**: an inline prompt is
handed straight to the classifier, and any prompt whose longest slash-free
run reaches 256 bytes - a 143-character Hebrew sentence does it - made
`Path(prompt).is_dir()` raise errno 36 as a bare traceback. EACCES on a
parent directory and an embedded NUL (a ValueError, not even an OSError)
behave the same way.

So classification returns a verdict instead of raising, and each caller
decides what an unanswerable path means: for the prompt argument it means
"not a path, treat it as text"; for -l and -s it means a usage error.
"""

import os
import stat as _stat

DIR = "dir"
FILE = "file"
OTHER = "other"        # exists but is neither: fifo, socket, device
MISSING = "missing"    # nothing there, or a dangling symlink
UNKNOWN = "unknown"    # the OS refused to answer - name too long, EACCES, ...


def classify(path):
    """Return (kind, reason). `reason` is the OS message for UNKNOWN, else ""."""
    try:
        st = os.stat(str(path))
    except (FileNotFoundError, NotADirectoryError):
        return MISSING, ""
    except OSError as exc:
        return UNKNOWN, str(exc)
    except ValueError as exc:
        # An embedded NUL byte is a ValueError, not an OSError.
        return UNKNOWN, str(exc)
    if _stat.S_ISDIR(st.st_mode):
        return DIR, ""
    if _stat.S_ISREG(st.st_mode):
        return FILE, ""
    return OTHER, ""


def kind(path):
    return classify(path)[0]
