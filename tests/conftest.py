"""A fake `claude` on a temporary PATH.

No test may reach a real claude: one exists on this machine and would spend
real quota. The fixture replaces PATH entirely rather than prepending.
"""

import os
import stat
import sys

import pytest

FAKE = """\
#!{python}
import os, sys
n_file = os.environ["FAKE_COUNT_FILE"]
n = 0
if os.path.exists(n_file):
    n = int(open(n_file).read() or 0)
n += 1
open(n_file, "w").write(str(n))

rec = os.environ.get("FAKE_DIR")
if rec:
    with open(os.path.join(rec, "argv-%d.txt" % n), "w") as fh:
        fh.write("\\n".join(sys.argv[1:]))
    with open(os.path.join(rec, "prompt-%d.txt" % n), "w", encoding="utf-8") as fh:
        fh.write(sys.stdin.read())
else:
    sys.stdin.read()

print("fake claude call %d" % n)
out = os.environ.get("FAKE_OUT")
if out:
    print(out)

sf = os.environ.get("FAKE_STATE_FILE")
if sf:
    at = os.environ.get("FAKE_COMPLETE_AT")
    prose = os.environ.get("FAKE_PROSE")
    if prose:
        open(sf, "w", encoding="utf-8").write(
            "TASK_STATUS: IN_PROGRESS\\n\\n## Goal\\n\\n"
            "only then may line 1 say TASK_STATUS: COMPLETE\\n"
        )
    elif at and int(at) == n:
        open(sf, "w", encoding="utf-8").write("TASK_STATUS: COMPLETE\\n")

sys.exit(int(os.environ.get("FAKE_RC", "0")))
"""

# Windows has no #! mechanism, so a "claude" script with a shebang line is not
# executable there. Rather than teach runner.py about that (it must stay OS
# agnostic and just shutil.which("claude") + subprocess.run it), the fixture
# itself grows a second file on Windows: claude.bat, which shells out to the
# real claude.py with the same interpreter this test process is running
# under. runner.py never learns this happened.
FAKE_BAT = '@"{python}" "%~dp0claude.py" %*\r\n'


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / ("claude.py" if os.name == "nt" else "claude")
    exe.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    if os.name == "nt":
        shim = bindir / "claude.bat"
        shim.write_text(FAKE_BAT.format(python=sys.executable), encoding="utf-8")

    recdir = tmp_path / "rec"
    recdir.mkdir()
    count_file = tmp_path / "count.txt"
    # Pre-create at 0: some tests (lock contention) assert _count(fake) == 0
    # without claude ever running, and _count() does a bare read_text() with
    # no exists() guard.
    count_file.write_text("0")
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setenv("FAKE_DIR", str(recdir))
    monkeypatch.setenv("FAKE_COUNT_FILE", str(count_file))
    return type("F", (), {"dir": recdir, "count_file": count_file,
                          "exe": exe})()
