"""Fixtures shared by the whole suite.

`fake_claude` is the important one: no test may reach a real claude, since one
exists on this machine and would spend real quota, so the fixture replaces PATH
entirely rather than prepending.
"""

import os
import stat
import sys

import pytest

# One definition for every permission test. os.geteuid is Unix-only and a
# skipif argument is evaluated at import time, so a bare os.geteuid() call makes
# the whole module raise AttributeError during collection on Windows, silently
# losing every test in it.
skip_as_root = pytest.mark.skipif(
    getattr(os, "geteuid", lambda: 1)() == 0,
    reason="root ignores file permissions",
)


@pytest.fixture
def readonly_dir(tmp_path):
    """A directory that cannot be written to.

    Restored to 0o700 on teardown, without which pytest cannot clean tmp_path
    up - which is why this is a fixture rather than seven try/finally blocks.
    """
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    yield ro
    ro.chmod(0o700)

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

stream = os.environ.get("FAKE_STREAM")
if stream:
    # Speak stream-json, the way `claude -p --output-format stream-json` does,
    # so the -v path is exercised through the renderer rather than through its
    # non-JSON fallback.
    import json as _json
    def emit(event):
        sys.stdout.write(_json.dumps(event) + "\\n")
        sys.stdout.flush()
    emit({{"type": "system", "subtype": "init", "model": "fake-model",
           "session_id": "s%d" % n, "cwd": os.getcwd()}})
    emit({{"type": "assistant", "message": {{"content": [
        {{"type": "text", "text": "fake claude call %d" % n}}]}}}})

    marker = os.environ.get("FAKE_LIVE_MARKER")
    if marker:
        # Liveness: block until the runner has LOGGED the line above. Under a
        # capture-then-replay implementation nothing is logged until this
        # process exits, so the marker never appears and the second event is
        # never emitted - which is exactly what the test asserts on. Bounded,
        # so a regression fails cleanly instead of hanging the suite.
        import time as _time
        deadline = _time.time() + 5.0
        while not os.path.exists(marker) and _time.time() < deadline:
            _time.sleep(0.01)
        # Only if the marker really appeared. Emitting it either way would
        # make the test pass under capture-then-replay too - it would simply
        # wait out the deadline first - which is a false green, not a test.
        if os.path.exists(marker):
            emit({{"type": "assistant", "message": {{"content": [
                {{"type": "tool_use", "name": "Edit",
                  "input": {{"file_path": "after-the-marker.py"}}}}]}}}})

    tail = os.environ.get("FAKE_STREAM_QUOTA_TAIL")
    if tail:
        # The wording placed PAST the renderer's clip width, which is what a
        # real long explanation from claude looks like. The raw JSON line
        # carries it; the rendered line cannot. That is what makes the [QUOTA]
        # test discriminate between scanning the raw line and the rendered
        # one - with a short message both scans find it, and the test is a
        # false green.
        emit({{"type": "assistant", "message": {{"content": [
            {{"type": "text", "text": ("padding " * 40) + tail}}]}}}})

    emit({{"type": "result", "subtype": "success", "is_error": False,
           "num_turns": 2, "duration_ms": 1234,
           "result": os.environ.get("FAKE_STREAM_RESULT", "done")}})
else:
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
    elif os.environ.get("FAKE_BLANK_FIRST_LINE"):
        # Landmine 14, the shape the ^-anchored regex CAN match: line 1 is
        # blank, line 2 says COMPLETE. A whole-file search matches it because
        # ^\\s* happily spans the newline; a line-1-only read does not.
        open(sf, "w", encoding="utf-8").write(
            "\\nTASK_STATUS: COMPLETE\\n\\n## Goal\\n\\nnot really done\\n"
        )
    elif at and int(at) == n:
        open(sf, "w", encoding="utf-8").write("TASK_STATUS: COMPLETE\\n")

if os.environ.get("FAKE_WRECK_TMP"):
    # Delete the runner's whole temp workspace, prompt file and all, the way a
    # cleanup script or an over-eager tmpreaper would. The next iteration then
    # cannot write its prompt - the case that used to abort the loop.
    import glob, shutil, tempfile
    for d in glob.glob(os.path.join(tempfile.gettempdir(), "lmi-schedule-*")):
        shutil.rmtree(d, ignore_errors=True)

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
