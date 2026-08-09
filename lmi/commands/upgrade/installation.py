"""Which lmi installation is this process running from?

Answered before anything else happens and before the user is asked anything,
because a wrong answer is silent: pip reports success, the command still runs,
and it is either the old code or a second copy that nothing on PATH ever reaches.

Every fact this module needs comes from its own one-line helper, so a test can
replace the fact rather than sys itself - the same reason schedule/paths.py has
_on_windows instead of reading os.name where it is used.

The order of the checks in detect() is load-bearing. An editable checkout is
almost always *also* inside a virtual environment, so the venv rule would claim
it if it went first.
"""

import json
import os
import shutil
import site
import subprocess
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import List

from ...core.errors import EXIT_USAGE, LmiError

VENV = "venv"
USER_SITE = "user site"

EDITABLE = (
    "this lmi is an editable install (pip install -e) from %s.\n"
    "    `lmi upgrade` will not install a released wheel over a working tree:\n"
    "    it would look exactly like a successful upgrade and replace whatever\n"
    "    is uncommitted there.\n"
    "    Use git in that checkout, or install a wheel somewhere else."
)

PIPX = (
    "this lmi was installed by pipx (%s).\n"
    "    Upgrading it from underneath pipx leaves pipx's own record describing\n"
    "    a version that is no longer installed. Use pipx instead:\n\n"
    "        pipx upgrade lmi\n"
)

UNSUPPORTED = (
    "lmi is installed somewhere `lmi upgrade` does not know how to replace:\n"
    "      package:     %s\n"
    "      interpreter: %s\n"
    "    It upgrades the two installations the install scripts produce - a\n"
    "    virtual environment of its own, and a `pip install --user` - and\n"
    "    refuses anything else rather than guessing, because a wrong guess\n"
    "    installs a second copy that nothing on PATH ever reaches.\n"
    "    Re-install with scripts/install-linux.sh, install-macos.sh or\n"
    "    install-windows.cmd, or upgrade with pip yourself."
)

NO_PIP = (
    "the virtual environment at %s has no pip, and no python3 outside it could\n"
    "    be found to lend one.\n"
    "    On Debian and Ubuntu this is one missing package:\n\n"
    "        sudo apt install python3-venv\n"
)


@dataclass(frozen=True)
class Installation:
    kind: str
    pip_prefix: List[str]   # argv up to but not including "install"
    user_flag: bool         # whether pip needs --user
    script: Path            # the installed `lmi` command, for verification
    where: Path             # what to name in messages


def detect():
    """The installation to upgrade, or a usage error saying why not."""
    if _editable():
        raise LmiError(EDITABLE % _package_dir(), EXIT_USAGE)

    marker = _prefix() / "pipx_metadata.json"
    if marker.exists():
        raise LmiError(PIPX % _prefix(), EXIT_USAGE)

    package = _package_dir()
    if _prefix() != _base_prefix() and _within(package, _prefix()):
        return _venv_installation()
    if _within(package, _user_site_dir()):
        return _user_installation()
    raise LmiError(UNSUPPORTED % (package, _executable()), EXIT_USAGE)


def _venv_installation():
    python = _executable()
    script = _scripts_dir() / _script_name()
    if _has_pip(python):
        prefix = [str(python), "-m", "pip"]
    else:
        # Debian and Ubuntu ship venv's bootstrap separately, so a venv created
        # with --without-pip has none of its own. A pip outside it can still
        # populate it: --python must come before the subcommand and needs pip
        # 22.3 or newer. install-linux.sh does exactly this.
        base = _base_python()
        if base is None:
            raise LmiError(NO_PIP % _prefix(), EXIT_USAGE)
        prefix = [str(base), "-m", "pip", "--python", str(python)]
    return Installation(VENV, prefix, False, script, _prefix())


def _user_installation():
    return Installation(
        USER_SITE,
        [str(_executable()), "-m", "pip"],
        True,
        _user_scripts_dir() / _script_name(),
        _user_site_dir(),
    )


# --- the facts, each replaceable by a test --------------------------------

def _package_dir():
    """Where the lmi package being run was imported from."""
    import lmi
    return Path(lmi.__file__).resolve().parent


def _prefix():
    return Path(sys.prefix)


def _base_prefix():
    return Path(getattr(sys, "base_prefix", sys.prefix))


def _executable():
    return Path(sys.executable)


def _scripts_dir():
    """This environment's console-script directory - bin/ or Scripts\\."""
    return Path(sysconfig.get_path("scripts"))


def _user_scripts_dir():
    r"""The --user console-script directory.

    From sysconfig, deliberately not %APPDATA%\Python\PythonXX\Scripts: the
    answer differs between installs, and a Microsoft Store Python inserts a
    version level. install-windows.ps1 asks the same question the same way.
    """
    if hasattr(sysconfig, "get_preferred_scheme"):
        scheme = sysconfig.get_preferred_scheme("user")
    else:
        scheme = "nt_user" if _on_windows() else "posix_user"
    return Path(sysconfig.get_path("scripts", scheme))


def _user_site_dir():
    return Path(site.getusersitepackages())


def _script_name():
    return "lmi.exe" if _on_windows() else "lmi"


def _on_windows():
    """os.name == "nt", in a form a test can override.

    Monkeypatching os.name itself is not an option: pathlib chooses its
    concrete class from it at instantiation, so setting it to "nt" on Linux
    makes every Path() raise NotImplementedError - including pytest's own.
    """
    return os.name == "nt"


def _editable():
    """Does this lmi's install record say it is editable?

    direct_url.json with dir_info.editable is what pip writes for
    `pip install -e`. Any failure to read it means "not editable" - a source
    tree with no install record at all lands in UNSUPPORTED below, which says
    more.
    """
    try:
        from importlib import metadata
        raw = metadata.distribution("lmi").read_text("direct_url.json")
    except Exception:                       # noqa: BLE001 - any failure is "no"
        return False
    if not raw:
        return False
    try:
        doc = json.loads(raw)
    except ValueError:
        return False
    info = doc.get("dir_info")
    return bool(isinstance(info, dict) and info.get("editable"))


def _has_pip(python):
    try:
        done = subprocess.run(
            [str(python), "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return done.returncode == 0


def _base_python():
    """A python outside this venv, to lend it a pip. None if there is none."""
    candidate = getattr(sys, "_base_executable", None)
    if candidate and Path(candidate) != _executable():
        return Path(candidate)
    found = shutil.which("python3") or shutil.which("python")
    return Path(found) if found else None


def _within(child, parent):
    """Is `child` inside `parent`? Never raises for an odd path."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False
