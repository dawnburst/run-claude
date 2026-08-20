"""Fixtures shared by the whole suite.

`fake_claude` is the important one: no test may reach a real claude, since one
exists on this machine and would spend real quota, so the fixture replaces PATH
entirely rather than prepending.

`fake_pip` lives here rather than under tests/commands/upgrade/ because two
commands now run pip - `lmi upgrade` and `lmi install claude` - and one seam
faked two ways is two descriptions of pip that can drift apart. It moved when
the second caller appeared, which is the rule CLAUDE.md section 2 applies to
lmi/core/, applied to a fixture.
"""

import os
import stat
import sys

import pytest

from lmi.commands.schedule import stream as _stream
from lmi.commands.upgrade import installation

# How many "padding " words FAKE_STREAM_QUOTA_TAIL sits behind.
#
# Derived from the renderer's own widest clip, never hardcoded. The [QUOTA] test
# below works by placing the wording PAST that clip, so that finding the tag
# proves the scan read the raw line; a literal count silently stops proving
# anything the moment a width grows past it, and the test goes green for the
# wrong reason. Widening TEXT_WIDTH is exactly what did that once.
QUOTA_PAD_WORDS = _stream.TEXT_WIDTH // len("padding ") + 40

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

gone = os.environ.get("FAKE_SESSION_GONE")
if gone and int(gone) == n and "--resume" in sys.argv:
    # claude 2.1.235's own wording and exit code for a conversation that is not
    # there, verified by running it. Printed and gone: the lookup is local, so no
    # API call happens - which is what makes the runner's one retry affordable
    # rather than a doubled bill.
    sid = sys.argv[sys.argv.index("--resume") + 1]
    print("No conversation found with session ID: %s" % sid)
    if os.environ.get("FAKE_SESSION_GONE_QUOTA"):
        # Quota wording on the FAILED attempt and nowhere else, which is the only
        # way to tell "the tag survives the retry" from "the retry mentioned it
        # too". With the wording in FAKE_OUT both attempts carry it and the test
        # passes however the two flags are combined - a false green of exactly
        # item 47's kind, found by inverting the guard and watching nothing break.
        print("Claude AI usage limit reached|1234567890")
    sys.exit(1)

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
        # false green. The count comes from QUOTA_PAD_WORDS, which reads the
        # renderer's width, so it cannot fall behind it.
        emit({{"type": "assistant", "message": {{"content": [
            {{"type": "text", "text": ("padding " * {quota_pad}) + tail}}]}}}})

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
    exe.write_text(
        FAKE.format(python=sys.executable, quota_pad=QUOTA_PAD_WORDS),
        encoding="utf-8",
    )
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


# --- pip, for `lmi upgrade` and `lmi install claude` -----------------------
#
# pip is never found on PATH in either command - it is always
# `<interpreter> -m pip` - so the seam is the INTERPRETER, and that is what is
# faked here. A pip on PATH would be the wrong seam twice over: it is not what
# the code looks for, and it is not what decides where a package lands.
#
# The fake answers three different things one interpreter has to answer:
#
#   `-m pip install ...`   the install, recorded and given an exit code
#   `-m pip index versions` the version probe `lmi upgrade` degrades around
#   `-c "import ..."`       the import probe `lmi install claude` decides the
#                           schedule backend with
#
# The last of those is answered BEFORE anything is counted or recorded, so
# `calls()` stays a list of pip invocations only. Otherwise the probe would
# quietly satisfy a test asserting that a failing install is retried exactly
# never - the assertion that keeps the two anti-fallbacks in install/sdk.py
# honest - and that test would pass with a PyPI retry added.

