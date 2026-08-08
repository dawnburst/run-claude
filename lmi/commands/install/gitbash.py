"""Finding Git Bash on Windows, and persisting CLAUDE_CODE_GIT_BASH_PATH.

Windows only, and not "runs and no-ops elsewhere" - Claude Code resolves this
variable through require("path/win32") and never reads it on Linux or macOS, so
probing there would be noise and writing the key into settings.json would put a
meaningless line in a file the user reads.

Claude Code's own auto-detection checks exactly two paths, so a Git installed
anywhere else is invisible to it. That is what makes searching harder here
worth doing - and also why every candidate is validated the same way Claude
Code validates: it requires the basename to be bash/sh AND the file to exist,
and warns and ignores the variable otherwise. Writing a path it rejects is
worse than writing nothing, because it looks configured.
"""

import os
import shutil
import subprocess
from pathlib import Path

from ...core import fs

VAR = "CLAUDE_CODE_GIT_BASH_PATH"

# Exactly the set Claude Code accepts. Do not widen it.
VALID_NAMES = ("bash.exe", "sh.exe", "bash", "sh")


def on_windows():
    """os.name == "nt", in a form a test can override.

    Monkeypatching os.name itself is not an option: pathlib chooses its concrete
    class from it at instantiation, so setting it to "nt" on Linux makes every
    Path() raise NotImplementedError - including pytest's own.
    """
    return os.name == "nt"


def is_valid(path):
    """Would Claude Code honour this path?"""
    if not path:
        return False
    if Path(path).name.lower() not in VALID_NAMES:
        return False
    # fs.kind, not Path.is_file(): an over-long path raises ENAMETOOLONG rather
    # than returning False, and a user-typed answer can be anything.
    return fs.kind(path) == fs.FILE


def candidates():
    """Every place to look, best first. Empty off Windows."""
    if not on_windows():
        return []

    found = []
    existing = os.environ.get(VAR)
    if existing:
        found.append(existing)

    # Authoritative: this is what the Git for Windows installer records.
    found.extend(_registry_paths())

    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)",
                                       r"C:\Program Files (x86)")
    found.append(str(Path(program_files) / "Git" / "bin" / "bash.exe"))
    found.append(str(Path(program_files_x86) / "Git" / "bin" / "bash.exe"))
    found.append(str(Path(program_files) / "Git" / "usr" / "bin" / "bash.exe"))

    # A per-user Git install needs no admin, so it is common on locked-down
    # machines - and it is one Claude Code cannot find on its own.
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        found.append(
            str(Path(local_appdata) / "Programs" / "Git" / "bin" / "bash.exe")
        )

    git = shutil.which("git")
    if git:
        # git.exe lives in <root>\cmd\ or <root>\bin\; bash is in <root>\bin\.
        found.append(str(Path(git).parent.parent / "bin" / "bash.exe"))

    return found


def find():
    """The first candidate Claude Code would accept, or None."""
    for candidate in candidates():
        if is_valid(candidate):
            return candidate
    return None


def persist(path, say):
    """Set CLAUDE_CODE_GIT_BASH_PATH for future shells. True if it took.

    setx rather than a raw winreg write because setx broadcasts WM_SETTINGCHANGE
    itself. Its 1024-byte truncation - the trap pylmi walks into - applies to
    PATH, an accumulated list; this value is a single short path. lmi never uses
    setx for PATH.

    Never raises. npm has already succeeded by the time this runs, so a failure
    here is a warning, not a failed installation.
    """
    if not on_windows():
        return False
    try:
        code = subprocess.run(["setx", VAR, path]).returncode
    except OSError as exc:
        say("[WARN] could not run setx to set %s (%s)" % (VAR, exc))
        return False
    if code != 0:
        say("[WARN] setx %s failed (exit %d). The value is still written into "
            "settings.json, so claude will pick it up." % (VAR, code))
        return False
    return True


def _registry_paths():
    """InstallPath from HKLM\\SOFTWARE\\GitForWindows, 64- and 32-bit views.

    Its own module-level function so a test can replace it wholesale: winreg
    does not exist off Windows, and importing it is the only Windows-specific
    import in the package.
    """
    try:
        import winreg
    except ImportError:
        return []

    found = []
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GitForWindows", 0,
                winreg.KEY_READ | view,
            )
        except OSError:
            continue
        try:
            root, _ = winreg.QueryValueEx(key, "InstallPath")
        except OSError:
            root = None
        finally:
            winreg.CloseKey(key)
        if root:
            found.append(str(Path(root) / "bin" / "bash.exe"))
    return found
