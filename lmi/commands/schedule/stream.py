"""Turning claude's stream-json events into readable log lines.

This module encodes claude's output schema, which is this command's concern
and nobody else's, so it stays inside commands/schedule/ rather than moving to
core/. Promote it if a second command ever needs it, not before.

Two rules hold the whole file together, and both exist because the failure
they prevent is silent - the log goes quiet while the iteration still reports
exit 0:

  * an event shape this module does not recognise degrades to one line, never
    to an exception. An exception here reaches _iteration_rc, which records the
    iteration as skipped - a schema addition would abandon the run.
  * a line that is not a JSON object means claude is not speaking stream-json
    at all. That is said once, out loud, and everything is then passed through
    verbatim, so the output is still visible even when this module is useless.
"""

import json

TAG = "[claude]"

# How much of a tool argument survives into the log. Long enough for a real
# path or a pytest command, short enough that one event stays one readable
# line.
ARG_WIDTH = 160

# The tool input field worth showing, most specific first. `content` is
# deliberately absent and must stay absent: it carries the whole new file on a
# Write, which would put the state file into the log on every save.
ARG_KEYS = ("file_path", "command", "pattern", "path", "url", "prompt")


def _clip(value, width=ARG_WIDTH):
    """One line, no longer than `width`. Never None, never multi-line."""
    text = " ".join(str(value).split())
    return text if len(text) <= width else text[: width - 3] + "..."


def _tool_arg(inp):
    """The most identifying argument of a tool call, or ""."""
    if not isinstance(inp, dict):
        return ""
    for key in ARG_KEYS:
        if key in inp:
            return _clip(inp[key])
    return ""


def _blocks(event):
    """The content blocks of an assistant or user event, defensively."""
    message = event.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _row(kind, body):
    return "%s %-7s %s" % (TAG, kind, body)


# --- the rows themselves --------------------------------------------------
#
# Every row either front end can emit is built by one of these, and neither
# front end formats a row of its own. That is what makes the CLI and SDK logs
# comparable: not a convention that they should match, but one function per row
# with two callers. A row that exists in only one of them is a difference
# nobody can review, because the two logs stop lining up from there on.

def _text_row(text):
    return _row("text", _clip(text))


def _thinking_row(text):
    return _row("think", _clip(text))


def _tool_row(name, inp):
    return _row("tool", ("%-6s %s" % (_clip(name or "?", 20),
                                      _tool_arg(inp))).rstrip())


def _result_row(content, is_error):
    return _row("error" if is_error else "result", _clip(content or ""))


def _init_row(model, session, cwd):
    bits = []
    for label, value in (("model", model), ("session", session), ("cwd", cwd)):
        if value:
            bits.append("%s=%s" % (label, _clip(value, 80)))
    return _row("init", " ".join(bits))


def _done_row(subtype, is_error, num_turns, duration_ms, result):
    """`subtype` arrives already defaulted, so an explicit empty one stays empty.

    Each front end applies its own default - "ok" for a missing key, "ok" for a
    missing attribute - because "the key is absent" and "the key is there and
    empty" are different facts and only the caller can tell them apart.
    """
    bits = ["error" if is_error else _clip(subtype, 20)]
    if num_turns is not None:
        bits.append("%s turns" % num_turns)
    if duration_ms is not None:
        try:
            bits.append("%.1fs" % (float(duration_ms) / 1000.0))
        except (TypeError, ValueError):
            pass
    # The result event is where a usage limit is reported, so its message must
    # survive into the line - the runner scans for quota wording before this
    # module ever sees it, but a reader needs to see the wording too.
    if result:
        bits.append(_clip(result, 200))
    return _row("done", " - ".join(bits))


