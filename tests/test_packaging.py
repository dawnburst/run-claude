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

import ast
import re
from pathlib import Path

import lmi
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


SDK_MODULE = "claude_agent_sdk"


def _imports_the_sdk(path):
    """Does this file really `import claude_agent_sdk`?

    Parsed rather than grepped, and that is the whole point of the function:
    lmi/commands/install/sdk.py carries the module name as a STRING, because
    task 22's check is `sys.executable -c "import claude_agent_sdk"` run in a
    subprocess. A substring search cannot tell that apart from an import and
    would make the boundary test fail on the one module whose job is to prove
    the boundary holds.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] == SDK_MODULE for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == SDK_MODULE:
                return True
    return False


def test_declares_the_sdk_as_an_optional_extra():
    """The other half of the rule above: the SDK is an extra, not a dependency.

    `lmi schedule`'s SDK backend needs claude-agent-sdk, which needs Python
    3.10 and pulls anyio, sniffio and mcp along with it. As a dependency it
    would break every bootstrap script's --no-index on every platform, and it
    would end the 3.9 floor for the CLI-mode sites that never touch it.

    Pinned as `>=`, not bare: an unpinned SDK is how a message-type rename
    empties the activity log without anything failing.
    """
    assert re.search(r"^\s*sdk\s*=\s*\[[^\]]*claude-agent-sdk\s*>=",
                     PYPROJECT, re.MULTILINE), \
        'pyproject.toml must keep [project.optional-dependencies] sdk = ' \
        '["claude-agent-sdk>=..."] - lower-bounded, and an extra, not a dependency'


def test_the_extras_floor_is_the_one_install_asks_pip_for():
    """MANDATORY. The declared floor and the requested floor must be one string.

    The extra's constraint only governs `pip install "lmi[sdk]"`. It does not
    reach `lmi install claude`, which names the distribution to pip directly -
    so the two can disagree, and the direction that bites is silent: an index
    mirroring a version too old for `ClaudeAgentOptions.setting_sources` would
    install cleanly, import cleanly, be written `sdk`, and then raise on every
    iteration. `install/sdk.importable()` cannot catch that; importing the
    package is not the same as being able to build its options.
    """
    from lmi.commands.install import sdk as install_sdk

    assert re.search(
        r"^\s*sdk\s*=\s*\[\s*[\"']%s[\"']\s*\]" % re.escape(
            install_sdk.REQUIREMENT
        ),
        PYPROJECT,
        re.MULTILINE,
    ), (
        'pyproject.toml\'s sdk extra must be exactly ["%s"], to match the '
        "requirement lmi install asks pip for" % install_sdk.REQUIREMENT
    )


def test_only_the_schedule_command_imports_the_sdk():
    """MANDATORY. The containment boundary invariant 4 now states.

    lmi/core/, lmi/cli.py, lmi/commands/__init__.py and the install, config and
    upgrade commands are standard-library only, and must stay importable on 3.9
    with no extra installed. `lmi install claude` and `lmi upgrade` are the two
    commands whose job is fixing a broken machine, and commands/__init__.py
    imports every command at startup - so an SDK import anywhere but the one
    module in commands/schedule/ makes a missing or broken extra break the
    commands that would repair it.
    """
    allowed = REPO / "lmi" / "commands" / "schedule"
    offenders = sorted(
        str(p.relative_to(REPO))
        for p in (REPO / "lmi").rglob("*.py")
        if p.parent != allowed and _imports_the_sdk(p)
    )
    assert offenders == [], (
        "only lmi/commands/schedule/ may import claude_agent_sdk; found it in: %s"
        % offenders
    )


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


def test_lmi_version_matches_pyproject():
    """`lmi upgrade`'s verify.confirm compares two version strings that come
    from two different places: the index's answer, which traces back to
    pyproject.toml's `version` via the wheel filename, and `lmi --version`,
    which argparse prints from lmi.__version__. Nothing else ties them
    together - if they ever drift by one character, EVERY `lmi upgrade` at
    every site that actually installs the newest version still ends in exit 3,
    after pip has already changed the machine, because the freshly-installed
    command would report a version that does not match what the index said it
    shipped.
    """
    match = re.search(r'^\s*version\s*=\s*"([^"]+)"\s*$', PYPROJECT, re.MULTILINE)
    assert match, "pyproject.toml must declare [project] version = \"...\""
    assert lmi.__version__ == match.group(1), (
        "lmi/__init__.py's __version__ (%s) and pyproject.toml's version (%s) "
        "have drifted apart" % (lmi.__version__, match.group(1))
    )


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