FAKE_PIP = """\
#!{python}
import os, re, sys

# The import probe, answered first and counted separately - see above. Matched
# on argv[1] rather than "-c" anywhere in argv, because pip spells --constraint
# `-c` too and a future flag must not silently turn an install into a probe.
if sys.argv[1:2] == ["-c"]:
    p_file = os.environ.get("FAKE_PROBE_COUNT")
    if p_file:
        p = 0
        if os.path.exists(p_file):
            p = int(open(p_file).read() or 0)
        open(p_file, "w").write(str(p + 1))
    with open(os.path.join(os.environ["FAKE_PIP_DIR"], "probe.txt"), "a") as fh:
        fh.write(sys.argv[2] + "\\n")
    # Absent means NOT importable, deliberately: nothing is installed on a
    # fresh machine, and a fake whose default is "yes" would let the mode be
    # decided by pip's exit code in every test that forgot to say otherwise.
    sys.exit(0 if os.environ.get("FAKE_IMPORTABLE") else 1)

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

# Per-package failure, in FAKE_NPM_FAIL_GLOBAL's shape: an index that carries
# one package and not another is the real case both commands have to survive,
# and FAKE_PIP_RC alone can only fail every call.
# Matched against the DISTRIBUTION NAME, with any version specifier stripped,
# so the knob means "this index does not carry that package" and a caller does
# not have to know how the requirement happens to be pinned today. `lmi install
# claude` asks pip for `claude-agent-sdk>=X` rather than a bare name, and an
# exact argv comparison here silently stopped firing the moment that pin
# arrived - a fake that quietly no longer fails is a test asserting nothing.
fail = os.environ.get("FAKE_PIP_FAIL_PACKAGE")
if fail:
    names = [re.split(r"[<>=!~\\[]", arg, 1)[0] for arg in sys.argv[1:]]
    if fail in names:
        sys.stderr.write(
            "ERROR: No matching distribution found for %s\\n" % fail
        )
        sys.exit(1)

sys.exit(int(os.environ.get("FAKE_PIP_RC", "0")))
"""

FAKE_SCRIPT = """\
#!{python}
import os, sys

# FAKE_SCRIPT_STDERR: an extra line written to stderr BEFORE the version line
# on stdout - a DeprecationWarning, a .pth file's own output, a locale
# complaint - the shape that used to become "line 0" and fail verification
# when stdout and stderr were merged.
stderr_line = os.environ.get("FAKE_SCRIPT_STDERR")
if stderr_line:
    sys.stderr.write(stderr_line + "\\n")

# FAKE_SCRIPT_BOM and FAKE_SCRIPT_PREFIX: a UTF-8 BOM or odd leading
# whitespace ahead of "lmi" itself on the version line.
bom = "\\ufeff" if os.environ.get("FAKE_SCRIPT_BOM") else ""
prefix = os.environ.get("FAKE_SCRIPT_PREFIX", "")
version = os.environ.get("FAKE_SCRIPT_VERSION", "0.1.0")
sys.stdout.write("%s%slmi %s\\n" % (bom, prefix, version))

# The version line is written above UNCONDITIONALLY, so FAKE_SCRIPT_RC can
# exercise "printed a version line and then still exited non-zero" - the
# returncode check must keep winning over a matched version line.
rc = int(os.environ.get("FAKE_SCRIPT_RC", "0"))
if rc:
    sys.stderr.write("boom\\n")
    sys.exit(rc)
"""