class Renderer:
    """One per iteration: it remembers whether it has given up already."""

    def __init__(self, log):
        self.log = log
        self.warned = False

    def render(self, raw_line):
        """One raw stdout line in, one line to log out."""
        if not raw_line.strip():
            # The stream ends with a newline. A blank line is not a format
            # failure and must not spend the one warning.
            return raw_line
        if self.warned:
            return raw_line
        try:
            event = json.loads(raw_line)
        except ValueError:
            return self._give_up(raw_line)
        if not isinstance(event, dict):
            # json.loads("42") succeeds and returns an int, which has no .get.
            return self._give_up(raw_line)
        try:
            return self._event(event)
        except Exception:
            # Belt and braces over the defensive .get()s below. A rendering
            # failure must cost one dull line, never the iteration.
            return _row("event", _clip(raw_line))

    def _give_up(self, raw_line):
        if not self.warned:
            self.warned = True
            self.log.warn(
                "claude is not emitting stream-json - logging its output "
                "verbatim from here on"
            )
        return raw_line

    def _event(self, event):
        kind = event.get("type")
        if kind == "system":
            return self._system(event)
        if kind == "assistant":
            return self._assistant(event)
        if kind == "user":
            return self._user(event)
        if kind == "result":
            return self._result(event)
        return _row("event", _clip(kind if kind else json.dumps(event)))

    @staticmethod
    def _system(event):
        if event.get("subtype") != "init":
            return _row("system", _clip(event.get("subtype", "")))
        return _init_row(event.get("model"), event.get("session_id"),
                         event.get("cwd"))

    @staticmethod
    def _assistant(event):
        rows = []
        for block in _blocks(event):
            if block.get("type") == "text" and block.get("text", "").strip():
                rows.append(_text_row(block["text"]))
            elif block.get("type") == "thinking" and \
                    str(block.get("thinking", "")).strip():
                rows.append(_thinking_row(block["thinking"]))
            elif block.get("type") == "tool_use":
                rows.append(_tool_row(block.get("name"), block.get("input")))
        # One event can carry several blocks - a sentence and the tool call it
        # introduces arrive together. They are joined into one returned string
        # rather than emitted separately, so that render() stays a function of
        # one line and _pump never has to know an event can fan out. Logger
        # writes the embedded newlines through unchanged.
        return "\n".join(rows) if rows else _row("assistant", "")

    @staticmethod
    def _user(event):
        rows = []
        for block in _blocks(event):
            if block.get("type") != "tool_result":
                continue
            content = block.get("content")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            rows.append(_result_row(content, block.get("is_error")))
        return "\n".join(rows) if rows else _row("user", "")

    @staticmethod
    def _result(event):
        return _done_row(
            event.get("subtype", "ok"), event.get("is_error"),
            event.get("num_turns"), event.get("duration_ms"),
            event.get("result"),
        )


