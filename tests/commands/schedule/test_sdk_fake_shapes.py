"""Task 51: the fake SDK's shapes, checked against the real ones.

**A fake that emits a shape the real SDK never produces is worse than no fake
at all**, and this module is the only thing standing between the suite and that
state. Every SDK-mode test in this directory is built on `sdk_fake`, and both
`sdk.py` and `stream.py` reach the SDK's objects through `type(x).__name__` and
`getattr` - never `isinstance`, which is what keeps `claude_agent_sdk` imported
in exactly one module of `lmi/`. That duck-typing is deliberate and it has one
cost, paid here: **nothing else in the suite can tell a right name from a wrong
one.** A renamed field degrades to a dull log line, a renamed class degrades to
the "unrecognised shape" row, and a keyword `ClaudeAgentOptions` no longer
accepts is a TypeError on every single iteration - and a fake that made the same
mistake would be green about all three.

So the assertions run in both directions:

  * every class name the fake emits, and both renderers match on, exists in the
    real package;
  * every attribute the fake *sets* is a real field, so the fake cannot teach
    the suite about a field that does not exist;
  * every attribute lmi *reads* is a real field, which is the rename check that
    matters most, because `getattr(m, "subtype", None)` cannot fail loudly;
  * every keyword `sdk._options` passes is one the real `ClaudeAgentOptions`
    accepts, and the two literal values it chooses - the permission mode and
    the setting sources - are values the real package recognises.

Skipped, never errored, when the extra is absent: the import is guarded and the
marker computed from its result, in the style of `skip_as_root` in
tests/conftest.py. A `skipif` argument evaluated at import time is what loses a
whole module during collection.
"""

import ast
import dataclasses
import inspect
import re
import typing

import pytest

from lmi.commands.schedule import sdk, stream

from . import sdk_fake
from .test_stream import EQUIVALENT

try:                                    # the extra, or nothing
    import claude_agent_sdk as real_sdk
except Exception:                       # noqa: BLE001 - any failure means absent
    real_sdk = None

requires_sdk = pytest.mark.skipif(
    real_sdk is None,
    reason='the "sdk" extra is not installed: pip install -e ".[sdk]"',
)

pytestmark = requires_sdk


# --- what the fake actually emits ------------------------------------------

class _StderrStub:
    """`_messages` only touches the recorder to deliver stderr."""

    def emit_stderr(self, text):
        pass


KNOBS = {
    # Every optional branch of the fake's stream turned on at once, so this
    # module validates the shapes the suite can emit rather than the subset a
    # default run happens to reach. FAKE_SDK_UNKNOWN and FAKE_SDK_NO_RESULT are
    # deliberately left off: the first is a shape the real SDK is not supposed
    # to have, and the second removes the ResultMessage this module needs to see.
    "FAKE_SDK_TOOL_INPUT": "the whole new file",
    "FAKE_SDK_STDERR": "a diagnostic",
    "FAKE_SDK_RATE_LIMIT": "rejected",
    "FAKE_OUT": "done",
}


def _emitted(monkeypatch):
    """Every message the fake's stream can produce, plus the table's."""
    for key, value in KNOBS.items():
        monkeypatch.setenv(key, value)
    for key in ("FAKE_SDK_UNKNOWN", "FAKE_SDK_NO_RESULT", "FAKE_SDK_RAISE_AT",
                "FAKE_STREAM_QUOTA_TAIL", "FAKE_RC"):
        monkeypatch.delenv(key, raising=False)

    messages = list(sdk_fake._messages(1, _StderrStub()))
    # The table in test_stream.py is imported rather than duplicated: it carries
    # the UserMessage, ToolResultBlock and ThinkingBlock shapes the fake's own
    # stream never reaches, and importing it means a shape added there is
    # validated here without anybody remembering to.
    messages.extend(message for _, _, message in EQUIVALENT)
    return messages


def _objects(messages):
    """Each message and each of its content blocks, once per class."""
    seen = {}
    for message in messages:
        seen.setdefault(type(message).__name__, message)
        content = getattr(message, "content", None)
        if isinstance(content, list):
            for block in content:
                seen.setdefault(type(block).__name__, block)
    return seen


