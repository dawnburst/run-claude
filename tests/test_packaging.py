"""The packaging properties the install story depends on.

lmi is installed the same way everywhere: build one wheel, `pip install` it. That
works because of four declarations in pyproject.toml and one property of the
source tree, none of which are obvious from reading the code - so each gets a
test that fails loudly rather than at a user's first install.

Deliberately no test that builds a real wheel: that needs setuptools, and with
build isolation a network, which would make the suite flaky for no gain. The
install scripts each verify the generated launcher exists before declaring
success, and a real wheel install was exercised by hand on Linux and Windows.
"""

import re
from pathlib import Path

from lmi.cli import main

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = (REPO / "pyproject.toml").read_text(encoding="utf-8")


def test_declares_the_lmi_console_script():
    """Without this, `pip install` succeeds and installs no `lmi` command.

    The failure is quiet in the worst way: pip exits 0, and the user is left
    typing a command that does not exist.
    """
    assert re.search(
        r"^\s*lmi\s*=\s*[\"']lmi\.cli:main[\"']\s*$", PYPROJECT, re.MULTILINE
    ), "pyproject.toml must keep [project.scripts] lmi = \"lmi.cli:main\""


def test_declares_no_dependencies():
    """Every install command passes --no-index, so a dependency would break them.

    It would also end the single-file story: a wheel with dependencies cannot be
    installed on an air-gapped machine without carrying its whole tree along.
    """
    assert re.search(r"^\s*dependencies\s*=\s*\[\s*\]\s*$", PYPROJECT, re.MULTILINE), \
        "lmi must keep dependencies = [] - the installers rely on --no-index"


def test_declares_the_python_floor():
    assert re.search(r"^\s*requires-python\s*=\s*[\"']>=3\.9[\"']\s*$",
                     PYPROJECT, re.MULTILINE), \
        "the supported floor is 3.9; the installers check for it by that number"


def test_the_package_is_pure_python():
    """This is what makes the wheel py3-none-any: one file for every OS.

    A single compiled source would give the wheel a platform tag, and the
    project would need a separate build per operating system and interpreter.
    """
    compiled = [
        str(p.relative_to(REPO))
        for pattern in ("*.c", "*.pyx", "*.so", "*.pyd", "*.dll")
        for p in (REPO / "lmi").rglob(pattern)
    ]
    assert compiled == [], "compiled sources would end the py3-none-any wheel: %s" % compiled


def test_main_returns_its_exit_code(tmp_path, monkeypatch):
    """pip's console script is `sys.exit(main())`, so main() must RETURN codes.

    If main() ever grows a bare sys.exit() or returns None on a failure path, the
    installed command starts reporting success for failures - which for a tool
    built to run unattended is the worst possible bug: a scheduled task looks
    healthy forever. One usage error proves the mechanism; which command lines
    are usage errors is test_config.py's job, and codes 1, 3 and 4 need a real
    run, so they live in the schedule tests.
    """
    # chdir even though this fails in argument validation, before any path is
    # resolved: if that order ever changes, the test must not start dropping a
    # log and a state file into the repository.
    monkeypatch.chdir(tmp_path)
    assert main([]) == 2
