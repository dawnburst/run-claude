"""The claude session carried across the intervals: the handle, and its file.

`lmi schedule` has two memories. The state file is the durable one - a summary
claude writes, inlined into every prompt, and the only one that survives a
session that cannot be resumed. This module owns the other: the id of the
claude conversation itself, so iteration 2 continues iteration 1's context
rather than reading a description of it.

Nothing here knows which backend is running, and neither backend knows what a
session id is for. The runner mints, persists, resumes and drops; `runner.py`
renders the handle into an argv and `sdk.py` into an options object. That is
the same division the seam already draws, and it is what keeps the mechanism
identical in both modes rather than similar in two places.
"""

import os
import uuid
from typing import NamedTuple, Optional

from ...core import fs, jsonfile
from ...core.errors import EXIT_USAGE, LmiError

# What jsonfile.read/write raise with. Every call below catches it - a failure
# here degrades continuity and must never end a run whose actual memory, the
# state file, is intact - so the code is a formality. EXIT_USAGE rather than one
# of this command's own codes, because that is what an unreadable file named by
# a path would be if it ever did escape.
_CODE = EXIT_USAGE

WHAT = "lmi schedule session"

ID_KEY = "session_id"
CREATED_KEY = "created"
WORK_DIR_KEY = "work_dir"

# Aligned with state.prepare's "State file       : " lines, so the two memories
# report themselves in one column.
_SAID = "Session file     : "


class Handle(NamedTuple):
    """One claude session, as this run knows it.

    `resuming` is the whole of what the backends read: False means "this id has
    no conversation behind it yet" (`--session-id`, `session_id=`), True means
    "continue the conversation that has it" (`--resume`, `resume=`). It flips to
    True after the first call of the run, whatever that call returned - a call
    that failed part-way may still have created the session, and item 54 is that
    a failure, a usage limit above all, is not a reason to throw one away.

    `created` and `work_dir` are recorded for the operator rather than for
    claude: the first is the only thing that reveals a session older than the
    state file beside it, and the second is what makes a moved working directory
    diagnosable instead of merely broken - see warn_if_moved.
    """

    id: str
    resuming: bool
    created: str
    work_dir: Optional[str] = None


def mint(work_dir, now_str):
    """A brand new handle. uuid4, because `claude --session-id` requires a UUID.

    Minted by lmi rather than read back out of claude's output, and that is the
    decision the whole feature rests on: without -v the CLI backend logs
    claude's plain text, which carries no session id anywhere, so observing one
    would mean forcing --output-format stream-json onto a run that did not ask
    for it - item 26 arriving from the other side. Minting also means the id
    exists on disk BEFORE the call, so an iteration killed mid-flight still
    leaves something to resume.
    """
    return Handle(id=str(uuid.uuid4()), resuming=False, created=now_str,
                  work_dir=str(work_dir))


def prepare(cfg, path, run_ts, log):
    """The handle this run starts from, or None when continuity is off.

    The `-r` rule, applied to the sidecar exactly as `state.prepare` applies it
    to the state file: kept when -r was given, backed up and replaced when it
    was not. **The two must agree.** A run without -r that started a clean state
    file and resumed yesterday's session would have two memories describing
    different work, both plausible, and would exit 0 either way - which is why
    a test pins the pair rather than each half.

    With continuity off this returns before touching the file at all. An opt-out
    for one run must not destroy the session a later -r run would continue, and
    the operator would have nothing to connect that loss back to.
    """
    if not cfg.session:
        return None
    if fs.kind(path) == fs.FILE:
        if cfg.resume:
            handle = _read(path, run_ts, log)
            if handle is not None:
                log.line(_SAID + "keeping " + str(path))
                return handle
        else:
            _move_aside(path, run_ts, log, "old session id backed up to ")
    else:
        log.line(_SAID + "created new")
    return _mint(cfg, path, log)


