"""A whole fake `claude_agent_sdk`, and the shapes it emits.

**Containment is this module's first purpose, not its second.** `fake_claude`
protects the CLI suite by replacing PATH entirely, and that protects nothing at
all once the call is a Python import: the real SDK spawns a bundled Claude Code
binary, so an SDK-mode test that reached the real package would spend real
money on the site's account. The guarantee here is total - the fixture puts
this module into `sys.modules["claude_agent_sdk"]`, so `sdk._import()`'s
`import claude_agent_sdk` finds it and **no line of the real package is ever
executed**, installed or not.

That is deliberately NOT the SDK's documented `query(transport=...)` injection
point. A transport still runs the real package's own machinery around it, and
reaching it would mean giving `sdk.py` a parameter that exists only for tests -
production code shaped by its test suite. Replacing the module is both stricter
and invisible to `sdk.py`, which keeps its one plain `import`.

It lives in its own module rather than in conftest.py so that the shapes below
can be imported by the test that validates them field by field against the real
dataclasses (skipping cleanly when the extra is absent). A fake that emits a
shape the real SDK never produces is worse than no fake at all: every test
built on it is then green about something that cannot happen.
"""

import os
import types
from pathlib import Path


class _Shape:
    """Attributes in, attributes out. The base of every shape below.

    The renderer and `sdk.py` reach everything through `getattr` and match on
    `type(x).__name__` - never `isinstance` - which is exactly what lets these
    stand in for the real dataclasses. `__dict__` is populated because
    `stream._fields` reads `vars(message)` when it describes a message it
    cannot render.
    """

    def __init__(self, **kw):
        for key, value in kw.items():
            setattr(self, key, value)

    def __repr__(self):
        return "%s(%s)" % (
            type(self).__name__,
            ", ".join("%s=%r" % kv for kv in sorted(vars(self).items())),
        )


# --- the shapes -----------------------------------------------------------
#
# Named exactly as the real SDK names them, because that name IS the matching
# key in stream.py and sdk.py. A typo here does not fail loudly - it produces a
# fake whose messages all fall through to the "unrecognised shape" row, which
# is a green suite testing the degrade path and nothing else.

class TextBlock(_Shape):
    pass


class ThinkingBlock(_Shape):
    pass


class ToolUseBlock(_Shape):
    pass


class ToolResultBlock(_Shape):
    pass


class SystemMessage(_Shape):
    pass


class AssistantMessage(_Shape):
    pass


class UserMessage(_Shape):
    pass


class ResultMessage(_Shape):
    pass


class RateLimitInfo(_Shape):
    """What a RateLimitEvent carries. Field names are the real ones.

    Nothing reads these individually - the whole object is str()'d by
    sdk._raw_text - but a fake whose field names were invented would make the
    quota test green about a shape that cannot occur.
    """


class RateLimitEvent(_Shape):
    """The SDK's own name for the thing [QUOTA] exists to catch.

    Emitted by the real package's message parser, so it reaches query()'s
    stream. It carries its entire payload in `rate_limit_info` and in none of
    the fields a result or an assistant message uses - which is how it went
    unscanned: see CLAUDE.md item 43.
    """


class ClaudeAgentOptions(_Shape):
    """What `sdk._options` built, kept so a test can assert on it.

    This is the seam tasks 32, 33 and 34 are tested at: the options object is
    the SDK backend's whole equivalent of the CLI backend's argv, so the four
    values that decide what Claude may do - the tools, the extra directory, the
    working directory, the permission mode - and the settings sources are only
    observable here.
    """

    def __init__(self, **kw):
        # Spelled out rather than **kw straight through, so that a keyword
        # sdk._options stops passing turns into an AttributeError in the test
        # that asserts on it, rather than a silent None.
        self.allowed_tools = kw.get("allowed_tools")
        self.add_dirs = kw.get("add_dirs")
        self.cwd = kw.get("cwd")
        self.permission_mode = kw.get("permission_mode")
        self.setting_sources = kw.get("setting_sources")
        self.stderr = kw.get("stderr")
        # The one thing that must never be set. Invariant 3: nothing in the
        # unattended runner may wait for a keypress, and a can_use_tool callback
        # that awaits anything is precisely that - it would hang the run rather
        # than fail it. Recorded so a test can assert it stayed absent.
        self.can_use_tool = kw.get("can_use_tool")
        # The session pair, spelled out rather than left to _extra for the same
        # reason as everything above: a test asserting on them must fail loudly
        # when sdk.py stops passing them, not read None off a silently absent
        # attribute. Both are real fields of the real ClaudeAgentOptions at the
        # floor version, which test_sdk_fake_shapes.py asserts - a fake that
        # accepted a keyword the real dataclass rejects would make every session
        # test green about a TypeError.
        self.session_id = kw.get("session_id")
        self.resume = kw.get("resume")
        self._extra = {k: v for k, v in kw.items() if k not in vars(self)}


