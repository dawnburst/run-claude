"""The zipapp build must propagate lmi's exit codes.

This is the default install route on every platform, and it had a silent, total
failure: `python -m zipapp -m lmi.cli:main` generates

    import lmi.cli
    lmi.cli.main()

which discards the return value, so the process always exited 0. Every code lmi
defines - 1 a failed claude call, 2 usage, 3 another run holds the lock, 4 an
internal crash - became 0. For a tool whose whole purpose is unattended runs
that is the worst possible bug: a scheduled task reports success forever.

The installers therefore stage their own __main__.py that calls sys.exit(main()).
These tests build a zipapp the same way and check the codes really come back, so
that reverting to zipapp's -m turns them red instead of shipping quietly.
"""

import shutil
import subprocess
import sys
import zipapp
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

MAIN_PY = """\
import sys

from lmi.cli import main

sys.exit(main())
"""


@pytest.fixture(scope="module")
def built_pyz(tmp_path_factory):
    """A zipapp built the way the installers build it."""
    work = tmp_path_factory.mktemp("zipapp")
    stage = work / "stage"
    stage.mkdir()
    shutil.copytree(REPO / "lmi", stage / "lmi")
    for junk in stage.rglob("__pycache__"):
        shutil.rmtree(junk, ignore_errors=True)
    (stage / "__main__.py").write_text(MAIN_PY, encoding="utf-8", newline="\n")
    target = work / "lmi.pyz"
    zipapp.create_archive(str(stage), str(target))
    return target


def _run(pyz, *args):
    return subprocess.run(
        [sys.executable, str(pyz), *args],
        capture_output=True, text=True,
    )


def test_version_exits_zero(built_pyz):
    done = _run(built_pyz, "--version")
    assert done.returncode == 0
    assert "lmi" in done.stdout


def test_no_command_exits_two(built_pyz):
    assert _run(built_pyz).returncode == 2


def test_unknown_command_exits_two(built_pyz):
    assert _run(built_pyz, "nosuchcommand").returncode == 2


def test_usage_error_exits_two(built_pyz):
    """-i without -c. Under the generated __main__.py this returned 0."""
    assert _run(built_pyz, "schedule", "x", "-i", "5").returncode == 2


def test_a_nonzero_code_is_not_flattened_to_zero(built_pyz):
    """The property that matters, stated directly.

    Any failing invocation must leave a non-zero status. If this passes while
    the others fail, the entry point is discarding main()'s return value again.
    """
    done = _run(built_pyz, "schedule", "x", "-c", "3")   # -c without -i
    assert done.returncode != 0
