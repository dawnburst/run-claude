"""The `lmi upgrade` flow.

Order matters. Every question is asked BEFORE anything is modified: a user who
abandons the command at the prompt, or answers no, leaves the machine exactly
as they found it.

One rule about this module in particular. From the moment pip runs, this
process is executing code whose files have just been replaced underneath it.
Modules already imported stay in memory; a module imported AFTER pip would come
from the new version, mixed with old ones already loaded. So every import here
is module-level, and nothing after pip.install does anything but run one
subprocess and print. Do not add a lazy import, and do not move work below that
line.
"""

import shutil
from pathlib import Path

from . import installation, pip, prompts, verify
from .config import build_config
from .exit_codes import EXIT_INTERNAL
from ... import __version__
from ...core.errors import EXIT_OK, LmiError

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
    say("Index:   %s" % cfg.index)

    target = _target(args, inst, cfg)
    if target is _NOTHING_TO_DO:
        return EXIT_OK

    # --- ask everything, change nothing ---------------------------------
    if not prompts.confirm(_question(target, cfg), default=False):
        say("Nothing was changed.")
        return EXIT_OK

    # --- from here the machine changes ----------------------------------
    pip.install(inst, cfg, target, say)
    got = verify.confirm(inst.script, target)

    say("")
    say("Upgraded lmi %s -> %s" % (RUNNING, got))
    say("  %s" % inst.script)
    _warn_if_shadowed(inst.script)
    return EXIT_OK


# A sentinel rather than None, because None is a real target: "whatever the
# index says is newest".
_NOTHING_TO_DO = object()


def _target(args, inst, cfg):
    """The version to install, None for "the newest", or _NOTHING_TO_DO."""
    wanted = getattr(args, "version", None)
    if wanted is not None:
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


def _question(target, cfg):
    if target is None:
        return ("Replace lmi %s with the newest version on the index?"
                % RUNNING)
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