# --- the script -----------------------------------------------------------

def _env(name, default=None):
    return os.environ.get(name, default)


def _write_state(n):
    """The FAKE_STATE_FILE knobs, byte for byte as the CLI fake writes them.

    Shared wording on purpose: FAKE_PROSE and FAKE_BLANK_FIRST_LINE are the
    fixtures for regression 2, and a state file that differed between the two
    modes would let the completion check be widened in one of them without the
    suite noticing.
    """
    sf = _env("FAKE_STATE_FILE")
    if not sf:
        return
    at = _env("FAKE_COMPLETE_AT")
    if _env("FAKE_PROSE"):
        Path(sf).write_text(
            "TASK_STATUS: IN_PROGRESS\n\n## Goal\n\n"
            "only then may line 1 say TASK_STATUS: COMPLETE\n",
            encoding="utf-8",
        )
    elif _env("FAKE_BLANK_FIRST_LINE"):
        Path(sf).write_text(
            "\nTASK_STATUS: COMPLETE\n\n## Goal\n\nnot really done\n",
            encoding="utf-8",
        )
    elif at and int(at) == n:
        Path(sf).write_text("TASK_STATUS: COMPLETE\n", encoding="utf-8")


def _session_id(n, recorder):
    """The id the fake reports back, as the real SDK reports the one in use.

    Echoing the REQUESTED id is the realistic default and is what makes the
    mismatch check testable at all: a fake that always invented an id would fire
    the warning on every run, and the test would pass without telling anything
    apart. FAKE_SDK_SESSION_ID forces the mismatch instead.
    """
    forced = _env("FAKE_SDK_SESSION_ID")
    if forced:
        return forced
    # getattr, because test_sdk_fake_shapes drives _messages with a recorder
    # stub that carries only what the stream itself needs. A generator that
    # demanded more of its recorder than that would make the one module which
    # checks these shapes against the real package unable to run at all.
    options = getattr(recorder, "_current", None)
    return (getattr(options, "resume", None)
            or getattr(options, "session_id", None)
            or "s%d" % n)


def _messages(n, recorder):
    """One iteration's message stream, from the same FAKE_* knobs.

    The knob names are the CLI fake's wherever the knob means the same thing,
    so a regression test can be written once and run in both modes. Where a
    knob cannot mean the same thing it is absent rather than approximated:

      FAKE_STREAM          has no meaning here. The CLI fake needs it because
                           stream-json is a *format* it must opt into; the SDK
                           always delivers typed messages, and -v decides
                           whether they are rendered. The fake therefore always
                           emits the full sequence.
      FAKE_WRECK_TMP       has no meaning here either: this backend writes no
                           prompt file and uses no temp workspace, so deleting
                           one breaks nothing. Item 12's guarantee - an
                           exception mid-iteration must not abort the loop -
                           gets FAKE_SDK_RAISE_AT below instead, which is the
                           natural shape for a message stream.
    """
    sid = _session_id(n, recorder)
    yield SystemMessage(
        subtype="init",
        data={"model": "fake-model", "session_id": sid, "cwd": os.getcwd()},
    )
    yield AssistantMessage(
        content=[TextBlock(text="fake claude call %d" % n)],
        model="fake-model",
    )

    raise_at = _env("FAKE_SDK_RAISE_AT")
    if raise_at and int(raise_at) == n:
        # Part-way through, with messages already delivered: the realistic
        # shape of a stream that dies, and the one that proves _iteration_rc
        # records a skip and lets the loop carry on rather than the whole run
        # ending here.
        raise RuntimeError("the fake SDK transport died mid-stream")

    if _env("FAKE_SDK_STDERR"):
        # Routed through the options object the backend handed us, which is the
        # only path the real SDK offers for the underlying binary's
        # diagnostics. Without it they vanish from an unattended run's only
        # record.
        recorder.emit_stderr(_env("FAKE_SDK_STDERR"))

    if _env("FAKE_SDK_TOOL_INPUT"):
        # A Write whose `content` is the whole new file - item 29 and task 42.
        # ARG_KEYS is an allowlist precisely so this never reaches the log.
        yield AssistantMessage(content=[ToolUseBlock(
            name="Write",
            input={"file_path": "run-claude-state.md",
                   "content": _env("FAKE_SDK_TOOL_INPUT")},
        )])

    if _env("FAKE_SDK_RATE_LIMIT"):
        # A rate limit as the SDK actually reports one: its own event type,
        # with the wording nowhere near `result` or `content`. The CLI backend
        # catches the equivalent for free by scanning whole raw lines, so this
        # is the shape in which the two backends could silently disagree about
        # the only tag that says "do not trust this iteration".
        yield RateLimitEvent(
            rate_limit_info=RateLimitInfo(
                status=_env("FAKE_SDK_RATE_LIMIT"),
                resets_at=None,
                rate_limit_type="output_tokens",
                utilization=100,
                overage_status=None,
                overage_resets_at=None,
                overage_disabled_reason=None,
                raw={"status": _env("FAKE_SDK_RATE_LIMIT")},
            ),
            session_id=sid,
        )

    if _env("FAKE_SDK_UNKNOWN"):
        # A message type this lmi does not know, for the degrade-out-loud half
        # of task 41: exactly one [WARN], one dull line per message, exit 0.
        yield _Unknown(surprise="a later SDK grew a message type")

    if _env("FAKE_SDK_NO_RESULT"):
        # A stream that simply ends. The real SDK closes every completed query
        # with a ResultMessage, so its absence means the stream was cut off -
        # and that is a row in its own right, never a zero. Mapping it to 0 is
        # regression 1 with a new front end: the iteration is counted as a
        # success, the run exits 0, and nothing was done.
        return

    result = _env("FAKE_OUT") or "done"
    tail = _env("FAKE_STREAM_QUOTA_TAIL")
    if tail:
        # Past the renderer's clip width, as in the CLI fake, so the test can
        # tell scanning the message from scanning the rendered row.
        result = ("padding " * 40) + tail

    # FAKE_RC is the CLI fake's exit code. The SDK has none, so it is mapped to
    # the only thing that carries the same fact: a non-success subtype, which
    # sdk._rc_of turns into CALL_FAILED_RC. Both make main() return 1, which is
    # what a shared test asserts on.
    rc = int(_env("FAKE_RC", "0"))
    # FAKE_SDK_SUCCESS_SUBTYPE_ON_ERROR reproduces the combination a REAL failed
    # call carries, verified against 0.2.136 with no credential: subtype
    # "success" AND is_error true at the same time. It is the shape that made
    # gating on the subtype alone report a failed iteration as a successful one,
    # so the suite has to be able to emit it - the default shapes below cannot.
    subtype = "success" if rc == 0 else "error_during_execution"
    if rc and _env("FAKE_SDK_SUCCESS_SUBTYPE_ON_ERROR"):
        subtype = "success"
    yield ResultMessage(
        subtype=subtype,
        is_error=bool(rc),
        num_turns=2,
        duration_ms=1234,
        result=result,
        session_id=sid,
        total_cost_usd=0.0,
        usage={},
    )

    if _env("FAKE_SDK_RAISE_AFTER_RESULT"):
        # The real SDK's shape for a failed call, verified against 0.2.136: it
        # yields the ResultMessage and only THEN raises, on the error envelope
        # that follows it (_internal/query.py's receive_messages). An expired
        # login and an exhausted quota both arrive this way - so this, not
        # FAKE_SDK_RAISE_AT, is the common failure, and item 45 is about not
        # throwing away the rc and the quota flag the sink already computed.
        raise RuntimeError("Claude Code returned an error result: success")