class MessageRenderer:
    """The SDK front end: typed messages in, the same rows out.

    A second front end onto the rows above, not a second renderer. Everything
    it emits comes from the same `_*_row` functions the JSON front end uses, so
    an equivalent event renders byte-identically in both modes - which is the
    only thing that makes a CLI log and an SDK log comparable, and a review of
    the difference between them meaningful.

    Messages are matched by CLASS NAME and duck-typed attributes rather than by
    isinstance. That is deliberate and is what keeps `claude_agent_sdk` imported
    in exactly one module: this one stays importable, and testable, with no
    extra installed. It also means an SDK that renames a field degrades to a
    dull line here instead of raising.

    Both of Renderer's founding rules carry over unchanged, for the same
    reasons:

      * an unrecognised shape costs one line, never an exception. An exception
        here reaches _iteration_rc, which records the whole iteration as
        skipped - so a message type added in a later SDK would abandon the run.
      * a shape this module cannot read at all is said once, out loud, and
        everything after it is described as plainly as possible. "Degrade out
        loud" is half of why the -v feature is trustworthy at all.
    """

    def __init__(self, log):
        self.log = log
        self.warned = False

    def render(self, message):
        """One SDK message in, one (possibly multi-line) string out."""
        try:
            rendered = self._message(message)
        except Exception:
            # Belt and braces over the defensive getattr()s below.
            return _row("event", _clip(repr(message)))
        if rendered is None:
            return self._give_up(message)
        return rendered

    def _give_up(self, message):
        if not self.warned:
            self.warned = True
            self.log.warn(
                "the Claude Agent SDK is emitting message types this lmi does "
                "not know - describing them plainly from here on"
            )
        return _row("event", _clip("%s %s" % (type(message).__name__,
                                              _fields(message))))

    def _message(self, message):
        """The rendered row(s), or None when the shape is unrecognised."""
        name = type(message).__name__
        if name == "AssistantMessage":
            return self._content(message, _row("assistant", ""))
        if name == "UserMessage":
            return self._content(message, _row("user", ""))
        if name == "SystemMessage":
            return self._system(message)
        if name == "RateLimitEvent":
            # Recognised rather than left to _give_up for two reasons, neither
            # cosmetic. It would otherwise spend the one warning an iteration
            # gets - and spend it on a message type lmi does know about, so a
            # genuinely unknown type arriving later would then pass silently.
            # And the warning's own wording ("message types this lmi does not
            # know") would be the log's only comment on a rate limit, which is
            # the last event an unattended run should describe vaguely.
            #
            # SDK-only, so deliberately not one of the shared row primitives
            # below: the CLI backend has no equivalent event to keep it
            # byte-identical with, and inventing one would put a row in the
            # EQUIVALENT table that only half the backends can ever emit.
            return _row("limit", _clip(getattr(message, "rate_limit_info", "")))
        if name == "HookEventMessage":
            # Recognised for the same reason as RateLimitEvent, and proven by
            # the same real run: a machine with hooks configured emits several
            # of these per iteration, so leaving them to _give_up spent the one
            # warning on every run on such a machine - and a genuinely unknown
            # type arriving afterwards was then never announced at all.
            return _row("hook", _clip("%s %s" % (
                getattr(message, "hook_event_name", "") or "",
                getattr(message, "subtype", "") or "",
            )).strip())
        if name == "ResultMessage":
            return _done_row(
                getattr(message, "subtype", None) or "ok",
                getattr(message, "is_error", None),
                getattr(message, "num_turns", None),
                getattr(message, "duration_ms", None),
                getattr(message, "result", None),
            )
        return None

    @staticmethod
    def _system(message):
        data = getattr(message, "data", None)
        if not isinstance(data, dict):
            data = {}
        if getattr(message, "subtype", None) != "init":
            return _row("system", _clip(getattr(message, "subtype", "") or ""))
        return _init_row(data.get("model"), data.get("session_id"),
                         data.get("cwd"))

    @staticmethod
    def _content(message, empty):
        """Every block of one message, one row each, joined like the JSON side."""
        content = getattr(message, "content", None)
        if isinstance(content, str):
            # A UserMessage can carry plain text rather than blocks.
            return _text_row(content) if content.strip() else empty
        rows = []
        for block in content if isinstance(content, list) else []:
            row = _block_row(block)
            if row is not None:
                rows.append(row)
        return "\n".join(rows) if rows else empty


def _block_row(block):
    """One content block as a row, or None if it says nothing worth a line."""
    name = type(block).__name__
    if name == "TextBlock":
        text = getattr(block, "text", "") or ""
        return _text_row(text) if text.strip() else None
    if name == "ThinkingBlock":
        text = getattr(block, "thinking", "") or ""
        return _thinking_row(text) if text.strip() else None
    if name == "ToolUseBlock":
        # getattr(..., "input") is a dict, and _tool_arg is an ALLOWLIST over
        # it - see ARG_KEYS. The typed block makes `content` easier to reach
        # than it was through a JSON dict, which makes the rule easier to break:
        # a Write's `content` is the whole new file, so rendering it puts the
        # state file into the log on every single save.
        return _tool_row(getattr(block, "name", None),
                         getattr(block, "input", None))
    if name == "ToolResultBlock":
        content = getattr(block, "content", None)
        if isinstance(content, list):
            content = " ".join(
                str(b.get("text", "")) for b in content if isinstance(b, dict)
            )
        return _result_row(content, getattr(block, "is_error", None))
    return None


def _fields(message):
    """A dull, bounded description of an object this module cannot read.

    Never the whole object: an unknown message could carry a tool input, and
    ARG_KEYS exists precisely so that a file's contents never reach the log.
    """
    keys = sorted(k for k in vars(message)) if hasattr(message, "__dict__") else []
    return "fields=%s" % ",".join(keys) if keys else ""
