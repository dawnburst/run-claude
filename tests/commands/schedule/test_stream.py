"""The two front ends: one claude event in, one log line out - the same line.

`Renderer` reads claude's stream-json lines; `MessageRenderer` reads the SDK's
typed messages. They are two front ends onto one set of row functions, and the
table at the bottom of this module is where that claim is actually tested: the
same logical event fed to both must come out byte-identical, or a CLI log and an
SDK log stop lining up and no review of the difference between them means
anything.
"""

import json

import pytest

from lmi.commands.schedule import stream
from lmi.commands.schedule.stream import MessageRenderer, Renderer

from . import sdk_fake


class FakeLog:
    def __init__(self):
        self.lines = []

    def line(self, msg=""):
        self.lines.append(msg)

    def warn(self, msg):
        self.lines.append("[WARN] " + msg)


def _render(event):
    """Render one event dict through a fresh Renderer."""
    return Renderer(FakeLog()).render(json.dumps(event))


def test_init_names_the_model_and_the_directory():
    out = _render({"type": "system", "subtype": "init",
                   "model": "claude-opus-5", "cwd": "/repo/lmi",
                   "session_id": "a3f2b1c8"})
    assert "claude-opus-5" in out and "/repo/lmi" in out


def test_assistant_text_is_rendered_as_text():
    out = _render({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "I'll start with fs.py."}]}})
    assert "I'll start with fs.py." in out
    assert out.startswith("[claude]")


def test_a_tool_call_names_the_tool_and_its_target():
    out = _render({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Edit",
         "input": {"file_path": "lmi/core/log.py", "old_string": "a"}}]}})
    assert "Edit" in out and "lmi/core/log.py" in out


def test_a_bash_call_shows_the_command():
    out = _render({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash",
         "input": {"command": "python3 -m pytest tests/ -q"}}]}})
    assert "Bash" in out and "python3 -m pytest tests/ -q" in out


def test_a_write_never_puts_the_file_content_in_the_log():
    """MANDATORY. Write's input carries the whole new file. Rendering it would
    put a 400-line file into the log every time claude saves the state file,
    which defeats the readability this feature exists for - and buries the
    tool calls either side of it."""
    content = "\n".join("line %d" % n for n in range(400))
    out = _render({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Write",
         "input": {"file_path": "state.md", "content": content}}]}})
    assert out.count("\n") == 0
    assert "line 399" not in out
    assert "Write" in out and "state.md" in out


def test_a_long_tool_argument_is_truncated():
    out = _render({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash",
         "input": {"command": "x" * 500}}]}})
    assert len(out) < 300


def test_a_tool_result_is_rendered():
    out = _render({"type": "user", "message": {"content": [
        {"type": "tool_result", "content": "420 passed, 1 skipped"}]}})
    assert "420 passed, 1 skipped" in out


def test_a_tool_result_is_not_clipped_to_the_argument_budget():
    """MANDATORY. A tool result is what an operator reads a -v log FOR, and it
    used to inherit ARG_WIDTH - the budget for a file path - because
    _result_row called _clip with no width of its own. Every grep's hits and
    every file's head were cut off mid-word at 160 characters.

    Not silent, but it makes the feature useless in the direction that looks
    fine: the log still shows a row per event, so it reads as complete, while
    saying that claude ran something and never what it got back."""
    body = " ".join("%d: a line of real output" % n for n in range(1, 80))
    out = _render({"type": "user", "message": {"content": [
        {"type": "tool_result", "content": body}]}})
    assert "40: a line of real output" in out
    assert len(out) > 1000


def test_a_huge_tool_result_is_still_bounded_to_one_line():
    """The other half of the same rule. A Read returns whole files, so an
    unbounded result row would put every file claude opens into the log - item
    29's harm arriving through the tool's output instead of its input."""
    out = _render({"type": "user", "message": {"content": [
        {"type": "tool_result", "content": "y" * 500000}]}})
    assert len(out) < 3000
    assert out.count("\n") == 0


def test_assistant_prose_is_not_clipped_to_the_argument_budget():
    """Same root cause, same fix: what claude said is content, not an argument.
    Left at ARG_WIDTH it is cut off mid-sentence exactly like a tool result."""
    body = " ".join("sentence %d of the explanation." % n for n in range(1, 60))
    out = _render({"type": "assistant", "message": {"content": [
        {"type": "text", "text": body}]}})
    assert "sentence 30 of the explanation." in out