class _Unknown(_Shape):
    """A shape stream.py has never heard of. Deliberately not SDK-named."""


class Recorder:
    """Everything the fake saw, for the test to assert on.

    The CLI fake records to files because it is a separate process; this one is
    in the same process, so it records to attributes. The one exception is the
    prompt and the call count, which are mirrored onto disk under the same
    names `fake_claude` uses - `prompt-N.txt` and the count file - so that a
    test asserting on the composed prompt reads the same way in both modes.
    """

    def __init__(self, rec_dir, count_file):
        self.dir = Path(rec_dir)
        self.count_file = Path(count_file)
        self.count_file.write_text("0")
        self.options = []       # one ClaudeAgentOptions per iteration
        self.prompts = []       # the composed prompt, per iteration
        self.n = 0
        self._current = None

    def start(self, prompt, options):
        self.n += 1
        self.count_file.write_text(str(self.n))
        self.options.append(options)
        self.prompts.append(prompt)
        self._current = options
        (self.dir / ("prompt-%d.txt" % self.n)).write_text(
            prompt or "", encoding="utf-8"
        )
        return self.n

    def emit_stderr(self, text):
        if self._current is not None and self._current.stderr is not None:
            self._current.stderr(text)


def build_module(recorder):
    """A module object that answers `import claude_agent_sdk`."""
    module = types.ModuleType("claude_agent_sdk")
    module.ClaudeAgentOptions = ClaudeAgentOptions
    module.__version__ = "0.0.0-fake"

    async def query(prompt=None, options=None, **kw):
        n = recorder.start(prompt, options)
        for message in _messages(n, recorder):
            yield message
        # After the stream, not before: the state file is what the real Claude
        # writes with the Write tool during the iteration, and the completion
        # check reads it once the call has returned.
        _write_state(n)

    module.query = query
    # The shapes, exported under the names the real package exports them under,
    # so a test can build a message the way production code would see one.
    for shape in (TextBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock,
                  SystemMessage, AssistantMessage, UserMessage, ResultMessage):
        setattr(module, shape.__name__, shape)
    return module