def remint(cfg, path, log, old):
    """Give up on `old` and mint a fresh session, out loud.

    Called from the runner on exactly one condition - claude said the
    conversation does not exist - so the wording names the id that is gone
    rather than describing a policy. What it must not sound like is a routine
    step: continuity has just been lost for the rest of the run, and the state
    file is what carries the work from here.
    """
    log.warn(
        "the claude session %s could not be resumed: no conversation with that "
        "id exists. Starting a fresh session - the state file is what carries "
        "the work forward." % old.id
    )
    return _mint(cfg, path, log)


def warn_if_moved(handle, work_dir, log):
    """Say so when the session was created under a different working directory.

    claude keeps its conversations per working directory - they live under
    ~/.claude/projects/<escaped cwd>/ - so a resume from somewhere else will
    very likely fail. This does not refuse the attempt: lmi does not know that
    store's layout is the only path, and the runner handles the failure anyway.
    It supplies the reason in advance, instead of leaving the operator with a
    bare "no conversation found" and a working directory they had no reason to
    suspect.
    """
    if not handle.resuming or handle.work_dir is None:
        return
    if str(work_dir) == handle.work_dir:
        return
    log.warn(
        "the claude session %s was created in %s and this run works in %s. "
        "claude stores conversations per working directory, so resuming it may "
        "fail - the state file still carries the work forward if it does."
        % (handle.id, handle.work_dir, work_dir)
    )


# --- the file -------------------------------------------------------------

def _read(path, run_ts, log):
    """The handle in the sidecar, or None - moving a bad file aside first.

    An unparseable sidecar is neither overwritten nor fatal. Overwriting
    discards what was there, which is what item 19 forbids; refusing the run
    would fail an overnight job over the continuity file while the state file
    was perfectly fine. Moved aside, warned about, and the run mints fresh.
    """
    try:
        doc = jsonfile.read(path, WHAT, _CODE)
    except LmiError as exc:
        log.warn(str(exc))
        _move_aside(path, run_ts, log, "moved aside to ")
        return None
    raw = doc.get(ID_KEY)
    if not isinstance(raw, str) or not raw.strip():
        log.warn(
            "the %s file has no usable %s: %s - starting a fresh session"
            % (WHAT, ID_KEY, path)
        )
        _move_aside(path, run_ts, log, "moved aside to ")
        return None
    return Handle(
        id=raw,
        resuming=True,
        created=str(doc.get(CREATED_KEY, "unknown")),
        work_dir=doc.get(WORK_DIR_KEY),
    )


def _mint(cfg, path, log):
    # Imported here rather than at module scope: paths.py is where the state
    # file, the log, the lock and this file's names are decided, and it must
    # stay importable without this module.
    from . import paths

    handle = mint(cfg.work_dir, paths.now_str())
    _save(path, handle, log)
    return handle


def _save(path, handle, log):
    """Write the handle. A failure is a [WARN], never the end of the run.

    Through core/jsonfile.write, so the sidecar inherits the temp file born 0600
    rather than chmod-ed afterwards, the O_BINARY that keeps the write LF on
    Windows and the atomic replace. None of that is worth a second
    implementation here, and a hand-rolled write is how one of those three gets
    quietly dropped.
    """
    doc = {
        ID_KEY: handle.id,
        CREATED_KEY: handle.created,
        WORK_DIR_KEY: handle.work_dir,
    }
    try:
        jsonfile.write(path, doc, WHAT, _CODE)
    except LmiError as exc:
        log.warn(
            "%s - this run keeps its session, but -r will not be able to "
            "continue it later." % exc
        )


def _move_aside(path, run_ts, log, said):
    """Rename the sidecar out of the way, the way state.prepare does.

    The same `.<run_ts>.bak` shape as the state file's backup rather than
    jsonfile.backup's `.bk_<stamp>`: this file is the state file's companion and
    an operator looking at that folder should find one convention, not two.
    """
    backup = path.with_name(path.name + "." + run_ts + ".bak")
    try:
        os.replace(str(path), str(backup))
    except OSError as exc:
        log.warn("could not back up %s (%s) - it is replaced as is" % (path, exc))
        return
    log.line(_SAID + said + str(backup))
