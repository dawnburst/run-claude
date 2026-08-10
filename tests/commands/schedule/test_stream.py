"""The stream-json renderer: one claude event in, one log line out."""

import json

from lmi.commands.schedule.stream import Renderer


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
