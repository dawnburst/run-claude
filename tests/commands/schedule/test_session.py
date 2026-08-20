"""The session handle, and the sidecar that carries it between runs.

`lmi schedule` has two memories. The state file is the durable one - a summary
claude writes, inlined into every prompt. This is the other: the id of the
claude conversation itself, so an iteration continues the previous one's
context rather than a description of it.

Every test here builds its own tiny cfg and log rather than taking make_cfg,
because these functions read exactly three fields and one method between them -
and a test that has to construct a whole Config to check a file rename is a
test nobody wants to read.
"""

import json
import uuid

import pytest

from lmi.core import jsonfile
from lmi.core.errors import LmiError
from lmi.commands.schedule import paths, session


class _Cfg:
    """The three fields session.py reads. Nothing else is needed."""

    def __init__(self, work_dir, session=True, resume=False):
        self.work_dir = work_dir
        self.session = session
        self.resume = resume


class _Log:
    def __init__(self):
        self.lines = []

    def line(self, msg=""):
        self.lines.append(msg)

    def warn(self, msg):
        self.lines.append("[WARN] " + msg)

    def error(self, msg):
        self.lines.append("[ERROR] " + msg)

    @property
    def text(self):
        return "\n".join(self.lines)


TS = "20260819-140211"


def _sidecar(tmp_path):
    return paths.resolve_session(tmp_path / "run-claude-state.md")


# --- where it lives --------------------------------------------------------

def test_the_sidecar_sits_beside_the_state_file_and_is_named_after_it(tmp_path):
    state = tmp_path / "run-claude-state.md"
    assert paths.resolve_session(state) == (
        tmp_path / "run-claude-state.md.session.json"
    )


def test_two_state_files_in_one_directory_get_two_sidecars(tmp_path):
    """A directory can hold two tasks. The session belongs to the task, so the
    name is derived from the state file rather than fixed like the lock's - one
    sidecar per folder would have two tasks resuming each other's conversation.
    """
    assert paths.resolve_session(tmp_path / "a.md") != \
        paths.resolve_session(tmp_path / "b.md")


def test_a_moved_state_file_takes_its_sidecar_with_it(tmp_path):
    """-s moves the state file; the session must follow it, not stay in the
    working directory."""
    elsewhere = tmp_path / "other"
    got = paths.resolve_session(elsewhere / "state.md")
    assert got.parent == elsewhere


# --- minting ---------------------------------------------------------------

def test_a_minted_id_is_a_uuid(tmp_path):
    """`claude --session-id` refuses anything else - verified on 2.1.235:
    "Error: Invalid session ID. Must be a valid UUID."."""
    handle = session.mint(tmp_path, "2026-08-19 14:02:11")
    assert uuid.UUID(handle.id)
    assert handle.resuming is False
    assert handle.work_dir == str(tmp_path)


def test_two_mints_are_two_sessions(tmp_path):
    assert session.mint(tmp_path, "x").id != session.mint(tmp_path, "x").id


# --- prepare: the -r rule, applied to the sidecar --------------------------

def test_session_off_touches_nothing(tmp_path):
    """MANDATORY - item 52's shape for this file: --no-session is an opt-out for
    one run, not a reset of the machine's state.

    Backing the sidecar up here, or replacing it, would silently make the NEXT
    `-r` run start a fresh session - and the operator would have no reason to
    connect that to the one iteration they ran with --no-session.
    """
    path = _sidecar(tmp_path)
    path.write_text('{"session_id": "keep-me"}', encoding="utf-8")
    log = _Log()

    assert session.prepare(_Cfg(tmp_path, session=False), path, TS, log) is None
    assert json.loads(path.read_text())["session_id"] == "keep-me"
    assert log.lines == []


def test_a_first_run_mints_and_writes_the_sidecar(tmp_path):
    path = _sidecar(tmp_path)
    handle = session.prepare(_Cfg(tmp_path), path, TS, _Log())

    assert handle.resuming is False
    doc = json.loads(path.read_text())
    assert doc["session_id"] == handle.id
    assert doc["work_dir"] == str(tmp_path)
    assert doc["created"] == handle.created


def test_resume_keeps_the_id_and_resumes_it(tmp_path):
    """MANDATORY - item 56, the -r half. This is what makes a run killed by a
    usage limit continuable the next day: the same conversation, not a new one
    reading yesterday's summary.
    """
    path = _sidecar(tmp_path)
    first = session.prepare(_Cfg(tmp_path), path, TS, _Log())

    again = session.prepare(_Cfg(tmp_path, resume=True), path, "20260820-090000",
                            _Log())

    assert again.id == first.id
    assert again.resuming is True
    assert again.created == first.created
    assert again.work_dir == first.work_dir


def test_without_resume_the_sidecar_is_backed_up_and_a_new_id_minted(tmp_path):
    """MANDATORY - item 56, the other half.

    state.prepare backs the state file up and writes a fresh template without
    -r; this file follows the identical rule. A clean state file paired with
    yesterday's session is two memories describing different work, both
    plausible, and the run exits 0 either way.
    """
    path = _sidecar(tmp_path)
    first = session.prepare(_Cfg(tmp_path), path, TS, _Log())

    fresh = session.prepare(_Cfg(tmp_path), path, "20260820-090000", _Log())

    assert fresh.id != first.id
    assert fresh.resuming is False
    backup = path.with_name(path.name + ".20260820-090000.bak")
    assert json.loads(backup.read_text())["session_id"] == first.id
    assert json.loads(path.read_text())["session_id"] == fresh.id


