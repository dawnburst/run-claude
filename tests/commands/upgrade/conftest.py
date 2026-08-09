"""Fixtures for the `lmi upgrade` suite.

pip is never found on PATH - it is always `<interpreter> -m pip` - so the seam
is the interpreter. `fake_pip` gives you one that records argv and answers
`index versions`, and an Installation pointing at it. Nothing here may reach a
real pip or a real index: a real one would install a real package over the
developer's own lmi.
"""

import os
import stat
import sys

import pytest

from lmi.commands.upgrade import installation

FAKE_PIP = """\
#!{python}
import os, sys

n_file = os.environ["FAKE_PIP_COUNT"]
n = 0
if os.path.exists(n_file):
    n = int(open(n_file).read() or 0)
n += 1
open(n_file, "w").write(str(n))

with open(os.path.join(os.environ["FAKE_PIP_DIR"], "argv-%d.txt" % n), "w") as fh:
    fh.write("\\n".join(sys.argv[1:]))

if "index" in sys.argv and "versions" in sys.argv:
    latest = os.environ.get("FAKE_PIP_LATEST")
    if not latest:
        # The shape of a pip too old for the subcommand, which must degrade
        # the question rather than fail the command.
        sys.stderr.write("ERROR: unknown command \\"index\\"\\n")
        sys.exit(2)
    sys.stdout.write("lmi (%s)\\n" % latest)
    sys.stdout.write("Available versions: %s\\n" % latest)
    sys.exit(0)

print("fake pip call %d: %s" % (n, " ".join(sys.argv[1:])))
sys.exit(int(os.environ.get("FAKE_PIP_RC", "0")))
"""

FAKE_SCRIPT = """\
#!{python}
import os, sys
rc = int(os.environ.get("FAKE_SCRIPT_RC", "0"))
if rc:
    sys.stderr.write("boom\\n")
    sys.exit(rc)
sys.stdout.write("lmi %s\\n" % os.environ.get("FAKE_SCRIPT_VERSION", "0.1.0"))
"""


def _executable(path, body):
    path.write_text(body.format(python=sys.executable), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


class Pip:
    def __init__(self, exe, recdir, count_file, script):
        self.exe = exe
        self.dir = recdir
        self.count_file = count_file
        self.script = script

    def calls(self):
        """Every invocation's argv, in order."""
        return [
            (self.dir / ("argv-%d.txt" % i)).read_text(
                encoding="utf-8").splitlines()
            for i in range(1, self.count() + 1)
        ]

    def count(self):
        return int(self.count_file.read_text() or 0)

    def installation(self, kind=installation.VENV, user_flag=False):
        return installation.Installation(
            kind=kind,
            pip_prefix=[str(self.exe), "-m", "pip"],
            user_flag=user_flag,
            script=self.script,
            where=self.exe.parent,
        )


@pytest.fixture
def fake_pip(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = _executable(bindir / "python", FAKE_PIP)
    script = _executable(bindir / "lmi", FAKE_SCRIPT)

    recdir = tmp_path / "piprec"
    recdir.mkdir()
    count_file = tmp_path / "pipcount.txt"
    count_file.write_text("0")

    monkeypatch.setenv("FAKE_PIP_DIR", str(recdir))
    monkeypatch.setenv("FAKE_PIP_COUNT", str(count_file))
    return Pip(exe, recdir, count_file, script)