@pytest.fixture
def emitted(monkeypatch):
    return _objects(_emitted(monkeypatch))


def _fields(name):
    """The real class's field names, or None if there is no such class."""
    real = getattr(real_sdk, name, None)
    if real is None:
        return None
    if dataclasses.is_dataclass(real):
        return set(f.name for f in dataclasses.fields(real))
    # Not a dataclass: fall back to whatever it declares. A TypedDict or a
    # plain class is still answerable, and answering "no fields at all" would
    # make every assertion below pass vacuously.
    return set(getattr(real, "__annotations__", {}))


# --- the class names -------------------------------------------------------

def test_every_shape_the_fake_emits_is_a_real_sdk_class(emitted):
    """MANDATORY. The name IS the matching key, in both renderers.

    A typo in `sdk_fake` does not fail loudly on its own - it produces a fake
    whose messages all fall through to the "unrecognised shape" row, which is a
    green suite testing the degrade path and nothing else.
    """
    missing = sorted(name for name in emitted
                     if name != "_Unknown" and getattr(real_sdk, name, None) is None)
    assert missing == [], (
        "sdk_fake emits shapes the installed claude-agent-sdk does not export: "
        "%s. Fix the fake (and stream.py's matching names) - not this test."
        % missing
    )


def test_the_names_the_renderer_matches_on_are_real_classes():
    """The other end of the same rope.

    `MessageRenderer` and `_block_row` match on string literals, so a rename in
    the SDK turns every message of that type into one dull line while the
    iteration still exits 0. Nothing else in the suite can see that: the fake
    would have been renamed to match, or not renamed at all, and either way it
    stays green.

    The list is READ OUT OF stream.py rather than written down here. A
    hand-copied list is a second place to maintain, and it drifted the first
    time: it omitted "ToolResultMessage", which stream.py matched on for a
    while and the SDK has never exported - so the dispatch carried a branch that
    could not fire and this test, whose whole job is catching exactly that, was
    green. Do not replace the parse below with a literal list again.
    """
    matched = _names_stream_matches_on()
    assert matched, "found no class-name literals in stream.py - parse broken"
    missing = [name for name in matched if getattr(real_sdk, name, None) is None]
    assert missing == [], (
        "stream.py matches on message class names the installed SDK does not "
        "export: %s" % missing
    )


# Only a literal that is entirely a class name counts, so the prose in
# stream.py's docstrings - which names most of these types - cannot be mistaken
# for a dispatch key.
_CLASS_NAME = re.compile(r"^[A-Z][A-Za-z0-9]*(?:Message|Block|Event)$")


def _names_stream_matches_on():
    """Every SDK class name stream.py compares against, from its source."""
    tree = ast.parse(inspect.getsource(stream))
    return sorted({
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _CLASS_NAME.match(node.value)
    })


# --- the fields ------------------------------------------------------------

def test_every_attribute_the_fake_sets_is_a_real_field(emitted):
    """MANDATORY. The fake must not be able to invent a field.

    A test asserting on an attribute the real SDK never produces is green about
    something that cannot happen - and the direction that bites is the quiet
    one: production code reads it with a defaulted `getattr`, so on a real run
    it is simply always the default.
    """
    wrong = {}
    for name, obj in sorted(emitted.items()):
        if name == "_Unknown":
            continue
        real = _fields(name)
        if real is None:
            continue                     # the class itself is missing: above
        extra = sorted(set(vars(obj)) - real)
        if extra:
            wrong[name] = extra
    assert wrong == {}, (
        "sdk_fake sets fields the installed claude-agent-sdk does not declare: "
        "%s. Fix the fake, and check whether stream.py or sdk.py reads them - "
        "not this test." % wrong
    )


# What lmi reads off each shape, per class. Only the attributes a *decision*
# depends on: `subtype` decides the exit code, `content` and `input` decide what
# reaches the log. Attributes read purely to decorate a row - is_error,
# num_turns, duration_ms - are deliberately absent, because they are read with a
# default and their absence costs a word in one log line rather than a wrong
# result.
READ = {
    "SystemMessage": ["subtype", "data"],
    "AssistantMessage": ["content"],
    "UserMessage": ["content"],
    "ResultMessage": ["subtype", "result"],
    "TextBlock": ["text"],
    "ThinkingBlock": ["thinking"],
    "ToolUseBlock": ["name", "input"],
    "ToolResultBlock": ["content"],
}