def _executable(path, body):
    path.write_text(body.format(python=sys.executable), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


class Pip:
    def __init__(self, exe, recdir, count_file, probe_file, script):
        self.exe = exe
        self.dir = recdir
        self.count_file = count_file
        self.probe_file = probe_file
        self.script = script

    def calls(self):
        """Every pip invocation's argv, in order. Import probes are not pip."""
        return [
            (self.dir / ("argv-%d.txt" % i)).read_text(
                encoding="utf-8").splitlines()
            for i in range(1, self.count() + 1)
        ]

    def count(self):
        return int(self.count_file.read_text() or 0)

    def probes(self):
        """The source of every `-c` the interpreter was asked to run."""
        path = self.dir / "probe.txt"
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8").splitlines()

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
    """A fake interpreter, plus a fake installed `lmi` console script.

    Its directory is deliberately not tmp_path/"bin": fake_npm owns that name,
    and an `lmi install claude` test needs both fixtures at once.
    """
    bindir = tmp_path / "pipbin"
    bindir.mkdir()
    exe = _executable(bindir / "python", FAKE_PIP)
    script = _executable(bindir / "lmi", FAKE_SCRIPT)

    recdir = tmp_path / "piprec"
    recdir.mkdir()
    count_file = tmp_path / "pipcount.txt"
    count_file.write_text("0")
    probe_file = tmp_path / "probecount.txt"
    probe_file.write_text("0")

    monkeypatch.setenv("FAKE_PIP_DIR", str(recdir))
    monkeypatch.setenv("FAKE_PIP_COUNT", str(count_file))
    monkeypatch.setenv("FAKE_PROBE_COUNT", str(probe_file))
    return Pip(exe, recdir, count_file, probe_file, script)


# --- git, for the repo source and the availability notice -------------------
#
# The same exclusive-PATH trick as fake_claude and fake_npm, for the same
# reason: a real `git ls-remote` in a test is a network call whose answer
# changes underneath the suite, and on a developer machine it would reach the
# actual lmi repository.

FAKE_GIT = """\
#!{python}
import os, sys, time

rec = os.environ["FAKE_GIT_DIR"]
n_file = os.path.join(rec, "count.txt")
n = 0
if os.path.exists(n_file):
    n = int(open(n_file).read() or 0)
n += 1
open(n_file, "w").write(str(n))
with open(os.path.join(rec, "argv-%d.txt" % n), "w") as fh:
    fh.write("\\n".join(sys.argv[1:]))

hang = os.environ.get("FAKE_GIT_HANG")
if hang:
    # Slower than any timeout the caller passes, so the test measures the
    # caller's patience rather than the fake's speed.
    time.sleep(float(hang))

rc = int(os.environ.get("FAKE_GIT_RC", "0"))
if rc:
    sys.stderr.write("fatal: repository not found\\n")
    sys.exit(rc)

raw = os.environ.get("FAKE_GIT_RAW")
if raw is not None:
    sys.stdout.write(raw)
else:
    for i, name in enumerate(os.environ.get("FAKE_GIT_TAGS", "").split(",")):
        if name:
            sys.stdout.write("%040d\\trefs/tags/%s\\n" % (i, name))
sys.exit(0)
"""

FAKE_GIT_BAT = '@"{python}" "%~dp0git.py" %*\r\n'


@pytest.fixture
def fake_git(tmp_path, monkeypatch):
    """A fake `git` on an exclusive PATH, with the three answers that matter.

    `tags()`, `raw()`, `rc()` and `hang()` rather than raw environment
    variables, because every one of these tests is about what lmi does with an
    answer and none of them is about how the fake is configured.
    """
    bindir = tmp_path / "gitbin"
    bindir.mkdir()
    exe = bindir / ("git.py" if os.name == "nt" else "git")
    exe.write_text(FAKE_GIT.format(python=sys.executable), encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    if os.name == "nt":
        (bindir / "git.bat").write_text(
            FAKE_GIT_BAT.format(python=sys.executable), encoding="utf-8"
        )

    recdir = tmp_path / "gitrec"
    recdir.mkdir()
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setenv("FAKE_GIT_DIR", str(recdir))

    class _Git:
        dir = recdir

        def tags(self, names):
            monkeypatch.setenv("FAKE_GIT_TAGS", ",".join(names))

        def raw(self, text):
            monkeypatch.setenv("FAKE_GIT_RAW", text)

        def rc(self, code):
            monkeypatch.setenv("FAKE_GIT_RC", str(code))

        def hang(self, seconds):
            monkeypatch.setenv("FAKE_GIT_HANG", str(seconds))

        def count(self):
            counter = recdir / "count.txt"
            return int(counter.read_text()) if counter.exists() else 0

        def calls(self):
            return [
                (recdir / ("argv-%d.txt" % i)).read_text().splitlines()
                for i in range(1, self.count() + 1)
            ]

    return _Git()