def test_thinking_is_not_clipped_to_the_argument_budget():
    body = " ".join("thought %d about the state file." % n for n in range(1, 60))
    out = _render({"type": "assistant", "message": {"content": [
        {"type": "thinking", "thinking": body}]}})
    assert "thought 30 about the state file." in out


def test_the_content_budget_is_wider_than_the_argument_budget():
    """The two must not be collapsed back into one constant. ARG_WIDTH sizes an
    identifier - a path, a command, a URL - and TEXT_WIDTH sizes something
    somebody has to read. A single width can only be wrong for one of them."""
    assert stream.TEXT_WIDTH > stream.ARG_WIDTH


def test_the_result_event_reports_how_the_iteration_went():
    out = _render({"type": "result", "subtype": "success", "is_error": False,
                   "num_turns": 11, "duration_ms": 108400})
    assert "11" in out and "108" in out


def test_an_unknown_event_type_renders_one_uninformative_line():
    """A schema addition must degrade to one line, never to a traceback that
    _iteration_rc would turn into a skipped iteration."""
    out = _render({"type": "telepathy", "payload": {"deep": ["nested"]}})
    assert out.count("\n") == 0
    assert "telepathy" in out


def test_an_event_missing_the_fields_we_expect_does_not_raise():
    for event in ({"type": "assistant"},
                  {"type": "assistant", "message": {}},
                  {"type": "assistant", "message": {"content": [{}]}},
                  {"type": "result"},
                  {}):
        assert isinstance(_render(event), str)


def test_a_non_json_line_warns_once_and_passes_through_verbatim():
    """MANDATORY. If claude stops emitting stream-json - a future version, or a
    flag combination config did not catch - the renderer must say so and show
    the raw output. Silent: the activity block goes quiet while the iteration
    still reports exit 0."""
    log = FakeLog()
    renderer = Renderer(log)
    assert renderer.render("not json at all") == "not json at all"
    assert renderer.render("still not json") == "still not json"
    warnings = [line for line in log.lines if line.startswith("[WARN]")]
    assert len(warnings) == 1
    assert "stream-json" in warnings[0]


def test_a_json_line_that_is_not_an_object_is_treated_as_raw():
    """json.loads("42") succeeds and returns an int, which has no .get."""
    log = FakeLog()
    assert Renderer(log).render("42") == "42"
    assert any(line.startswith("[WARN]") for line in log.lines)


def test_a_blank_line_is_passed_through_without_warning():
    """claude's stream ends with a newline; a blank line is not a format
    failure and must not spend the one warning."""
    log = FakeLog()
    assert Renderer(log).render("") == ""
    assert log.lines == []


# --- the SDK front end -----------------------------------------------------
#
# Task 41. The shapes come from sdk_fake rather than being defined again here:
# they are the same objects every SDK-mode test renders, and a second set of
# stand-ins would let the two drift apart - at which point this module would be
# green about a shape no test actually feeds through the backend.

def _render_message(message):
    """Render one SDK message through a fresh MessageRenderer."""
    return MessageRenderer(FakeLog()).render(message)


def test_the_sdk_front_end_renders_a_tool_call():
    out = _render_message(sdk_fake.AssistantMessage(content=[
        sdk_fake.ToolUseBlock(name="Edit",
                              input={"file_path": "lmi/core/log.py",
                                     "old_string": "a"})]))
    assert "Edit" in out and "lmi/core/log.py" in out
    assert out.startswith("[claude]")


def test_the_sdk_front_end_renders_thinking():
    """The JSON front end gained thinking rows so that this one could have them.

    Task 41 requires the two to emit identical rows for equivalent events, and
    the SDK delivers ThinkingBlock as a first-class block - so dropping it in
    either front end is a row that exists in one log and not the other.
    """
    out = _render_message(sdk_fake.AssistantMessage(content=[
        sdk_fake.ThinkingBlock(thinking="the state file is under .claude/")]))
    assert "the state file is under .claude/" in out


def test_a_user_message_carrying_plain_text_is_rendered_as_text():
    """A UserMessage's content is a list of blocks or a bare string."""
    out = _render_message(sdk_fake.UserMessage(content="carry on"))
    assert "carry on" in out


