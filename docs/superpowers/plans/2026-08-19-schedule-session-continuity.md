# Session continuity for `lmi schedule` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One claude session carried across a run's intervals, in both backends, so an iteration cut short — by a usage limit above all — is continued with the context it already had rather than a summary of it.

**Architecture:** lmi mints a `uuid4` before the first call, passes `--session-id` on a fresh session and `--resume` afterwards (CLI), or `session_id=` / `resume=` (SDK), and persists the id in `<state file>.session.json` so `-r` continues the session as well as the state. A quota failure keeps the session; only claude's own "No conversation found with session ID" wording drops it, once, with one fresh retry inside the same iteration.

**Tech Stack:** Python 3.9 floor, standard library only (`uuid`, `json`); `claude_agent_sdk` in `commands/schedule/sdk.py` alone; pytest.

**Spec:** `docs/superpowers/specs/2026-08-19-schedule-session-continuity-design.md`

## Global Constraints

- **Python 3.9 floor, stdlib only at runtime.** No `match`, no `X | Y` runtime unions, no builtin generics in evaluated annotations. `uuid` and `json` are stdlib; nothing new is added to `dependencies`.
- **The SDK is imported in `commands/schedule/sdk.py` and nowhere else**, lazily, inside functions. `tests/test_packaging.py` enforces it.
- **The `sdk` extra's floor does not move.** Verified empirically against `claude-agent-sdk==0.2.136`, the current floor in both `pyproject.toml` and `install/sdk.REQUIREMENT`: `ClaudeAgentOptions` already has both `session_id` and `resume`, and `ResultMessage`/`AssistantMessage` already carry `session_id`. Spec §9's floor bump is therefore **not** part of this work; the runtime field check in Task 5 stays, for a machine whose installed SDK is older than the floor.
- **Invariant 3:** nothing in the unattended runner may wait for a keypress. No `can_use_tool`, no interactive permission mode, every wait a `time.sleep`.
- **Invariant 2:** a failing claude call never fails the runner. New failure paths log and continue.
- **Both backends or neither.** Every behaviour below is asserted in `cli_mode` *and* `sdk_mode`. An asymmetry is only acceptable where it is declared out loud (Task 5's id check).
- **The suite is run after every task:** `python3 -m pytest tests/ -q`. Baseline before this work: **769 passed, 19 skipped**; with the SDK importable, **787 passed, 1 skipped** (measured, not arithmetic).
- **Never let a test reach a real `claude` or a real SDK.** `fake_claude` replaces `PATH` entirely; `fake_sdk` replaces `sys.modules["claude_agent_sdk"]`.
- Exit codes: `0`/`2` are global (`core/errors.py`); this command owns `1`, `3`, `4` (`schedule/exit_codes.py`). No new codes.

---

### Task 1: The `session` config key and the unresumable wording

Both live in `commands/schedule/backend.py`, the module for what the two backends and the two config-writing commands must agree on — same reasoning as `QUOTA_RE` and `ALLOWED_TOOLS`.

**Files:**
- Modify: `lmi/commands/schedule/backend.py`
- Test: `tests/commands/schedule/test_backend.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `backend.SESSION_KEY = "session"`, `backend.SESSION_DEFAULT = True`, `backend.parse_session(raw, source) -> bool`, `backend.resolve_session(explicit_config) -> (bool, str)`, `backend.session_of_document(doc, path) -> (bool, str)`, `backend.UNRESUMABLE_RE` (compiled, `re.IGNORECASE`).

- [ ] **Step 1: Write the failing tests**

In `tests/commands/schedule/test_backend.py`:

```python
def test_an_absent_session_key_means_the_default(tmp_path):
    doc = {"schedule": {"mode": "cli"}}
    assert backend.session_of_document(doc, tmp_path / "lmi.json") == (
        backend.SESSION_DEFAULT, backend.DEFAULT_SOURCE
    )


def test_session_false_is_read_and_names_the_file(tmp_path):
    path = tmp_path / "lmi.json"
    on, source = backend.session_of_document({"schedule": {"session": False}}, path)
    assert on is False
    assert source == str(path)


def test_an_explicit_null_session_is_refused(tmp_path):
    """MANDATORY - absent is not null, the same rule's fifth home.

    `.get(KEY)` alone cannot tell an absent key from `"session": null`, and
    null is meaningful elsewhere in these documents. A null read as "the
    default" is a value the operator wrote being silently discarded.
    """
    with pytest.raises(LmiError) as exc:
        backend.session_of_document({"schedule": {"session": None}}, tmp_path / "x.json")
    assert exc.value.code == EXIT_USAGE
    assert "null" in str(exc.value)


@pytest.mark.parametrize("raw", ["true", "false", "on", 1, 0, [], {}])
def test_a_non_boolean_session_is_refused(raw, tmp_path):
    with pytest.raises(LmiError) as exc:
        backend.session_of_document({"schedule": {"session": raw}}, tmp_path / "x.json")
    assert exc.value.code == EXIT_USAGE


def test_the_verified_unresumable_wording_matches():
    """MANDATORY - item 55. This is claude 2.1.235's own line, verified:

        $ claude -p --resume 1111...-5555 "hi"
        No conversation found with session ID: 1111...-5555
    """
    line = ("No conversation found with session ID: "
            "11111111-2222-3333-4444-555555555555")
    assert backend.UNRESUMABLE_RE.search(line)


def test_quota_wording_is_never_read_as_unresumable():
    """MANDATORY - item 54. The two patterns must not overlap.

    An overlap drops the session on a usage limit, which is the one case this
    feature exists for, at exit 0 with nothing to show it happened.
    """
    for line in ("Claude AI usage limit reached|1234567890",
                 "rate limit exceeded, please try again later",
                 "You have exceeded your credit balance",
                 "API Error: 429 Too Many Requests"):
        assert backend.QUOTA_RE.search(line)
        assert not backend.UNRESUMABLE_RE.search(line)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/commands/schedule/test_backend.py -q`
Expected: FAIL — `AttributeError: module 'lmi.commands.schedule.backend' has no attribute 'session_of_document'`.

- [ ] **Step 3: Implement**

In `backend.py`, after `QUOTA_RE`:

```python
# What earns an iteration the "this session is gone" verdict, in the one form
# both backends read - beside QUOTA_RE, for the same reason and with one extra
# one. The verdict is acted on: a hit discards the session handle and mints a
# fresh one (item 55), so this pattern MUST NOT match quota wording. Dropping
# a session because a usage limit was reported is item 54's failure, and the
# session survives a usage limit - that is the case the feature exists for.
#
# The first alternative is claude 2.1.235's verbatim line, verified by running
# it: "No conversation found with session ID: <uuid>", exit 1, printed before
# any API call. The other two are near-misses from the same family, cheap to
# accept because a miss means every remaining iteration failing identically
# against a session that no longer exists.
UNRESUMABLE_RE = re.compile(
    r"no conversation found|session not found|could not find session",
    re.IGNORECASE,
)

# Whether one claude session is carried across the intervals. On by default:
# an iteration cut short by a usage limit continuing with the context it
# already had is the behaviour the command was asked for. `--no-session` and
# this key turn it off; the header names which one did (item 58).
SESSION_KEY = "session"
SESSION_DEFAULT = True

SESSION_INVALID = (
    '"%s.%s" must be true or false\n'
    "    Got: %s\n"
    "    From: %s\n"
    "    There is deliberately no fall back to the default here: a run that\n"
    "    silently dropped the session, or kept one the operator asked it not\n"
    "    to, is indistinguishable from one that did as it was told - both\n"
    "    exit 0."
)


def parse_session(raw, source):
    """One raw value into a bool, or exit 2. `isinstance(True, bool)`, so 1 is
    refused: JSON spells this key `true`, and guessing at `1` or `"true"` is
    the near-miss class `parse()` refuses for the mode.
    """
    if isinstance(raw, bool):
        return raw
    raise LmiError(
        SESSION_INVALID % (SECTION, SESSION_KEY, _shown(raw), source), EXIT_USAGE
    )


def resolve_session(explicit_config):
    """(on?, where it came from). Never raises for a missing config file.

    Discovery is core/config.py's, unchanged: the same file `resolve()` reads,
    so one lookup order governs both keys in this section.
    """
    path, _ = core_config.find_optional(explicit_config)
    if path is None:
        return SESSION_DEFAULT, DEFAULT_SOURCE
    return session_of_document(core_config.load(path), path)


def session_of_document(doc, path):
    """(on?, source) out of one already-loaded config document."""
    section = _section(doc, path)
    if section is _MISSING:
        return SESSION_DEFAULT, DEFAULT_SOURCE
    raw = section.get(SESSION_KEY, _MISSING)
    if raw is _MISSING:
        return SESSION_DEFAULT, DEFAULT_SOURCE
    return parse_session(raw, path), str(path)
```

And factor the section lookup `of_document` already does, so the two keys
cannot disagree about what a malformed document is — replacing those lines in
`of_document` with a call to it:

```python
def _section(doc, path):
    """The `schedule` section, `_MISSING` when absent. Refuses a non-object.

    Shared by both keys in the section deliberately: two copies of "what is a
    valid schedule section" is two chances for one key to accept a document the
    other refuses.
    """
    if not isinstance(doc, dict):
        raise LmiError(
            "the config file must contain a JSON object: %s" % path, EXIT_USAGE
        )
    section = doc.get(SECTION, _MISSING)
    if section is _MISSING:
        return _MISSING
    if not isinstance(section, dict):
        raise LmiError(
            'the "%s" section must be a JSON object: %s' % (SECTION, path),
            EXIT_USAGE,
        )
    return section
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest tests/commands/schedule/test_backend.py -q` → PASS.
Then the whole suite: `python3 -m pytest tests/ -q` → 769 + the new tests, 19 skipped.

- [ ] **Step 5: Commit**

```bash
git add lmi/commands/schedule/backend.py tests/commands/schedule/test_backend.py
git commit -m "feat: read schedule.session, and know the wording for a session that is gone"
```

---

### Task 2: The handle and its sidecar

**Files:**
- Create: `lmi/commands/schedule/session.py`
- Modify: `lmi/commands/schedule/paths.py` (one constant, one function)
- Test: `tests/commands/schedule/test_session.py` (new)

**Interfaces:**
- Consumes: `backend.SESSION_DEFAULT` (Task 1) only through `cfg.session`, which Task 3 adds; until then tests build a `Config` with `make_cfg(tmp_path, session=True)` — **Task 3 adds that field, so this task's tests pass `session` through a tiny local namespace object instead** (see Step 1).
- Produces: `paths.SESSION_SUFFIX`, `paths.resolve_session(state_path) -> Path`, `session.Handle(id, resuming, created, work_dir)`, `session.mint(work_dir, now_str) -> Handle`, `session.prepare(cfg, path, run_ts, log) -> Optional[Handle]`, `session.remint(cfg, path, log, old) -> Handle`, `session.warn_if_moved(handle, work_dir, log) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/commands/schedule/test_session.py`:

```python
"""The session handle, and the sidecar that carries it between runs."""

import json

import pytest

from lmi.commands.schedule import paths, session


class _Cfg:
    """Just the two fields session.prepare reads. Task 3 puts them on Config;
    this keeps the two tasks independently testable."""

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


def test_the_sidecar_sits_beside_the_state_file_and_is_named_after_it(tmp_path):
    state = tmp_path / "run-claude-state.md"
    assert paths.resolve_session(state) == (
        tmp_path / "run-claude-state.md.session.json"
    )


def test_two_state_files_in_one_directory_get_two_sidecars(tmp_path):
    """A directory can hold two tasks. The session belongs to the task, so the
    name is derived from the state file rather than fixed like the lock's."""
    a = paths.resolve_session(tmp_path / "a.md")
    b = paths.resolve_session(tmp_path / "b.md")
    assert a != b


def test_a_minted_id_is_a_uuid(tmp_path):
    """`claude --session-id` refuses anything else: verified on 2.1.235,
    "Error: Invalid session ID. Must be a valid UUID."."""
    import uuid
    handle = session.mint(tmp_path, "2026-08-19 14:02:11")
    assert uuid.UUID(handle.id)
    assert handle.resuming is False


def test_session_off_touches_nothing(tmp_path):
    """MANDATORY - --no-session is an opt-out for a run, not a reset of the
    machine's state. Destroying the sidecar would silently make the NEXT `-r`
    run start a fresh session."""
    path = paths.resolve_session(tmp_path / "s.md")
    path.write_text('{"session_id": "keep-me"}', encoding="utf-8")
    log = _Log()

    assert session.prepare(_Cfg(tmp_path, session=False), path, "20260819-140211", log) is None
    assert json.loads(path.read_text())["session_id"] == "keep-me"
    assert log.lines == []


def test_a_first_run_mints_and_writes_the_sidecar(tmp_path):
    path = paths.resolve_session(tmp_path / "s.md")
    log = _Log()

    handle = session.prepare(_Cfg(tmp_path), path, "20260819-140211", log)

    assert handle.resuming is False
    doc = json.loads(path.read_text())
    assert doc["session_id"] == handle.id
    assert doc["work_dir"] == str(tmp_path)


def test_resume_keeps_the_id_and_resumes_it(tmp_path):
    """MANDATORY - item 56, the -r half. This is what makes a run killed by a
    usage limit continuable the next day."""
    path = paths.resolve_session(tmp_path / "s.md")
    first = session.prepare(_Cfg(tmp_path), path, "20260819-140211", _Log())

    again = session.prepare(_Cfg(tmp_path, resume=True), path, "20260820-090000", _Log())

    assert again.id == first.id
    assert again.resuming is True
    assert again.created == first.created


def test_without_resume_the_sidecar_is_backed_up_and_a_new_id_minted(tmp_path):
    """MANDATORY - item 56, the other half. A clean state file with yesterday's
    session is two memories disagreeing, and the run exits 0 either way."""
    path = paths.resolve_session(tmp_path / "s.md")
    first = session.prepare(_Cfg(tmp_path), path, "20260819-140211", _Log())

    fresh = session.prepare(_Cfg(tmp_path), path, "20260820-090000", _Log())

    assert fresh.id != first.id
    assert fresh.resuming is False
    backup = path.with_name(path.name + ".20260820-090000.bak")
    assert json.loads(backup.read_text())["session_id"] == first.id


def test_resume_with_no_sidecar_is_a_fresh_mint(tmp_path):
    path = paths.resolve_session(tmp_path / "s.md")
    handle = session.prepare(_Cfg(tmp_path, resume=True), path, "20260819-140211", _Log())
    assert handle.resuming is False


def test_an_unparseable_sidecar_is_moved_aside_and_the_run_continues(tmp_path):
    """Item 19's spirit: never discard what the operator had. Failing the run
    over the continuity file while the state file is intact would be worse."""
    path = paths.resolve_session(tmp_path / "s.md")
    path.write_text("{not json", encoding="utf-8")
    log = _Log()

    handle = session.prepare(_Cfg(tmp_path, resume=True), path, "20260819-140211", log)

    assert handle.resuming is False
    assert path.with_name(path.name + ".20260819-140211.bak").read_text() == "{not json"
    assert "[WARN]" in log.text


def test_a_sidecar_that_cannot_be_written_warns_and_the_run_keeps_its_handle(
    tmp_path, monkeypatch
):
    """The state file's write is fatal (item 1); this one is not. Continuity
    inside this run is unaffected - only tomorrow's -r loses it."""
    path = paths.resolve_session(tmp_path / "s.md")
    log = _Log()

    from lmi.core import jsonfile
    from lmi.core.errors import LmiError

    def _boom(*a, **k):
        raise LmiError("disk full", 2)

    monkeypatch.setattr(jsonfile, "write", _boom)

    handle = session.prepare(_Cfg(tmp_path), path, "20260819-140211", log)

    assert handle is not None
    assert "[WARN]" in log.text


def test_remint_warns_naming_the_old_id_and_writes_the_new_one(tmp_path):
    path = paths.resolve_session(tmp_path / "s.md")
    old = session.prepare(_Cfg(tmp_path), path, "20260819-140211", _Log())
    log = _Log()

    new = session.remint(_Cfg(tmp_path), path, log, old._replace(resuming=True))

    assert new.id != old.id
    assert new.resuming is False
    assert old.id in log.text and "[WARN]" in log.text
    assert json.loads(path.read_text())["session_id"] == new.id


def test_a_moved_working_directory_is_warned_about_before_the_call(tmp_path):
    """claude's session store is keyed by cwd, so this resume will probably
    fail. Saying why in advance beats a bare "no conversation found"."""
    log = _Log()
    handle = session.mint(tmp_path / "old", "2026-08-19 14:02:11")._replace(resuming=True)

    session.warn_if_moved(handle, tmp_path / "new", log)

    assert "[WARN]" in log.text
    assert str(tmp_path / "old") in log.text and str(tmp_path / "new") in log.text


def test_the_same_working_directory_says_nothing(tmp_path):
    log = _Log()
    handle = session.mint(tmp_path, "2026-08-19 14:02:11")._replace(resuming=True)
    session.warn_if_moved(handle, tmp_path, log)
    assert log.lines == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/commands/schedule/test_session.py -q`
Expected: FAIL — `ImportError: cannot import name 'session'`.

- [ ] **Step 3: Implement `paths.resolve_session`**

In `paths.py`, beside `STATE_NAME` / `LOCK_NAME`:

```python
# The session sidecar's name is DERIVED from the state file's, not fixed in the
# folder like the lock's. A directory can legitimately hold two state files for
# two tasks, and the session belongs to the task: one sidecar per folder would
# have two tasks resuming each other's conversation.
SESSION_SUFFIX = ".session.json"
```

and, after `resolve_state`:

```python
def resolve_session(state_path):
    """Where the session id is remembered: beside the state file it belongs to.

    No validation of its own, deliberately. `resolve_state` has already
    expanded the path, refused a UNC one, refused a directory and ensured the
    parent is writable - and this file lives in that same directory, so every
    one of those verdicts already covers it. A second set of rules here would
    be a second chance to disagree with the first.
    """
    return state_path.with_name(state_path.name + SESSION_SUFFIX)
```

- [ ] **Step 4: Implement `session.py`**

Create `lmi/commands/schedule/session.py`:

```python
"""The claude session carried across the intervals: the handle, and its file.

`lmi schedule` has two memories. The state file is the durable one - a summary
claude writes, inlined into every prompt, and the only one that survives a
session that cannot be resumed. This module owns the other: the id of the
claude conversation itself, so iteration 2 continues iteration 1's context
rather than reading a description of it.

Nothing here knows which backend is running. The runner mints, persists,
resumes and drops; `runner.py` renders the handle into an argv and `sdk.py`
into an options object, and neither decides anything about sessions.
"""

import uuid
from typing import NamedTuple, Optional

from ...core import fs, jsonfile
from ...core.errors import EXIT_USAGE, LmiError

# What jsonfile.read/write raise with. Every call below catches it - a failure
# here degrades continuity and must never end a run whose actual memory, the
# state file, is intact - so the code is a formality. EXIT_USAGE rather than
# one of this command's codes, because that is what an unreadable file given by
# a path would be if it ever did escape.
_CODE = EXIT_USAGE

WHAT = "lmi schedule session"

ID_KEY = "session_id"
CREATED_KEY = "created"
WORK_DIR_KEY = "work_dir"


class Handle(NamedTuple):
    """One claude session, as this run knows it.

    `resuming` is the whole of what the backends read: False means "this id has
    no conversation behind it yet, mint it" (`--session-id`), True means
    "continue that conversation" (`--resume`). It flips to True after the first
    call of the run, whatever that call returned - a call that failed part-way
    may still have created the session, and item 54 is that a failure is not a
    reason to throw one away.

    `created` and `work_dir` are recorded for the operator, not for claude: the
    first is the only thing that reveals a session older than the state file
    beside it, and the second is what makes a moved working directory
    diagnosable (see warn_if_moved).
    """

    id: str
    resuming: bool
    created: str
    work_dir: Optional[str] = None


def mint(work_dir, now_str):
    """A brand new handle. uuid4 because `claude --session-id` requires a UUID.

    Minted by lmi rather than read back out of claude's output, which is the
    mechanism decision the whole feature rests on: without -v the CLI backend
    logs claude's plain text, which carries no session id anywhere, so
    observing one would mean forcing --output-format stream-json onto a run
    that did not ask for it. Minting also means the id exists on disk BEFORE
    the call, so an iteration killed mid-flight still leaves something to
    resume.
    """
    return Handle(id=str(uuid.uuid4()), resuming=False, created=now_str,
                  work_dir=str(work_dir))


def prepare(cfg, path, run_ts, log):
    """The handle this run starts from, or None when continuity is off.

    The `-r` rule, applied to the sidecar exactly as `state.prepare` applies it
    to the state file: kept when -r was given, backed up and replaced when it
    was not. The two must agree. A run without -r that started a clean state
    file and resumed yesterday's session would have two memories describing
    different work, both plausible, and would exit 0 either way - which is why
    a test pins the pair rather than each half.

    With continuity off this returns before touching the file at all: an
    opt-out for one run must not destroy the session a later -r run would
    continue.
    """
    if not cfg.session:
        return None
    if fs.kind(path) == fs.FILE:
        if cfg.resume:
            handle = _read(path, run_ts, log)
            if handle is not None:
                log.line("Session file     : keeping " + str(path))
                return handle
        else:
            _move_aside(path, run_ts, log,
                        "Session file     : old session id backed up to ")
    return _mint(cfg, path, log)


def remint(cfg, path, log, old):
    """Give up on `old` and mint a fresh session, out loud.

    Called from the runner on exactly one condition - claude said the
    conversation does not exist - so the wording names the id that is gone
    rather than describing a policy.
    """
    log.warn(
        "the claude session %s could not be resumed: no conversation with that "
        "id exists. Starting a fresh session; the state file is what carries "
        "the work forward." % old.id
    )
    return _mint(cfg, path, log)


def warn_if_moved(handle, work_dir, log):
    """Say so when the session was created under a different -d.

    claude keeps its conversations per working directory, so a resume from
    somewhere else will very likely fail. This does not refuse the attempt -
    lmi does not know that store's layout is the only path, and the runner
    handles the failure - it just supplies the reason in advance, instead of
    leaving the operator with a bare "no conversation found".
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
        _move_aside(path, run_ts, log, "Session file     : moved aside to ")
        return None
    raw = doc.get(ID_KEY)
    if not isinstance(raw, str) or not raw.strip():
        log.warn(
            "the %s file has no usable %s: %s - starting a fresh session"
            % (WHAT, ID_KEY, path)
        )
        _move_aside(path, run_ts, log, "Session file     : moved aside to ")
        return None
    return Handle(
        id=raw,
        resuming=True,
        created=str(doc.get(CREATED_KEY, "unknown")),
        work_dir=doc.get(WORK_DIR_KEY),
    )


def _mint(cfg, path, log):
    from . import paths                     # local: paths imports nothing here
    handle = mint(cfg.work_dir, paths.now_str())
    _save(path, handle, log)
    return handle


def _save(path, handle, log):
    """Write the handle. A failure is a [WARN], never the end of the run.

    Through core/jsonfile.write, so the sidecar inherits the temp file born
    0600, the O_BINARY that keeps the write LF on Windows and the atomic
    replace - none of which is worth a second implementation here.
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

    Same `.<run_ts>.bak` shape as the state file's backup rather than
    jsonfile.backup's `.bk_<stamp>`: this file is the state file's companion
    and an operator looking at the folder should see one convention, not two.
    """
    import os
    backup = path.with_name(path.name + "." + run_ts + ".bak")
    try:
        os.replace(str(path), str(backup))
    except OSError as exc:
        log.warn("could not back up %s (%s) - it is replaced as is" % (path, exc))
        return
    log.line(said + str(backup))
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest tests/commands/schedule/test_session.py -q` → PASS.
Then `python3 -m pytest tests/ -q` → the baseline plus both new modules' tests, 19 skipped.

- [ ] **Step 6: Commit**

```bash
git add lmi/commands/schedule/session.py lmi/commands/schedule/paths.py \
        tests/commands/schedule/test_session.py
git commit -m "feat: mint and remember the claude session beside the state file"
```

---

### Task 3: The command surface — `--no-session`, and the `-f` flags it protects

**Files:**
- Modify: `lmi/commands/schedule/config.py`
- Modify: `tests/commands/schedule/conftest.py` (`make_cfg` gains the two fields)
- Test: `tests/commands/schedule/test_config.py`

**Interfaces:**
- Consumes: `backend.resolve_session` (Task 1).
- Produces: `Config.session: bool`, `Config.session_source: str`, `config.SESSION_FLAG_SOURCE = "--no-session"`, `config.SESSION_FLAGS` (the six refused `-f` names).

- [ ] **Step 1: Write the failing tests**

In `tests/commands/schedule/test_config.py` — note every one of these needs a mode fixture, since `build_config` resolves the backend:

```python
def test_session_continuity_is_on_by_default(cli_mode, tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "resolve_session",
                        lambda explicit_config=None: (True, backend.DEFAULT_SOURCE))
    cfg = build_config(_args(prompt="do it"))
    assert cfg.session is True
    assert cfg.session_source == backend.DEFAULT_SOURCE


def test_no_session_beats_the_config_file(cli_mode, monkeypatch):
    """The flag is a statement about this run and must win. Whatever wins is
    named in the header - item 58 - which is what makes the precedence
    readable afterwards instead of guessable."""
    monkeypatch.setattr(backend, "resolve_session",
                        lambda explicit_config=None: (True, "/etc/lmi.json"))
    cfg = build_config(_args(prompt="do it", session=False))
    assert cfg.session is False
    assert cfg.session_source == config.SESSION_FLAG_SOURCE


def test_the_config_file_turns_it_off_and_is_named(cli_mode, monkeypatch):
    monkeypatch.setattr(backend, "resolve_session",
                        lambda explicit_config=None: (False, "/etc/lmi.json"))
    cfg = build_config(_args(prompt="do it"))
    assert cfg.session is False
    assert cfg.session_source == "/etc/lmi.json"


@pytest.mark.parametrize("flag", [
    "--resume abc", "--resume=abc", "-r abc", "--continue", "-c",
    "--session-id abc", "--session-id=abc", "--fork-session",
])
def test_a_session_flag_in_f_is_refused_while_continuity_is_on(
    flag, cli_mode, monkeypatch
):
    """MANDATORY - item 57. -f is appended last and claude takes the last
    occurrence of a repeated option, so the user's flag does not ADD anything:
    it replaces the one lmi is using to hold the run together, and the log
    still reads clean."""
    monkeypatch.setattr(backend, "resolve_session",
                        lambda explicit_config=None: (True, backend.DEFAULT_SOURCE))
    with pytest.raises(LmiError) as exc:
        build_config(_args(prompt="do it", flags=flag))
    assert exc.value.code == EXIT_USAGE
    assert "--no-session" in str(exc.value)


@pytest.mark.parametrize("flag", ["--resume abc", "-c", "--fork-session"])
def test_no_session_hands_those_flags_back(flag, cli_mode, monkeypatch):
    """The escape hatch, and the reason refusing is not confiscating: an
    operator who wants to drive resumption themselves says --no-session."""
    monkeypatch.setattr(backend, "resolve_session",
                        lambda explicit_config=None: (True, backend.DEFAULT_SOURCE))
    cfg = build_config(_args(prompt="do it", flags=flag, session=False))
    assert cfg.user_flags == shlex.split(flag)


def test_an_unrelated_f_flag_still_passes_through(cli_mode, monkeypatch):
    monkeypatch.setattr(backend, "resolve_session",
                        lambda explicit_config=None: (True, backend.DEFAULT_SOURCE))
    cfg = build_config(_args(prompt="do it", flags="--model opus"))
    assert cfg.user_flags == ["--model", "opus"]
```

`_args` is that module's existing argument-namespace helper; give it a
`session=None` default so these read the way the others do. If the module
builds namespaces inline, add `session=None` to the helper it uses.

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/commands/schedule/test_config.py -q`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'session'` / `Config` has no field `session`.

- [ ] **Step 3: Implement**

In `config.py`, in `add_arguments` after `-r`:

```python
    # Long form only: -r, -c, -s, -i, -d, -l, -f, -t and -v are all taken, and
    # a single letter for an opt-out nobody types often is not worth the
    # collision. Unlike --mode, which schedule deliberately does not have, a
    # flag is right here: continuity is a property of one run's task, not of
    # the machine, and the header names whichever of the two chose it.
    parser.add_argument(
        "--no-session", dest="session", action="store_false", default=None,
        help="do not keep one claude session across iterations; each one "
             "starts fresh and carries only the state file",
    )
```

On `Config`, after `mode_source`:

```python
    # Whether one claude session spans the iterations, and what decided it.
    # The source is carried for the same reason mode_source is: a resumed
    # iteration and a fresh one both exit 0 and neither marks the state file,
    # so the header line is the only thing that can ever tell them apart.
    session: bool = backend.SESSION_DEFAULT
    session_source: str = backend.DEFAULT_SOURCE
```

Module level:

```python
# What the header prints when the flag, rather than a config file, turned
# continuity off.
SESSION_FLAG_SOURCE = "--no-session"

# claude's own flags for choosing a conversation. Refused inside -f while lmi
# is managing the session, because -f is appended last and the CLI takes the
# last occurrence of a repeated option: forwarding one of these does not add a
# flag, it overrides the one holding the run together. Both spellings of each,
# since -f is verbatim tokens - lmi's own -r and -c are unaffected and keep
# meaning the state file and the iteration count.
SESSION_FLAGS = ("--resume", "-r", "--continue", "-c", "--session-id",
                 "--fork-session")

SESSION_FLAG_IN_F = (
    "-f cannot carry %s while lmi is keeping one claude session across the\n"
    "    iterations: -f is appended last and claude takes the last occurrence\n"
    "    of a repeated option, so your flag would replace lmi's own and the\n"
    "    log would not show it happened.\n"
    "\n"
    "    Either drop it, or take the session over yourself with --no-session,\n"
    "    which leaves every -f flag untouched."
)
```

In `build_config`, after `_reject_output_format`:

```python
    session, session_source = _resolve_session(args)
    _reject_session_flags(session, user_flags)
```

passing `session=session, session_source=session_source` into the `Config(...)`
call, and:

```python
def _resolve_session(args):
    """(on?, what decided it). The flag beats the file beats the default.

    `--no-session` is store_false with a None default, so "the operator said
    off" is distinguishable from "nothing said anything" without a sentinel of
    our own - the same trick -i and -c use to tell `-i 0` from "-i absent".
    """
    asked = getattr(args, "session", None)
    if asked is False:
        return False, SESSION_FLAG_SOURCE
    return backend.resolve_session(getattr(args, "config", None))


def _reject_session_flags(session, user_flags):
    """Refuse claude's conversation flags in -f while lmi manages the session.

    Validation, not rewriting: the same narrow shape as
    _reject_output_format - six names known by name, only in order to decline
    them, no flag grammar learned. Refused rather than dropped, because -f is
    where a site puts what it cannot say any other way and a silently ignored
    flag is the failure -f validation exists to prevent.
    """
    if not session:
        return
    for token in user_flags:
        name = token.split("=", 1)[0]
        if name in SESSION_FLAGS:
            raise LmiError(SESSION_FLAG_IN_F % name, EXIT_USAGE)
```

Then in `tests/commands/schedule/conftest.py`, `make_cfg`'s field dict gains:

```python
            # Spelled out for the same reason `mode` is: the default is ON, and
            # a factory that quietly produced a session-carrying Config would
            # put every test using it on the path it probably did not mean.
            session=True,
            session_source=FIXTURE_SOURCE,
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest tests/commands/schedule/test_config.py -q` → PASS.
Then `python3 -m pytest tests/ -q` → all green (some runner tests may now log a
session line; none assert on the absence of one).

- [ ] **Step 5: Commit**

```bash
git add lmi/commands/schedule/config.py tests/commands/schedule/test_config.py \
        tests/commands/schedule/conftest.py
git commit -m "feat: add --no-session, and refuse claude's session flags in -f"
```

---

### Task 4: `Outcome`, the CLI backend's flags, and the runner's handle

The task that makes continuity actually happen in `cli` mode. `Outcome` lands here because both backends must return it from this commit on.

**Files:**
- Modify: `lmi/commands/schedule/backend.py` (`Outcome`)
- Modify: `lmi/commands/schedule/runner.py`
- Modify: `lmi/commands/schedule/sdk.py` (return an `Outcome`; session options come in Task 5)
- Test: `tests/commands/schedule/test_runner.py`

**Interfaces:**
- Consumes: `session.prepare/remint/warn_if_moved`, `paths.resolve_session`, `cfg.session`, `cfg.session_source`.
- Produces: `backend.Outcome(rc, quota, unresumable)`; `_CliBackend.call(cfg, log, composed, state_path, tmp_dir, n, handle) -> Outcome`; `describe(cfg, log, handle)`; `runner._session_line(cfg, handle) -> str`.

- [ ] **Step 1: Write the failing tests**

In `tests/commands/schedule/test_runner.py`:

```python
def test_iteration_one_mints_and_the_rest_resume(fake_claude, cli_mode, tmp_path, make_cfg):
    """MANDATORY - the whole feature, in the mode that has an argv to read.

    One session across the intervals: --session-id once, --resume after, the
    same id throughout."""
    cfg = make_cfg(tmp_path, interval_min=0, max_runs=3)
    assert main_run(cfg) == 0

    first = _argv(fake_claude, 1)
    assert "--session-id" in first
    sid = first[first.index("--session-id") + 1]
    for n in (2, 3):
        argv = _argv(fake_claude, n)
        assert "--resume" in argv
        assert argv[argv.index("--resume") + 1] == sid
        assert "--session-id" not in argv


def test_the_session_flags_come_before_the_user_flags(fake_claude, cli_mode, tmp_path, make_cfg):
    """-f must stay last: that ordering is what item 26 and item 46 rest on."""
    cfg = make_cfg(tmp_path, user_flags=["--model", "opus"])
    main_run(cfg)
    argv = _argv(fake_claude, 1)
    assert argv.index("--session-id") < argv.index("--model")


def test_no_session_puts_no_session_flag_on_the_argv(fake_claude, cli_mode, tmp_path, make_cfg):
    cfg = make_cfg(tmp_path, session=False, max_runs=2, interval_min=0)
    main_run(cfg)
    for n in (1, 2):
        argv = _argv(fake_claude, n)
        assert "--session-id" not in argv and "--resume" not in argv


def test_the_header_names_the_session_and_what_chose_it(fake_claude, cli_mode, tmp_path, make_cfg):
    """MANDATORY - item 58, item 33's rule for the second switch in this
    command. Both a resumed and a fresh iteration exit 0 and neither marks the
    state file: this line is the only record of which one ran."""
    cfg = make_cfg(tmp_path)
    main_run(cfg)
    log = _log_text(tmp_path)
    assert "Session   : on (from " in log
    assert "(new)" in log


def test_the_header_says_off_and_names_the_flag(fake_claude, cli_mode, tmp_path, make_cfg):
    cfg = make_cfg(tmp_path, session=False, session_source="--no-session")
    main_run(cfg)
    assert "Session   : off (from --no-session)" in _log_text(tmp_path)


def test_a_resumed_run_says_so_and_names_when_the_session_was_created(
    fake_claude, cli_mode, tmp_path, make_cfg
):
    cfg = make_cfg(tmp_path, resume=True)
    main_run(cfg)                                    # writes the sidecar
    main_run(make_cfg(tmp_path, resume=True))        # resumes it
    assert "resuming, created " in _log_text(tmp_path)


def test_an_iteration_that_never_reached_claude_keeps_the_session(
    fake_claude, cli_mode, tmp_path, make_cfg, monkeypatch
):
    """Item 12 plus item 54: a skipped iteration is not a reason to throw the
    session away, because nothing about the session was learned."""
    cfg = make_cfg(tmp_path, max_runs=2, interval_min=0)
    monkeypatch.setenv("FAKE_WRECK_TMP", "1")
    main_run(cfg)
    sid = json.loads(
        (tmp_path / "run-claude-state.md.session.json").read_text()
    )["session_id"]
    argv = _argv(fake_claude, 1)
    assert argv[argv.index("--session-id") + 1] == sid
```

`main_run`, `_argv` and `_log_text` are that module's existing helpers — reuse
whatever it already calls them; do not add new ones.

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/commands/schedule/test_runner.py -q`
Expected: FAIL — no `--session-id` on the argv, no `Session` line in the log.

- [ ] **Step 3: Implement `Outcome` in `backend.py`**

```python
class Outcome(NamedTuple):
    """What one call to either backend comes back with.

    Was a bare `(rc, quota)` tuple until sessions arrived. The third field is
    the one thing only the backend can know - whether claude said the
    conversation it was asked to resume does not exist - and the runner needs
    it to decide between "this session is gone" and every other failure, which
    it must not treat alike (items 54 and 55).

    A NamedTuple rather than a mutated handle, so the seam stays a function of
    its arguments: `call` reads a handle and returns a verdict, and nothing
    below the seam can quietly change the runner's state.
    """

    rc: int
    quota: bool
    unresumable: bool = False
```

(add `from typing import NamedTuple` at the top of `backend.py`.)

- [ ] **Step 4: Implement the CLI backend and the runner**

In `runner.py`, replace `_claude_argv` and give the backend the handle:

```python
def _claude_argv(cfg, state_path, claude):
    """Everything that is fixed for the whole run: no session flags, no -f.

    The session flags change per iteration - a fresh session is minted once and
    resumed afterwards - so they are appended in `call`, and -f after them,
    because -f must stay last. That ordering is load-bearing: item 26 and item
    46 are both about claude taking the LAST occurrence of a repeated option.
    """
    verbose = VERBOSE_FLAGS if cfg.verbose else []
    return [claude, "-p"] + DEFAULT_FLAGS + verbose + \
        ["--add-dir", str(state_path.parent)]


def _session_flags(handle):
    """The two spellings, and the one place the handle becomes an argv.

    `--session-id` names a session that does not exist yet; `--resume`
    continues one that does. Getting them the wrong way round is not a subtle
    failure - claude refuses both - which is the good kind of load-bearing.
    """
    if handle is None:
        return []
    if handle.resuming:
        return ["--resume", handle.id]
    return ["--session-id", handle.id]
```

`_CliBackend.describe` and `call`:

```python
    def describe(self, cfg, log, handle):
        log.line("claude    : " + self.argv[0])
        # The complete flag list, which docs/schedule.md's Logging section
        # promises - including the session flag this iteration will carry, so
        # the line stays the argv that actually runs.
        log.line("Flags     : " + " ".join(
            self.argv[1:] + _session_flags(handle) + list(cfg.user_flags)
        ))

    def call(self, cfg, log, composed, state_path, tmp_dir, n, handle):
        prompt_path = tmp_dir / ("prompt-%d.txt" % n)
        with open(str(prompt_path), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(composed)
        out_path = tmp_dir / ("out-%d.txt" % n)
        argv = self.argv + _session_flags(handle) + list(cfg.user_flags)

        if cfg.verbose:
            return _stream_claude(cfg, log, argv, prompt_path)
        return _capture_claude(cfg, log, argv, prompt_path, out_path)
```

`_capture_claude` / `_stream_claude` return an `Outcome`, and `_pump` reports
both verdicts off the same raw text — one scan, so the two tags cannot drift:

```python
def _pump(log, lines, render=None):
    """Log every line as it arrives. (quota?, unresumable?) off the RAW line.

    Both verdicts are read before anything renders the line, for item 28's
    reason and now for a second one: the "no conversation found" line is
    claude's own diagnostic, and a renderer that summarised it would leave the
    runner unable to tell a dead session from any other failure.
    """
    quota = unresumable = False
    for raw in lines:
        if QUOTA_RE.search(raw):
            quota = True
        if backend.UNRESUMABLE_RE.search(raw):
            unresumable = True
        log.line(render(raw) if render else raw)
    return quota, unresumable
```

with both call sites becoming, e.g.:

```python
    quota, unresumable = _pump(log, output.splitlines())
    log.line("--- end of claude output ---")
    return backend.Outcome(completed.returncode, quota, unresumable)
```

`_SdkBackend` mirrors the signature (`describe(self, cfg, log, handle)` calling
`sdk.describe(cfg, log)`, `call(..., handle)` calling
`sdk.call(cfg, log, composed, state_path, handle)`).

The header:

```python
def _session_line(cfg, handle):
    """One line, naming the session and what chose it - item 58.

    Shaped like the Backend line above it, "<value> (from <source>)", because
    they answer the same kind of question and an operator reads them together.
    """
    if handle is None:
        return "Session   : off (from %s)" % cfg.session_source
    what = ("resuming, created %s" % handle.created) if handle.resuming else "new"
    return "Session   : on (from %s) - %s (%s)" % (
        cfg.session_source, handle.id, what
    )
```

called from `_log_header` right after the `Backend` line, with `_log_header`
and `describe` both taking `handle`.

`_run_locked` resolves the sidecar and prepares the handle **before** the
header, because the header has to name it, and threads it through the loop:

```python
def _run_locked(cfg, log, state_path, run_ts, chosen):
    chosen.prepare(cfg, state_path)
    session_path = paths.resolve_session(state_path)
    # Before the header, because the header names the session (item 58). The
    # state file's own prepare() stays where it is, below - its lines are part
    # of the run's body, not of the resolved configuration. The two follow ONE
    # -r rule, and a test pins the pair rather than either half.
    handle = session.prepare(cfg, session_path, run_ts, log)
    _log_header(cfg, log, state_path, chosen, handle)

    state.prepare(state_path, cfg.resume, run_ts, log)
    ...
            rc, handle = _iteration_rc(
                cfg, log, state_path, chosen, task, tmp_dir, iteration,
                label, started, prompt_log, session_path, handle
            )
```

`_iteration_rc` returns the pair and keeps the handle on every failure path:

```python
def _iteration_rc(cfg, log, state_path, chosen, task, tmp_dir, n, label, started,
                  prompt_log, session_path, handle):
    """(exit code, handle to use next) with invariant 2 enforced around it."""
    try:
        return _one_iteration(
            cfg, log, state_path, chosen, task, tmp_dir, n, label, started,
            prompt_log, session_path, handle
        )
    except LmiError:
        raise
    except Exception:
        log.error("could not run iteration %s - it was skipped:" % label)
        _log_traceback(log)
        # The handle is returned unchanged, deliberately. An iteration that
        # never reached claude learned nothing about the session, and throwing
        # one away for a vanished temp workspace is item 54's mistake with a
        # different cause.
        return ITERATION_ERROR_RC, handle
```

and `_one_iteration` does the work (the retry is Task 6; this commit leaves the
`unresumable` field read but unacted on, marked as such):

```python
def _one_iteration(cfg, log, state_path, chosen, task, tmp_dir, n, label, started,
                   prompt_log, session_path, handle):
    body = state.read_body(state_path)
    composed = prompt.compose(cfg, state_path, label, started, body, task)
    prompt_log.emit(log, composed, body)

    if handle is not None:
        session.warn_if_moved(handle, cfg.work_dir, log)

    outcome = chosen.call(cfg, log, composed, state_path, tmp_dir, n, handle)
    if handle is not None:
        # After the call, whatever it returned. A call that failed part-way may
        # still have created the session, and item 54 is that a failure - a
        # usage limit above all - is not a reason to start over.
        handle = handle._replace(resuming=True)

    if outcome.quota:
        log.line(
            "[QUOTA] *** Possible quota, rate limit or overload problem in the "
            "claude output above."
        )
        log.line(
            "[QUOTA] *** Check your usage before trusting the result of this "
            "iteration."
        )
    return outcome.rc, handle
```

Add `session` to the module's imports.

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest tests/commands/schedule/ -q` → PASS (SDK-mode tests
included: they go through the same seam).
Then `python3 -m pytest tests/ -q`.

- [ ] **Step 6: Commit**

```bash
git add lmi/commands/schedule/backend.py lmi/commands/schedule/runner.py \
        lmi/commands/schedule/sdk.py tests/commands/schedule/test_runner.py
git commit -m "feat: carry one claude session across the intervals in cli mode"
```

---

### Task 5: The same thing in SDK mode

**Files:**
- Modify: `lmi/commands/schedule/sdk.py`
- Modify: `tests/commands/schedule/sdk_fake.py`
- Test: `tests/commands/schedule/test_sdk.py`, `tests/commands/schedule/test_sdk_fake_shapes.py`

**Interfaces:**
- Consumes: `session.Handle`, `backend.Outcome`, `backend.UNRESUMABLE_RE`.
- Produces: `sdk.call(cfg, log, composed, state_path, handle) -> backend.Outcome`, `sdk.require(session=False)`, `sdk.SESSION_FIELDS`, `sdk.OLD_SDK`.

- [ ] **Step 1: Write the failing tests**

In `tests/commands/schedule/test_sdk.py`:

```python
def test_a_fresh_session_is_passed_as_session_id(fake_sdk, tmp_path, make_cfg):
    """MANDATORY - parity. The mechanism is the same in both backends: mint an
    id, name it, then resume it."""
    cfg = make_cfg(tmp_path, max_runs=3, interval_min=0)
    assert main_run(cfg) == 0

    first = fake_sdk.options[0]
    assert first.session_id and first.resume is None
    for options in fake_sdk.options[1:]:
        assert options.resume == first.session_id
        assert options.session_id is None


def test_no_session_passes_neither(fake_sdk, tmp_path, make_cfg):
    cfg = make_cfg(tmp_path, session=False)
    main_run(cfg)
    assert fake_sdk.options[0].session_id is None
    assert fake_sdk.options[0].resume is None


def test_fork_session_is_never_set(fake_sdk, tmp_path, make_cfg):
    """MANDATORY - item 59. A fork returns a NEW id per iteration, so the
    sidecar's handle goes stale while every iteration looks like a correct
    resume."""
    main_run(make_cfg(tmp_path, max_runs=2, interval_min=0))
    for options in fake_sdk.options:
        assert options._extra.get("fork_session") is None
        assert options._extra.get("continue_conversation") is None


def test_a_session_id_that_comes_back_different_is_warned_about(
    fake_sdk, tmp_path, make_cfg, monkeypatch
):
    """SDK-only by declaration, not by accident: CLI mode's plain output
    carries no session id at all, and changing its format is item 26."""
    monkeypatch.setenv("FAKE_SDK_SESSION_ID", "a-different-session")
    main_run(make_cfg(tmp_path, max_runs=2, interval_min=0))
    log = _log_text(tmp_path)
    assert "[WARN]" in log and "a-different-session" in log


def test_the_unresumable_wording_on_stderr_is_reported(fake_sdk, tmp_path, make_cfg,
                                                       monkeypatch):
    """The SDK spawns the same CLI, so this is where its diagnostic surfaces."""
    monkeypatch.setenv(
        "FAKE_SDK_STDERR",
        "No conversation found with session ID: 1111-2222",
    )
    monkeypatch.setenv("FAKE_RC", "1")
    outcome = _call_once(make_cfg(tmp_path))
    assert outcome.unresumable is True


def test_require_refuses_an_sdk_without_the_session_fields(monkeypatch):
    """MANDATORY - item 59/44's shape: importable is not the same as able to
    build its options. Passing a keyword the dataclass lacks is a TypeError on
    EVERY iteration, and this raises once, before the lock."""
    import dataclasses

    @dataclasses.dataclass
    class _Old:
        cwd: str = ""

    module = types.ModuleType("claude_agent_sdk")
    module.ClaudeAgentOptions = _Old
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", module)

    with pytest.raises(LmiError) as exc:
        sdk.require(session=True)
    assert exc.value.code == EXIT_USAGE
    assert "--no-session" in str(exc.value)
    # And with continuity off, the same old SDK is fine: nothing that ran
    # before this feature stops running because of it.
    sdk.require(session=False)
```

In `tests/commands/schedule/test_sdk_fake_shapes.py`, add to the module that
skips without the extra:

```python
def test_the_real_options_accept_the_session_fields():
    """MANDATORY - the fake is only evidence if the real dataclass agrees.

    Verified by hand against 0.2.136, the current floor: both fields exist
    there, which is why the floor does not move. This is the assertion that
    keeps that true.
    """
    import dataclasses
    from claude_agent_sdk import ClaudeAgentOptions
    names = {f.name for f in dataclasses.fields(ClaudeAgentOptions)}
    assert {"session_id", "resume"} <= names


def test_the_real_result_message_carries_a_session_id():
    """What the id-mismatch check in sdk.py reads."""
    import dataclasses
    from claude_agent_sdk import ResultMessage
    names = {f.name for f in dataclasses.fields(ResultMessage)}
    assert "session_id" in names
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/commands/schedule/test_sdk.py -q`
Expected: FAIL — `AttributeError: 'ClaudeAgentOptions' object has no attribute 'session_id'`.

- [ ] **Step 3: Teach the fake the two fields and the echo knob**

In `sdk_fake.py`'s `ClaudeAgentOptions.__init__`, beside the others:

```python
        # Spelled out rather than left in _extra, because a test asserting on
        # them must fail loudly when sdk.py stops passing them - not read None
        # off a silently absent attribute. Both are real fields of the real
        # dataclass at the floor version, checked by test_sdk_fake_shapes.
        self.session_id = kw.get("session_id")
        self.resume = kw.get("resume")
```

In `_messages`, echo the requested id — which is what the real SDK does — with
a knob to force a mismatch:

```python
def _session_id(n, recorder):
    """The id the fake reports back, as the real SDK reports the one in use.

    Echoing the requested id is the realistic default and is what makes the
    mismatch check testable at all: a fake that always invented an id would
    make the warning fire on every run, and the test would pass without
    telling anything apart.
    """
    forced = _env("FAKE_SDK_SESSION_ID")
    if forced:
        return forced
    options = recorder._current
    return (getattr(options, "resume", None)
            or getattr(options, "session_id", None)
            or "s%d" % n)
```

and use it for the `session_id` of the init `data`, the `RateLimitEvent` and the
`ResultMessage` (replacing `"s%d" % n` in those three places).

- [ ] **Step 4: Implement in `sdk.py`**

```python
SESSION_FIELDS = ("session_id", "resume")

OLD_SDK = (
    "the installed Claude Agent SDK cannot carry a claude session across\n"
    "    iterations: its ClaudeAgentOptions has no %s field.\n"
    "\n"
    "    Two ways out:\n"
    "\n"
    "      - upgrade it, which is what the `%s` extra pins:\n"
    '            pip install --upgrade "lmi[sdk]"\n'
    "      - or run without continuity, which is how `lmi schedule` behaved\n"
    "        before this existed - each iteration fresh, the state file\n"
    "        carrying the work:\n"
    "            lmi schedule ... --no-session\n"
    "\n"
    "    Checked here, once, rather than at the call: passing a keyword the\n"
    "    dataclass does not define is a TypeError on every iteration of the\n"
    "    run, and importable has never meant able to build its options."
)


def require(session=False):
    """Fail now if this backend cannot run at all.

    `session` is checked separately from the import because the two failures
    have different fixes and different blast radii: no SDK at all stops every
    run, while an SDK too old for `session_id` stops only the runs that want
    continuity - and those can still run with --no-session.
    """
    module = _import()
    if session:
        _require_session_fields(module)


def _require_session_fields(module):
    """Exit 2 when the installed options object has no session fields.

    `dataclasses.fields` raises TypeError for anything that is not a
    dataclass - the suite's fake among them - and that is treated as "nothing
    to check" rather than as a failure: this guard exists to catch an SDK older
    than the floor, not to insist on how the class is built.
    """
    import dataclasses
    try:
        names = {f.name for f in dataclasses.fields(module.ClaudeAgentOptions)}
    except TypeError:
        return
    missing = [name for name in SESSION_FIELDS if name not in names]
    if missing:
        raise LmiError(OLD_SDK % (missing[0], backend.SDK), EXIT_USAGE)
```

`_options` takes the handle:

```python
def _options(cfg, state_path, on_stderr, handle):
    module = _import()
    kwargs = dict(
        allowed_tools=list(backend.ALLOWED_TOOLS),
        add_dirs=[str(state_path.parent)],
        cwd=str(cfg.work_dir),
        permission_mode=PERMISSION_MODE,
        setting_sources=list(SETTING_SOURCES),
        stderr=on_stderr,
        extra_args=parse_flags(cfg.user_flags),
    )
    if handle is not None:
        # One of the two, never both, and never fork_session: a fork returns a
        # different id per iteration, so the sidecar would go stale while every
        # iteration looked like a correct resume. The CLI backend's
        # --session-id / --resume pair, one for one.
        if handle.resuming:
            kwargs["resume"] = handle.id
        else:
            kwargs["session_id"] = handle.id
    return module.ClaudeAgentOptions(**kwargs)
```

`call` and `_drive` take and pass the handle; `_Sink` learns two things:

```python
    def __init__(self, cfg, log, handle=None):
        ...
        self.unresumable = False
        self.handle = handle
        self._warned_id = False

    def _scan(self, text):
        if not text:
            return
        if backend.QUOTA_RE.search(text):
            self.quota = True
        if backend.UNRESUMABLE_RE.search(text):
            self.unresumable = True

    def _check_id(self, message):
        """Warn when the session that answered is not the one asked for.

        Free here, because every message is walked already - and impossible in
        CLI mode, whose plain output carries no id. Declared as asymmetric in
        docs/status.md rather than faked on the other side.
        """
        if self.handle is None or not self.handle.resuming or self._warned_id:
            return
        got = _session_id_of(message)
        if got and got != self.handle.id:
            self._warned_id = True
            self.log.warn(
                "asked to resume the claude session %s and got %s instead - "
                "this iteration is not continuing the context the previous one "
                "built. The state file still carries the work forward."
                % (self.handle.id, got)
            )
```

with `_check_id(message)` called from `message()` right after the scan, and:

```python
def _session_id_of(message):
    """The session id a message reports, across the two shapes that carry one.

    ResultMessage and AssistantMessage have a `session_id` field; SystemMessage
    carries its init payload in `data`. Both verified against 0.2.136.
    """
    direct = getattr(message, "session_id", None)
    if isinstance(direct, str) and direct:
        return direct
    data = getattr(message, "data", None)
    if isinstance(data, dict):
        got = data.get("session_id")
        if isinstance(got, str) and got:
            return got
    return None
```

and `call` returning the widened verdict:

```python
    return backend.Outcome(sink.rc, sink.quota, sink.unresumable)
```

Finally, `runner._select_backend` passes the flag through:
`sdk.require(cfg.session)`.

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest tests/commands/schedule/ -q` → PASS.
Then both suite runs:

```bash
python3 -m pytest tests/ -q
PYTHONPATH=<dir with claude_agent_sdk> python3 -m pytest tests/ -q
```

The second is how the two new shape assertions actually execute; without the
extra they skip, which is the point of that module.

- [ ] **Step 6: Commit**

```bash
git add lmi/commands/schedule/sdk.py tests/commands/schedule/sdk_fake.py \
        tests/commands/schedule/test_sdk.py \
        tests/commands/schedule/test_sdk_fake_shapes.py
git commit -m "feat: carry the same session in sdk mode, and refuse an SDK that cannot"
```

---

### Task 6: The two failures that must not be confused

**Files:**
- Modify: `lmi/commands/schedule/runner.py`
- Test: `tests/commands/schedule/test_runner.py`, `tests/conftest.py` (`fake_claude` knob)

**Interfaces:**
- Consumes: `backend.Outcome.unresumable`, `session.remint`.
- Produces: no new names; `_one_iteration` gains the retry.

- [ ] **Step 1: Write the failing tests**

In `tests/conftest.py`, add the knob to `FAKE` — before the plain-output branch,
so it fires in both verbosity modes:

```python
gone = os.environ.get("FAKE_SESSION_GONE")
if gone and int(gone) == n and "--resume" in sys.argv:
    # claude 2.1.235's own wording and exit code for a session that is not
    # there, verified by running it. Printed and gone: the lookup is local, so
    # no API call happens and the retry the runner does costs nothing.
    sid = sys.argv[sys.argv.index("--resume") + 1]
    print("No conversation found with session ID: %s" % sid)
    sys.exit(1)
```

In `tests/commands/schedule/test_runner.py`:

```python
def test_a_quota_failure_keeps_the_session(fake_claude, cli_mode, tmp_path,
                                           make_cfg, monkeypatch):
    """MANDATORY - item 54, and the reason this feature was asked for.

    Iteration 1 fails on a usage limit. Iteration 2 must resume ITS session,
    not start a new one: the session is intact, and starting over is exactly
    what the operator wanted to stop doing.
    """
    monkeypatch.setenv("FAKE_RC", "1")
    monkeypatch.setenv("FAKE_OUT", "Claude AI usage limit reached|1234567890")
    cfg = make_cfg(tmp_path, max_runs=2, interval_min=0)

    assert main_run(cfg) == 1                       # both iterations failed
    first, second = _argv(fake_claude, 1), _argv(fake_claude, 2)
    sid = first[first.index("--session-id") + 1]
    assert second[second.index("--resume") + 1] == sid
    log = _log_text(tmp_path)
    assert "[QUOTA]" in log
    assert "could not be resumed" not in log        # nothing was dropped


def test_a_session_that_is_gone_is_dropped_and_retried_once(
    fake_claude, cli_mode, tmp_path, make_cfg, monkeypatch
):
    """MANDATORY - item 55. Iteration 2's resume fails because the session is
    not there; the iteration mints a fresh one and runs, rather than burning
    the interval or failing every iteration after it identically.
    """
    monkeypatch.setenv("FAKE_SESSION_GONE", "2")
    cfg = make_cfg(tmp_path, max_runs=3, interval_min=0)

    assert main_run(cfg) == 0                       # the retry succeeded
    assert _count(fake_claude) == 4                 # 1, 2 (failed), 2 retry, 3
    first = _argv(fake_claude, 1)
    old = first[first.index("--session-id") + 1]
    retry = _argv(fake_claude, 3)
    assert "--session-id" in retry
    new = retry[retry.index("--session-id") + 1]
    assert new != old
    # Iteration 3 resumes the NEW session, and the sidecar agrees.
    third = _argv(fake_claude, 4)
    assert third[third.index("--resume") + 1] == new
    assert json.loads(
        (tmp_path / "run-claude-state.md.session.json").read_text()
    )["session_id"] == new
    log = _log_text(tmp_path)
    assert "[WARN]" in log and old in log


def test_the_retry_happens_at_most_once_per_iteration(
    fake_claude, cli_mode, tmp_path, make_cfg, monkeypatch
):
    """MANDATORY - item 55's bound. A fake that fails EVERY resume must not
    turn one iteration into an unbounded call loop."""
    monkeypatch.setenv("FAKE_RC", "1")
    monkeypatch.setenv("FAKE_OUT", "No conversation found with session ID: x")
    cfg = make_cfg(tmp_path, max_runs=2, interval_min=0)

    assert main_run(cfg) == 1
    # Iteration 1 mints (no resume to fail), iteration 2 resumes, fails, and
    # retries exactly once. Four calls, never five.
    assert _count(fake_claude) <= 4


def test_a_quota_report_in_the_first_attempt_survives_the_retry(
    fake_claude, cli_mode, tmp_path, make_cfg, monkeypatch
):
    """[QUOTA] under-reporting is the dangerous direction (item 43), so the tag
    is either attempt's."""
    monkeypatch.setenv("FAKE_SESSION_GONE", "2")
    monkeypatch.setenv("FAKE_OUT", "you have exceeded your quota")
    cfg = make_cfg(tmp_path, max_runs=2, interval_min=0)
    main_run(cfg)
    assert "[QUOTA]" in _log_text(tmp_path)


def test_a_dead_session_in_sdk_mode_is_dropped_the_same_way(
    fake_sdk, tmp_path, make_cfg, monkeypatch
):
    """Parity, on the failure path as well as the happy one."""
    monkeypatch.setenv("FAKE_SDK_STDERR",
                       "No conversation found with session ID: gone")
    monkeypatch.setenv("FAKE_RC", "1")
    cfg = make_cfg(tmp_path, max_runs=2, interval_min=0, mode=backend.SDK)
    main_run(cfg)
    ids = [o.session_id for o in fake_sdk.options if o.session_id]
    assert len(ids) >= 2 and ids[0] != ids[-1]      # a fresh one was minted
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/commands/schedule/test_runner.py -q -k session`
Expected: FAIL — the call count is 3, not 4: nothing retries, and iteration 3
still resumes the dead id.

- [ ] **Step 3: Implement the retry in `_one_iteration`**

Replacing the "read but unacted on" comment from Task 4:

```python
    was_resuming = handle is not None and handle.resuming
    outcome = chosen.call(cfg, log, composed, state_path, tmp_dir, n, handle)
    if handle is not None:
        handle = handle._replace(resuming=True)

    if was_resuming and outcome.rc != 0 and outcome.unresumable:
        # The one condition that drops a session, and the one retry there is.
        #
        # Not "any failure": a usage limit leaves the conversation perfectly
        # intact and resuming it next interval is the whole point of the
        # feature (item 54). Not "no retry": the resume failed locally, before
        # any API call - claude prints "No conversation found" and exits 1 - so
        # trying again fresh costs nothing, where waiting for the next interval
        # costs a third of a `-c 3` run. And not "retry until it works": one
        # attempt, so a machine that fails every resume cannot turn one
        # iteration into an unbounded loop (item 55).
        handle = session.remint(cfg, session_path, log, handle)
        retry = chosen.call(cfg, log, composed, state_path, tmp_dir, n, handle)
        handle = handle._replace(resuming=True)
        # rc from the attempt that actually ran; quota from EITHER, because
        # under-reporting [QUOTA] is the dangerous direction and a limit
        # reported by the first attempt is no less real for the second.
        outcome = backend.Outcome(
            retry.rc, outcome.quota or retry.quota, retry.unresumable
        )
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest tests/commands/schedule/test_runner.py -q` → PASS.
Then `python3 -m pytest tests/ -q`, and the SDK run.

Then **invert each MANDATORY guard and watch it go red** — the only real
evidence a pinned test still pins anything:
- make the retry unconditional on `rc != 0` → `test_a_quota_failure_keeps_the_session` must fail;
- drop the `was_resuming` guard or the one-shot bound → the bound test must fail;
- take `or retry.quota` out → the quota-survives test must fail.

Put each back.

- [ ] **Step 5: Commit**

```bash
git add lmi/commands/schedule/runner.py tests/conftest.py \
        tests/commands/schedule/test_runner.py
git commit -m "feat: keep the session through a usage limit, drop it only when it is gone"
```

---

### Task 7: Documentation, and the rules that outlive it

**Files:**
- Modify: `docs/schedule.md`, `docs/config.md`, `docs/status.md`, `README.md`, `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-08-19-schedule-session-continuity-design.md` (the two §15 answers, and the two small deviations)
- Test: `tests/test_docs.py`

- [ ] **Step 1: Write the failing documentation tests**

In `tests/test_docs.py`, beside the existing needle tests:

```python
def test_the_user_docs_document_session_continuity():
    docs = user_docs()
    assert "--no-session" in docs
    assert "schedule.session" in docs
    # The sidecar, by name: an operator who finds the file next to their state
    # file must be able to search the documentation for it.
    assert ".session.json" in docs


def test_the_docs_say_a_usage_limit_keeps_the_session():
    """Item 54 is the reason the feature exists, so it is the one fact the
    documentation must not leave out."""
    docs = user_docs().lower()
    assert "usage limit" in docs or "quota" in docs
    assert "resume" in docs


def test_claude_md_still_states_that_a_quota_failure_keeps_the_session():
    """MANDATORY - the same argument as the item-22 check in this module: this
    rule exists in one place in the code, has no symptom when inverted, and
    CLAUDE.md is the only file that says why."""
    text = Path("CLAUDE.md").read_text(encoding="utf-8")
    assert "A quota failure must not discard the session" in text
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/test_docs.py -q` → FAIL on the missing needles.

- [ ] **Step 3: Write the documentation**

`docs/schedule.md` — a new section after the state file's, covering: what
continuity is and that it is on by default; the sidecar's name and that it is
backed up or kept exactly as the state file is, by `-r`; that the session is
tied to the working directory, so `-d` must not move; the six `-f` flags that
are refused and that `--no-session` hands them back; the header's `Session`
line; the retry and the `[WARN]` an operator will see; and §11's cost note —
input tokens grow across a run, long sessions compact, which is why the state
file is still the authority.

`docs/config.md` — `schedule.session` beside `schedule.mode`: `true` by
default, `false` to turn continuity off machine-wide, absent means the default
and `null` is refused.

`docs/status.md` — the two facts only a real run settles: that a `--resume`
iteration really does carry the earlier context, and the SDK-only id-mismatch
warning, with the CLI's inability to observe an id recorded as a declared gap.
Add the measured suite numbers from Step 4.

`README.md` — one line where `lmi schedule` is described.

`CLAUDE.md` — section 2's file list gains `session.py` ("the session carried
across the intervals, and the sidecar that remembers it"); the seam paragraph's
"`(exit code, quota?)` pair" becomes `backend.Outcome`; section 3 gains items
53-59 verbatim from spec §12; section 4.1 and section 5 get the re-measured
counts.

- [ ] **Step 4: Re-measure the suite and write the real numbers down**

```bash
python3 -m pytest tests/ -q                       # without the extra
PYTHONPATH=<dir with claude_agent_sdk> python3 -m pytest tests/ -q
```

Write both **measured** figures into CLAUDE.md section 4.1 and section 5, and
record that the second is now measured rather than arithmetic — it had been
arithmetic for four consecutive changes. Do not adjust the old number by the
count of tests you think you added.

- [ ] **Step 5: Close the spec's open questions**

In the spec, replace §15's two open questions with their answers, and record
the two deviations this implementation made and why:
- **The floor does not move.** `claude-agent-sdk==0.2.136`, the current floor,
  already has `session_id` and `resume` on `ClaudeAgentOptions` and
  `session_id` on `ResultMessage` — verified by inspecting the installed
  package. §9's runtime check stays; its floor bump is dropped.
- **The sidecar is prepared before the header, not literally inside
  `state.prepare`.** The header must name the session (item 58), so the handle
  has to exist before it; the state file's own lines belong to the run's body.
  The `-r` rule is one rule, pinned by a test on the pair rather than by the
  two calls sharing a function.

- [ ] **Step 6: Run everything and commit**

```bash
python3 -m pytest tests/ -q
git add docs README.md CLAUDE.md tests/test_docs.py
git commit -m "docs: document session continuity, and pin the rule that a quota failure keeps it"
```

---

## Self-Review

**Spec coverage.** §2 → Task 3. §3 → Tasks 1 and 3 (the writer is declared out
of scope in the spec itself). §4 → Task 2. §5 → Task 2, with the placement
deviation recorded in Task 7 Step 5. §6 → Tasks 4 and 5. §7 → Tasks 4, 5 and 6.
§8 → Task 4. §9 → Task 5, minus the floor bump, which measurement removed.
§10 → Task 3. §11 → Task 7. §12 → Task 7. §13 → spread across every task's
tests, with `test_docs` in Task 7. §14 → Task 7. §15 → Task 7 Step 5.

**Placeholders.** One deliberate `<dir with claude_agent_sdk>` in two commands,
which is a local path that cannot be written down here. No TBDs, no "add
appropriate error handling", every code step carries the code.

**Type consistency.** `Handle(id, resuming, created, work_dir)` is constructed
in Task 2 and read in Tasks 4, 5 and 6 under those names; `Outcome(rc, quota,
unresumable)` is defined in Task 4 and returned by both backends from that
commit on; `session.prepare/remint/warn_if_moved` and `paths.resolve_session`
keep their Task 2 signatures throughout; `sdk.require(session=False)` is called
as `sdk.require(cfg.session)` in Task 5.
