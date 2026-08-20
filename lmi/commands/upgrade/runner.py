"""The `lmi upgrade` flow.

Order matters. Every question is asked BEFORE anything is modified: a user who
abandons the command at the prompt, or answers no, leaves the machine exactly
as they found it.

One rule about this module in particular. Every import here is module-level,
and after pip.install returns, nothing may import anything or touch the lmi
package: modules already imported stay in memory, but a module imported AFTER
pip would come from the new version, mixed with old ones already loaded. The
only things that may run after that line are a subprocess (verify.confirm),
stdlib calls whose modules were imported long before pip ran, and printing.
_warn_if_shadowed is that stdlib-only exception: shutil.which and Path.resolve
touch no lmi code, and both were imported at the top of this module, long
before pip ran. Do not add a lazy import, and do not move work below that
line.
"""

import shutil
from pathlib import Path

from . import installation, pip, prompts, repo, verify
from .config import SOURCE_REPO, build_config
from .exit_codes import EXIT_INTERNAL
from ... import __version__
from ...core.errors import EXIT_OK, EXIT_USAGE, LmiError

# The version this process is running, read at import - the FROM side of the
# upgrade, and the one version this process can honestly report. It is NEVER
# the answer to "did the upgrade work": see verify.py.
RUNNING = __version__

SHADOWED = (
    "[WARN] the lmi that runs in this shell is not the one just upgraded:\n"
    "         on PATH:  %s\n"
    "         upgraded: %s\n"
    "       Remove the first, or reorder PATH, or the upgrade is invisible."
)


def run(args):
    try:
        return _run(args)
    except LmiError:
        # A usage, pip or verification error, already carrying its exit code
        # and a message cli.main will print. Not ours to reinterpret.
        raise
    except Exception as exc:                    # noqa: BLE001 - deliberate
        raise LmiError(
            "unexpected failure in lmi upgrade: %s: %s"
            % (type(exc).__name__, exc),
            EXIT_INTERNAL,
        )


def _run(args):
    cfg = build_config(args)
    say("Config:  %s" % cfg.source)

    inst = installation.detect()
    say("Running: lmi %s, installed in %s (%s)" % (RUNNING, inst.where, inst.kind))
    # Which source, named. Item 63: both sources end in the same
    # "Upgraded 0.2.1 -> 0.3.0", so this line is the only thing that
    # distinguishes a machine upgraded from the site's audited mirror from one
    # upgraded off a git tag.
    if cfg.source_kind == SOURCE_REPO:
        say("Source:  repo %s" % cfg.repo)
    else:
        say("Source:  index %s" % cfg.index)

    target = _target(args, inst, cfg)
    if target is _NOTHING_TO_DO:
        return EXIT_OK

    # --- ask everything, change nothing ---------------------------------
    if not prompts.confirm(_question(target), default=False):
        say("Nothing was changed.")
        return EXIT_OK

    # --- from here the machine changes ----------------------------------
    pip.install(inst, cfg, target, say)
    # The VERSION the target names, not the target itself. On the repo path the
    # target is a tag name - `v0.3.0` - and the installed console script reports
    # `0.3.0`, so passing the tag through would fail a correct upgrade on a
    # string comparison. Item 22's trap, one layer along: the tag is what was
    # asked for, and only the subprocess says what is installed.
    got = verify.confirm(inst.script, repo.version_string(target) or target)

    say("")
    if got == RUNNING:
        # target was None (the probe in pip.latest could not say what is
        # newest) and pip found nothing newer to install: this is the "no pip
        # index versions on this pip" machine, exactly current, reporting
        # exit 0 having changed nothing. Saying "Upgraded" here would be the
        # silent-success failure CLAUDE.md section 3 exists to prevent - an
        # already-current run claiming it upgraded on every single invocation.
        say("lmi is unchanged: still %s -> %s. Nothing was upgraded; the "
            "source had nothing newer to install." % (RUNNING, got))
    else:
        say("Upgraded lmi %s -> %s" % (RUNNING, got))
    say("  %s" % inst.script)
    _warn_if_shadowed(inst.script)
    return EXIT_OK


# A sentinel rather than None, because None is a real target: "whatever the
# index says is newest".
_NOTHING_TO_DO = object()


def _target(args, inst, cfg):
    """The version to install, None for "the newest", or _NOTHING_TO_DO."""
    if cfg.source_kind == SOURCE_REPO:
        return _repo_target(args, cfg)

    wanted = getattr(args, "version", None)
    if wanted is not None:
        wanted = wanted.strip()
        if not wanted:
            # "" or whitespace passes straight through pip.install and becomes
            # "lmi==", which pip rejects on its own - surfacing as exit 1 with
            # a message that sends the operator to check the index, when the
            # actual mistake is a bad argument. That belongs at exit 2.
            raise LmiError('--version must not be empty', EXIT_USAGE)
        if wanted == RUNNING:
            say("Already at %s - nothing to do." % wanted)
            return _NOTHING_TO_DO
        return wanted

    newest = pip.latest(inst, cfg)
    if newest is None:
        # Best-effort, and its failure degrades the question rather than the
        # command: pip will resolve the newest itself.
        say("The index could not say which version is newest; pip will choose.")
        return None
    if newest == RUNNING:
        say("Already at %s, which is the newest on the index." % newest)
        return _NOTHING_TO_DO
    return newest


def _repo_target(args, cfg):
    """The same three answers, read off the repository's tags.

    Split from the index path rather than folded into it: the two ask different
    remotes different questions, and "newest" is a tag name here and a version
    string there. What they share - an explicit --version wins, an unanswerable
    lookup degrades the question rather than the command - is spelled the same
    way in both.
    """
    wanted = getattr(args, "version", None)
    if wanted is not None:
        wanted = wanted.strip()
        if not wanted:
            raise LmiError('--version must not be empty', EXIT_USAGE)
        if not repo.is_newer(wanted, RUNNING) and \
                repo.parse_version(wanted) == repo.parse_version(RUNNING):
            say("Already at %s - nothing to do." % wanted)
            return _NOTHING_TO_DO
        return wanted

    tag = repo.newest_tag(cfg.repo)
    if tag is None:
        # Best-effort, exactly like the index probe: no git, no network, a
        # timeout or no version tags at all. pip resolves the repository's
        # default branch, which is the only other thing "newest" could mean.
        say("The repository could not say which version is newest; pip will "
            "install its default branch.")
        return None
    say("Newest:  %s" % tag.name)
    if not repo.is_newer(tag.name, RUNNING):
        # Covers equal AND older, which a string comparison would not: a repo
        # whose newest tag is behind this machine must not produce a question
        # offering a downgrade.
        say("Already at %s, and the newest tag in the repository is %s - "
            "nothing to do." % (RUNNING, tag.name))
        return _NOTHING_TO_DO
    return tag.name


def _question(target):
    if target is None:
        return "Replace lmi %s with the newest version available?" % RUNNING
    return "Replace lmi %s with %s?" % (RUNNING, target)


def _warn_if_shadowed(script):
    found = shutil.which("lmi")
    if not found:
        return
    try:
        same = Path(found).resolve() == Path(script).resolve()
    except OSError:
        same = False
    if not same:
        say(SHADOWED % (found, script))


def say(message=""):
    """Console output.

    Deliberately not core.log.Logger: this command writes no log file, and a
    Logger needs a path. `print` is the whole requirement - the same choice
    lmi install made, for the same reason.
    """
    print(message)