def test_an_sdk_message_missing_the_fields_we_expect_does_not_raise():
    """Same rule as the JSON side: one dull line, never an exception.

    An exception out of the renderer reaches _iteration_rc, which records the
    whole iteration as skipped - so a field renamed in a later SDK would
    abandon the run rather than cost a log line.
    """
    for message in (sdk_fake.AssistantMessage(),
                    sdk_fake.AssistantMessage(content=None),
                    sdk_fake.AssistantMessage(content=[object()]),
                    sdk_fake.UserMessage(content=[]),
                    sdk_fake.SystemMessage(),
                    sdk_fake.ResultMessage()):
        assert isinstance(_render_message(message), str)


def test_a_message_whose_rendering_raises_costs_one_line_not_the_iteration():
    """Belt and braces over the defensive getattr()s. Same reason as above."""

    class ResultMessage(object):                 # the name IS the matching key
        @property
        def subtype(self):
            raise RuntimeError("a field that explodes when read")

        def __repr__(self):
            return "<exploding ResultMessage>"

    out = _render_message(ResultMessage())
    assert out.count("\n") == 0
    assert "ResultMessage" in out


def test_an_unknown_sdk_message_warns_once_and_describes_the_rest_plainly():
    """MANDATORY. The SDK analogue of _give_up, and the other half of "degrade
    out loud".

    A message type a later SDK grows must not make the activity block go quiet
    while the iteration still reports exit 0 - that is the failure item 26
    exists to prevent, reached from the other backend. One [WARN], one line per
    message, and nothing raised.
    """
    log = FakeLog()
    renderer = MessageRenderer(log)

    first = renderer.render(sdk_fake._Unknown(surprise="a new message type"))
    second = renderer.render(sdk_fake._Unknown(surprise="and another"))

    warnings = [line for line in log.lines if line.startswith("[WARN]")]
    assert len(warnings) == 1
    assert "Claude Agent SDK" in warnings[0]
    for out in (first, second):
        assert out.count("\n") == 0
        assert "_Unknown" in out


def test_an_unknown_sdk_message_is_described_by_field_name_never_by_value():
    """An unknown message could carry a tool input, and ARG_KEYS exists exactly
    so that a file's contents never reach the log. The degrade path must not be
    the way round it."""
    out = _render_message(sdk_fake._Unknown(
        input={"file_path": "state.md", "content": "SECRET " * 200}))
    assert "SECRET" not in out
    assert "input" in out                        # the field name is fine


# --- task 42: content is not in ARG_KEYS, in either front end ---------------

def test_a_write_never_puts_the_file_content_in_the_log_in_either_mode():
    """MANDATORY. Item 29, now with two ways to break it.

    `ToolUseBlock.input` makes `content` easier to reach than a JSON dict did,
    which makes the rule easier to break in the newer front end only - and a
    Write's content is the whole new file, so rendering it puts the state file
    into the log on every single save and buries the tool calls either side of
    it. ARG_KEYS is an allowlist; both front ends read it through _tool_arg.
    """
    content = "\n".join("line %d" % n for n in range(400))
    json_out = _render({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Write",
         "input": {"file_path": "state.md", "content": content}}]}})
    sdk_out = _render_message(sdk_fake.AssistantMessage(content=[
        sdk_fake.ToolUseBlock(name="Write",
                              input={"file_path": "state.md",
                                     "content": content})]))

    for out in (json_out, sdk_out):
        assert out.count("\n") == 0
        assert "line 399" not in out
        assert "Write" in out and "state.md" in out
    assert json_out == sdk_out


# --- task 41: the same event, the same row, from either front end -----------
#
# The whole claim of the two-front-ends design, in one table. Each row is one
# logical event in both of its wire shapes; the assertion is byte equality, not
# "both mention the model name", because the point is that the two logs line up
# well enough to diff - which is what task 55 does with two real runs.

