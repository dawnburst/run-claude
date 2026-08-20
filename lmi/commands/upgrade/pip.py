"""This command's pip install, and the read-only probe that precedes it.

How to spell and run a pip command moved to lmi/core/pip.py when
`lmi install claude` became its second caller. What stayed here is what only
`lmi upgrade` can answer: which package, whether a failure is fatal - it is -
and the version probe, which exists solely to decide what to ask the user.

Note this module is named `pip` and lives inside a package, so `import pip`
elsewhere still finds the real one; nothing here imports pip as a library.
"""

import os
import re
import subprocess

from . import config as cfg_module
from .config import PACKAGE
from .exit_codes import EXIT_PIP_FAILED
from ...core import pip as core_pip
from ...core.errors import LmiError

# `pip index versions lmi` answers with "lmi (0.9.0)" on the first line and
# "Available versions: ..." on the second. Anchored per line, and any failure
# to match is None rather than an error - see latest().
LATEST_RE = re.compile(r"^\s*%s\s*\((.+?)\)\s*$" % re.escape(PACKAGE), re.MULTILINE)

# Two hypotheses, not one, and pip's own output is inherited so it appears
# immediately above this. The Windows clause is printed on every Windows
# failure without inspecting pip's text: pattern-matching an error message to
# decide whether to offer help is a guess that goes stale with the next pip
# release, and an extra clause on a platform where it is plausible costs
# nothing.
INSTALL_FAILED = (
    "pip install %s failed (exit %d).\n"
    "    pip's own output above says which of these it was:\n"
    "      - the index, if pip reported a network error or a 404. Check the\n"
    '        "index" value in the config file, and that it really carries lmi -\n'
    "        lmi does not populate it.\n"
)

# The same shape for a repo install, because the hypotheses have to match what
# was actually tried: printing the index clauses for a git install sends the
# operator to check a URL this command never used.
#
# The third clause is item 60 wearing its diagnostic hat. pip clones first and
# builds second, and the build resolves setuptools from an index - so on an
# air-gapped machine the failure arrives after a perfectly successful clone and
# reads like a build error. An operator who does not know that looks at the
# repository, which is the one thing that worked.
REPO_INSTALL_FAILED = (
    "pip install from %s failed (exit %d).\n"
    "    pip's own output above says which of these it was:\n"
    "      - the repository or the tag, if pip reported a git error: check the\n"
    '        "repo" value in the config file, that git can reach it from this\n'
    "        machine, and that the tag exists.\n"
    "      - git itself, if pip could not run it. pip clones with the machine's\n"
    "        own git; lmi does not bundle one.\n"
    "      - the build, if pip cloned and then failed fetching setuptools or\n"
    "        wheel. Those come from a package index, not from the repository,\n"
    '        so an air-gapped machine needs the "index" key set as well as\n'
    '        "repo" - pip cannot build without them.\n'
)

WINDOWS_CLAUSE = (
    "      - the lmi.exe being replaced is the one running this command. If pip\n"
    "        reported a permission or access error, run this from a shell where\n"
    "        no lmi is live:\n\n"
    "          python -m pip install --user --upgrade --index-url %s lmi\n"
)


def _index_argv(cfg):
    """The index arguments, or none at all when no index is configured.

    The empty case is this command's own concept and is guarded here rather than
    in core/pip.py: "an index is optional because a repo can be the source" is a
    fact about `lmi upgrade`, and core/ has no business knowing it. Passing
    core_pip.index_argv a None index would put a literal None into the argv,
    which subprocess rejects with a TypeError two layers from the cause.
    """
    if not cfg.index:
        return []
    return core_pip.index_argv(cfg.index, cfg.cafile)


def latest(inst, cfg):
    """The newest version the index offers, or None if it cannot say.

    Best-effort by design. `pip index` is an experimental subcommand that an
    older pip does not have at all, and its output could change. Every failure
    is None, which degrades the question the user is asked - it must never
    degrade the command, because a diagnostic that blocks the thing it
    diagnoses is worse than no diagnostic.
    """
    argv = inst.pip_prefix + ["index", "versions", PACKAGE] + _index_argv(cfg)
    try:
        done = subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL)
    except OSError:
        return None
    if done.returncode != 0:
        return None
    match = LATEST_RE.search(done.stdout.decode("utf-8", "replace"))
    return match.group(1).strip() if match else None


def requirement(cfg, version):
    """What pip is asked to install, for whichever source this run uses.

        index, "0.2.0"   ->  "lmi==0.2.0"
        index, None      ->  "lmi"           (with --upgrade)
        repo,  "0.3.0"   ->  "lmi @ git+<url>@v0.3.0"
        repo,  None      ->  "lmi @ git+<url>"   (the repo's default branch)

    The `v` prefix is added HERE and only here, so `--version 0.3.0` and
    `--version v0.3.0` are the same request and an operator never has to know
    the repository's tagging habit. A version that already carries one is left
    alone.
    """
    if cfg.source_kind != cfg_module.SOURCE_REPO:
        return PACKAGE if version is None else "%s==%s" % (PACKAGE, version)
    if version is None:
        # NOT "@None", and not a bare `lmi` either: the source is the repo, so
        # the fallback is the repo's own default branch. A bare `lmi` would
        # silently install from an index instead - the wrong source, reported as
        # a successful upgrade.
        return "%s @ git+%s" % (PACKAGE, cfg.repo)
    tag = version if version[:1] in ("v", "V") else "v" + version
    return "%s @ git+%s@%s" % (PACKAGE, cfg.repo, tag)


def install(inst, cfg, version, say):
    """Install `version`, or the newest when it is None."""
    argv = inst.pip_prefix + ["install"]
    if inst.user_flag:
        argv.append("--user")
    # On a repo install too, and that is item 60: pip clones the repository and
    # then builds it in an isolated environment which it populates from an
    # INDEX. Without these the build fails on an air-gapped machine after a
    # clone that worked perfectly.
    argv += _index_argv(cfg)
    # --no-deps: lmi declares no dependencies and tests/test_packaging.py fails
    # if that stops being true, so this changes nothing about a correct install
    # - and it means a wrong or tampered package on the index cannot pull
    # anything else onto the machine.
    argv.append("--no-deps")
    what = requirement(cfg, version)
    if version is None:
        # --upgrade for both sources: an unpinned requirement that is already
        # satisfied is a no-op to pip, and "lmi is unchanged" is what
        # runner._run then reports rather than claiming an upgrade.
        argv.append("--upgrade")
    argv.append(what)

    code = core_pip.run(argv, say)
    if code != 0:
        if cfg.source_kind == cfg_module.SOURCE_REPO:
            message = REPO_INSTALL_FAILED % (cfg.repo, code)
        else:
            message = INSTALL_FAILED % (what, code)
        if os.name == "nt":
            message += WINDOWS_CLAUSE % (cfg.index or "<your index>")
        raise LmiError(message, EXIT_PIP_FAILED)