@pytest.mark.parametrize("name", sorted(READ))
def test_every_attribute_lmi_reads_is_a_real_field(name):
    """MANDATORY. The rename check, from the side that actually costs money.

    Every one of these is read through `getattr(x, "...", None)`, which is what
    keeps a schema addition from abandoning an iteration - and is also why a
    rename is invisible: `subtype` renamed means `_rc_of` sees None, decides the
    call did not succeed, and every iteration is recorded as failed; `result`
    renamed means a non-verbose run logs nothing at all. Neither raises.
    """
    real = _fields(name)
    assert real is not None, "the SDK no longer exports %s" % name
    missing = [field for field in READ[name] if field not in real]
    assert missing == [], (
        "lmi reads %s off %s, and the installed claude-agent-sdk does not "
        "declare it. sdk.py and stream.py must be updated - a getattr default "
        "means this fails silently on a real run." % (missing, name)
    )


# --- the options object ----------------------------------------------------

def test_every_keyword_the_backend_passes_is_a_real_option():
    """MANDATORY. Not silent at all - and that is why it needs pinning here.

    `_options` calls the real `ClaudeAgentOptions(...)` with these keywords, so
    one the SDK has renamed is a TypeError on every iteration of every SDK-mode
    run. The fake accepts anything through **kw, so the whole suite passes while
    the backend cannot construct its options object even once.
    """
    real = _fields("ClaudeAgentOptions")
    assert real is not None, "the SDK no longer exports ClaudeAgentOptions"
    passed = ["allowed_tools", "add_dirs", "cwd", "permission_mode",
              "setting_sources", "stderr"]
    missing = [name for name in passed if name not in real]
    assert missing == [], (
        "sdk._options passes keywords the installed claude-agent-sdk does not "
        "accept: %s" % missing
    )


def test_can_use_tool_is_a_real_option_and_is_left_unset():
    """Invariant 3, from an angle no other test can reach.

    Other tests assert `can_use_tool is None` on the options object. That
    assertion is only worth anything if the real SDK has such an option in the
    first place - if it were renamed, the fake would keep reporting None for a
    field nobody sets and the guarantee would quietly become a tautology.
    """
    real = _fields("ClaudeAgentOptions")
    assert "can_use_tool" in real, (
        "the SDK's interactive-permission callback has been renamed; the tests "
        "asserting it stays unset are now asserting nothing"
    )
    # Matched as a keyword argument rather than as a bare word, so that the
    # comment in sdk.py saying never to set one does not fail this test.
    assert "can_use_tool=" not in inspect.getsource(sdk), \
        "sdk.py must never set can_use_tool - invariant 3"


def _literal_values(name):
    """The values of an SDK type alias like PermissionMode, or None.

    Looked up on the package and on its `types` module, and tolerant of both
    `Literal[...]` and anything else - a version that models these as an enum
    or a plain str is not a failure of lmi's.
    """
    for holder in (real_sdk, getattr(real_sdk, "types", None)):
        alias = getattr(holder, name, None) if holder is not None else None
        if alias is None:
            continue
        args = typing.get_args(alias)
        if args:
            return set(a for a in args if isinstance(a, str))
    return None


def test_the_permission_mode_is_one_the_sdk_recognises():
    """MANDATORY. A misspelled permission mode is the one failure here that
    **hangs** rather than fails.

    Invariant 3: nothing in the unattended runner may wait for a keypress, and
    the SDK's default mode asks. If "acceptEdits" is not a mode the installed
    SDK knows, the run either falls back to that default - and blocks for ever
    on a decision nobody is there to make - or refuses to start. The fake cannot
    tell: it stores the string and hands it straight back to the assertion.
    """
    values = _literal_values("PermissionMode")
    if values is None:
        pytest.skip("this SDK does not model PermissionMode as a Literal")
    assert sdk.PERMISSION_MODE in values, (
        "sdk.PERMISSION_MODE is %r, and the installed SDK's modes are %s"
        % (sdk.PERMISSION_MODE, sorted(values))
    )
    # And it is not the interactive default, whatever that is called.
    assert sdk.PERMISSION_MODE != "default"


