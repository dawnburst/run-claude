"""Fixtures for the `lmi install` suite.

`fake_npm` replaces PATH ENTIRELY rather than prepending, exactly as the
schedule suite's fake_claude does: a real npm exists on a developer machine
and would otherwise win, rewriting their own ~/.npmrc and installing a real
package from a real registry.
"""

import os
import stat
import sys

import pytest

FAKE_NPM = """\
#!{python}
import os, sys

n_file = os.environ["FAKE_NPM_COUNT"]
n = 0
if os.path.exists(n_file):
    n = int(open(n_file).read() or 0)
n += 1
open(n_file, "w").write(str(n))

with open(os.path.join(os.environ["FAKE_NPM_DIR"], "argv-%d.txt" % n), "w") as fh:
    fh.write("\\n".join(sys.argv[1:]))

print("fake npm call %d: %s" % (n, " ".join(sys.argv[1:])))

# Fail only when a global-scope flag is present (--global or its synonym -g),
# which is how the EACCES fallback that a root-owned global npmrc produces is
# exercised without needing root.
if os.environ.get("FAKE_NPM_FAIL_GLOBAL") and (
    "--global" in sys.argv or "-g" in sys.argv
):
    sys.exit(243)

sys.exit(int(os.environ.get("FAKE_NPM_RC", "0")))
"""

# Windows has no #! mechanism, so a script with a shebang is not executable
# there. The fixture grows npm.cmd, the way the schedule suite grows claude.bat.
FAKE_CMD = '@"{python}" "%~dp0npm.py" %*\r\n'


class Npm:
    def __init__(self, recdir, count_file):
        self.dir = recdir
        self.count_file = count_file

    def calls(self):
        """Every invocation's argv, in order."""
        out = []
        for i in range(1, self.count() + 1):
            text = (self.dir / ("argv-%d.txt" % i)).read_text(encoding="utf-8")
            out.append(text.splitlines())
        return out

    def count(self):
        return int(self.count_file.read_text() or 0)


@pytest.fixture
def fake_npm(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / ("npm.py" if os.name == "nt" else "npm")
    exe.write_text(FAKE_NPM.format(python=sys.executable), encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    if os.name == "nt":
        (bindir / "npm.cmd").write_text(
            FAKE_CMD.format(python=sys.executable), encoding="utf-8"
        )

    recdir = tmp_path / "npmrec"
    recdir.mkdir()
    count_file = tmp_path / "npmcount.txt"
    count_file.write_text("0")

    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setenv("FAKE_NPM_DIR", str(recdir))
    monkeypatch.setenv("FAKE_NPM_COUNT", str(count_file))
    return Npm(recdir, count_file)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway HOME, so no test can touch the developer's real ~/.claude."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    return h