EQUIVALENT = [
    (
        "init",
        {"type": "system", "subtype": "init", "model": "claude-opus-5",
         "session_id": "a3f2b1c8", "cwd": "/repo/lmi"},
        sdk_fake.SystemMessage(subtype="init",
                               data={"model": "claude-opus-5",
                                     "session_id": "a3f2b1c8",
                                     "cwd": "/repo/lmi"}),
    ),
    (
        "a system event that is not init",
        {"type": "system", "subtype": "compact_boundary"},
        sdk_fake.SystemMessage(subtype="compact_boundary", data={}),
    ),
    (
        "assistant text",
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "I'll start with fs.py."}]}},
        sdk_fake.AssistantMessage(content=[
            sdk_fake.TextBlock(text="I'll start with fs.py.")]),
    ),
    (
        "assistant thinking",
        {"type": "assistant", "message": {"content": [
            {"type": "thinking", "thinking": "the floor is 3.9"}]}},
        sdk_fake.AssistantMessage(content=[
            sdk_fake.ThinkingBlock(thinking="the floor is 3.9")]),
    ),
    (
        "a tool call",
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit",
             "input": {"file_path": "lmi/core/log.py"}}]}},
        sdk_fake.AssistantMessage(content=[
            sdk_fake.ToolUseBlock(name="Edit",
                                  input={"file_path": "lmi/core/log.py"})]),
    ),
    (
        "a bash call",
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash",
             "input": {"command": "python3 -m pytest tests/ -q"}}]}},
        sdk_fake.AssistantMessage(content=[
            sdk_fake.ToolUseBlock(
                name="Bash",
                input={"command": "python3 -m pytest tests/ -q"})]),
    ),
    (
        "several blocks in one message",
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Now the log."},
            {"type": "tool_use", "name": "Write",
             "input": {"file_path": "state.md"}}]}},
        sdk_fake.AssistantMessage(content=[
            sdk_fake.TextBlock(text="Now the log."),
            sdk_fake.ToolUseBlock(name="Write",
                                  input={"file_path": "state.md"})]),
    ),
    (
        "an assistant message with nothing worth a row",
        {"type": "assistant", "message": {"content": []}},
        sdk_fake.AssistantMessage(content=[]),
    ),
    (
        "a tool result",
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": "420 passed, 1 skipped",
             "is_error": False}]}},
        sdk_fake.UserMessage(content=[
            sdk_fake.ToolResultBlock(content="420 passed, 1 skipped",
                                     is_error=False)]),
    ),
    (
        "a failed tool result",
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": "No such file",
             "is_error": True}]}},
        sdk_fake.UserMessage(content=[
            sdk_fake.ToolResultBlock(content="No such file", is_error=True)]),
    ),
    (
        "a tool result whose content is a list of blocks",
        {"type": "user", "message": {"content": [
            {"type": "tool_result",
             "content": [{"text": "first"}, {"text": "second"}],
             "is_error": False}]}},
        sdk_fake.UserMessage(content=[
            sdk_fake.ToolResultBlock(
                content=[{"text": "first"}, {"text": "second"}],
                is_error=False)]),
    ),
    (
        "the result",
        {"type": "result", "subtype": "success", "is_error": False,
         "num_turns": 11, "duration_ms": 108400, "result": "done"},
        sdk_fake.ResultMessage(subtype="success", is_error=False, num_turns=11,
                               duration_ms=108400, result="done"),
    ),
    (
        "a failed result",
        {"type": "result", "subtype": "error_during_execution",
         "is_error": True, "num_turns": 3, "duration_ms": 900,
         "result": "Claude AI usage limit reached"},
        sdk_fake.ResultMessage(subtype="error_during_execution", is_error=True,
                               num_turns=3, duration_ms=900,
                               result="Claude AI usage limit reached"),
    ),
]


@pytest.mark.parametrize("label,event,message",
                         EQUIVALENT, ids=[row[0] for row in EQUIVALENT])
def test_both_front_ends_emit_the_same_row(label, event, message):
    """MANDATORY. The two backends' logs must be comparable.

    Not a style preference: both backends exit 0 on success and neither marks
    the state file, so the log is the only place a run's behaviour is visible.
    If an equivalent event renders differently in the two modes, the two logs
    cannot be diffed and the reviewer has no way to tell a backend difference
    from a formatting difference. One row function, two callers - that is the
    mechanism, and this is the test of it.
    """
    assert _render(event) == _render_message(message)


def test_neither_front_end_warns_for_anything_in_that_table():
    """A row rendered through the degrade path would satisfy the equality above
    while telling the operator nothing. One [WARN] anywhere here means a shape
    the table claims is understood is not."""
    for _, event, message in EQUIVALENT:
        json_log, sdk_log = FakeLog(), FakeLog()
        Renderer(json_log).render(json.dumps(event))
        MessageRenderer(sdk_log).render(message)
        assert not [l for l in json_log.lines if l.startswith("[WARN]")]
        assert not [l for l in sdk_log.lines if l.startswith("[WARN]")]