def test_every_setting_source_is_one_the_sdk_recognises():
    """MANDATORY. Item 40, checked against the real vocabulary.

    The user source is what makes ~/.claude/settings.json - the file
    `lmi config switch` exists to change - reach SDK mode at all. A value the
    SDK does not recognise is either ignored or refused, and the ignored case is
    silent: the run goes to the wrong endpoint with no credentials.
    """
    values = _literal_values("SettingSource")
    if values is None:
        pytest.skip("this SDK does not model SettingSource as a Literal")
    unknown = sorted(set(sdk.SETTING_SOURCES) - values)
    assert unknown == [], (
        "sdk.SETTING_SOURCES names sources the installed SDK does not know: %s "
        "(it knows %s)" % (unknown, sorted(values))
    )
    assert "user" in values and "user" in sdk.SETTING_SOURCES


# --- the entry point -------------------------------------------------------

def test_query_takes_the_two_keywords_the_backend_passes():
    """`_drive` calls `module.query(prompt=..., options=...)`.

    A positional-only or renamed parameter is a TypeError on the first
    iteration, and the fake's own `query` is written to lmi's expectation rather
    than to the SDK's - which is exactly the shape of mistake this module
    exists to catch.
    """
    real = getattr(real_sdk, "query", None)
    assert real is not None, "the SDK no longer exports query()"
    params = inspect.signature(real).parameters
    for name in ("prompt", "options"):
        assert name in params, "query() has no %s parameter" % name
        assert params[name].kind is not inspect.Parameter.POSITIONAL_ONLY


def test_the_fake_module_exports_everything_the_backend_reaches_for():
    """The fake stands in for the real package, so it must export the same
    names lmi looks up on it - `ClaudeAgentOptions` and `query`. Everything
    else it exports is for the tests' convenience."""
    module = sdk_fake.build_module(_StderrStub())
    for name in ("ClaudeAgentOptions", "query"):
        assert hasattr(module, name)
        assert hasattr(real_sdk, name)


def test_the_real_options_accept_the_session_fields():
    """MANDATORY - the fake is only evidence if the real dataclass agrees.

    `sdk._options` passes `session_id=` on a fresh session and `resume=` on a
    resumed one. Passing a keyword a dataclass does not define is a TypeError on
    EVERY iteration of the run - item 44's failure with a new field name - and
    the suite's fake would happily accept both whatever the real package does.

    Verified by hand against 0.2.136, the floor named in pyproject.toml and
    install/sdk.REQUIREMENT: both fields exist there, which is why that floor did
    not have to move for session continuity. This is the assertion that keeps
    that true.
    """
    names = {f.name for f in dataclasses.fields(real_sdk.ClaudeAgentOptions)}
    assert {"session_id", "resume"} <= names


def test_the_real_result_message_carries_a_session_id():
    """What sdk._session_id_of reads, and the SDK-only id-mismatch check with
    it. A ResultMessage without one makes that warning permanently silent -
    which looks exactly like a run where nothing was substituted."""
    names = {f.name for f in dataclasses.fields(real_sdk.ResultMessage)}
    assert "session_id" in names


def test_the_renderer_reads_the_real_classes_as_readily_as_the_fakes():
    """One real-typed message through the real front end.

    Everything above compares names and fields; this constructs the genuine
    dataclasses and renders them, which is the only assertion here that would
    catch a shape change the field names survive - a `content` that is now a
    string, say, or blocks that are dicts rather than objects.
    """
    log = _Log()
    renderer = stream.MessageRenderer(log)
    message = real_sdk.AssistantMessage(
        content=[real_sdk.TextBlock(text="I'll start with fs.py.")],
        model="claude-opus-5",
    )
    out = renderer.render(message)
    assert "I'll start with fs.py." in out
    assert not [line for line in log.lines if line.startswith("[WARN]")], \
        "a real AssistantMessage fell through to the degrade path"


class _Log:
    def __init__(self):
        self.lines = []

    def line(self, msg=""):
        self.lines.append(msg)

    def warn(self, msg):
        self.lines.append("[WARN] " + msg)