def test_resume_with_no_sidecar_is_a_fresh_mint(tmp_path):
    """-r is about the state file. A task whose state file predates this
    feature, or whose session claude has pruned, simply starts a new one."""
    handle = session.prepare(_Cfg(tmp_path, resume=True), _sidecar(tmp_path), TS,
                             _Log())
    assert handle.resuming is False


def test_the_log_says_which_of_the_three_things_happened(tmp_path):
    path = _sidecar(tmp_path)
    made = _Log()
    session.prepare(_Cfg(tmp_path), path, TS, made)
    kept = _Log()
    session.prepare(_Cfg(tmp_path, resume=True), path, TS, kept)
    replaced = _Log()
    session.prepare(_Cfg(tmp_path), path, "20260820-090000", replaced)

    assert "created new" in made.text
    assert "keeping" in kept.text
    assert "backed up" in replaced.text


# --- prepare: the file being wrong -----------------------------------------

def test_an_unparseable_sidecar_is_moved_aside_and_the_run_continues(tmp_path):
    """Item 19's spirit, without its refusal.

    Overwriting in place would discard what the operator had; refusing the run
    would fail an overnight job over the *continuity* file while the state file
    - the memory that actually carries the work - was perfectly fine. Moved
    aside is the only option that does neither.
    """
    path = _sidecar(tmp_path)
    path.write_text("{not json", encoding="utf-8")
    log = _Log()

    handle = session.prepare(_Cfg(tmp_path, resume=True), path, TS, log)

    assert handle.resuming is False
    assert path.with_name(path.name + "." + TS + ".bak").read_text() == "{not json"
    assert "[WARN]" in log.text


def test_a_sidecar_with_no_session_id_is_moved_aside_too(tmp_path):
    """A JSON object without an id is not a sidecar lmi wrote. Same treatment:
    keep it, warn, mint."""
    path = _sidecar(tmp_path)
    path.write_text('{"note": "not mine"}', encoding="utf-8")
    log = _Log()

    handle = session.prepare(_Cfg(tmp_path, resume=True), path, TS, log)

    assert handle.resuming is False
    assert path.with_name(path.name + "." + TS + ".bak").exists()
    assert "[WARN]" in log.text


@pytest.mark.parametrize("raw", ['{"session_id": ""}', '{"session_id": 7}',
                                 '{"session_id": null}'])
def test_a_blank_or_non_string_id_is_not_resumed(raw, tmp_path):
    path = _sidecar(tmp_path)
    path.write_text(raw, encoding="utf-8")
    handle = session.prepare(_Cfg(tmp_path, resume=True), path, TS, _Log())
    assert handle.resuming is False


def test_a_sidecar_that_cannot_be_written_warns_and_the_run_keeps_its_handle(
    tmp_path, monkeypatch
):
    """The state file's write is fatal (item 1); this one is not, deliberately.

    Continuity inside this run is unaffected - the handle is in memory - and
    only tomorrow's -r loses it. Failing the whole run over that would be the
    worse trade, which is item 36's weighing.
    """
    def _boom(*a, **k):
        raise LmiError("disk full", 2)

    monkeypatch.setattr(jsonfile, "write", _boom)
    log = _Log()

    handle = session.prepare(_Cfg(tmp_path), _sidecar(tmp_path), TS, log)

    assert handle is not None
    assert "[WARN]" in log.text


def test_a_sidecar_that_cannot_be_moved_aside_is_replaced_not_fatal(
    tmp_path, monkeypatch
):
    path = _sidecar(tmp_path)
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(session.os, "replace",
                        lambda *a: (_ for _ in ()).throw(OSError(13, "denied")))
    log = _Log()

    handle = session.prepare(_Cfg(tmp_path, resume=True), path, TS, log)

    assert handle is not None
    assert "[WARN]" in log.text


# --- reminting, and the working directory ----------------------------------

def test_remint_warns_naming_the_old_id_and_writes_the_new_one(tmp_path):
    path = _sidecar(tmp_path)
    old = session.prepare(_Cfg(tmp_path), path, TS, _Log())._replace(resuming=True)
    log = _Log()

    new = session.remint(_Cfg(tmp_path), path, log, old)

    assert new.id != old.id
    assert new.resuming is False
    assert old.id in log.text and "[WARN]" in log.text
    assert json.loads(path.read_text())["session_id"] == new.id


def test_a_moved_working_directory_is_warned_about_before_the_call(tmp_path):
    """claude keeps conversations per working directory - verified: they live
    under ~/.claude/projects/<escaped cwd>/ - so this resume will very likely
    fail. Saying why in advance beats a bare "no conversation found"."""
    log = _Log()
    handle = session.mint(tmp_path / "old", "2026-08-19 14:02:11") \
        ._replace(resuming=True)

    session.warn_if_moved(handle, tmp_path / "new", log)

    assert "[WARN]" in log.text
    assert str(tmp_path / "old") in log.text
    assert str(tmp_path / "new") in log.text


def test_the_same_working_directory_says_nothing(tmp_path):
    log = _Log()
    handle = session.mint(tmp_path, "2026-08-19 14:02:11")._replace(resuming=True)
    session.warn_if_moved(handle, tmp_path, log)
    assert log.lines == []


def test_a_fresh_session_is_never_warned_about(tmp_path):
    """Nothing is being resumed, so the working directory cannot be wrong."""
    log = _Log()
    session.warn_if_moved(session.mint(tmp_path / "old", "x"), tmp_path, log)
    assert log.lines == []


def test_a_sidecar_written_before_work_dir_was_recorded_says_nothing(tmp_path):
    log = _Log()
    handle = session.Handle(id="x", resuming=True, created="x", work_dir=None)
    session.warn_if_moved(handle, tmp_path, log)
    assert log.lines == []
