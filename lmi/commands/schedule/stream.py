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
        bits = []
        for label, key in (("model", "model"), ("session", "session_id"),
                           ("cwd", "cwd")):
            if event.get(key):
                bits.append("%s=%s" % (label, _clip(event[key], 80)))
        return _row("init", " ".join(bits))

    @staticmethod
    def _assistant(event):
        rows = []
        for block in _blocks(event):
            if block.get("type") == "text" and block.get("text", "").strip():
                rows.append(_row("text", _clip(block["text"])))
            elif block.get("type") == "tool_use":
                name = _clip(block.get("name", "?"), 20)
                rows.append(_row("tool", ("%-6s %s" % (
                    name, _tool_arg(block.get("input")))).rstrip()))
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
            marker = "error" if block.get("is_error") else "result"
            rows.append(_row(marker, _clip(content if content else "")))
        return "\n".join(rows) if rows else _row("user", "")

    @staticmethod
    def _result(event):
        bits = ["error" if event.get("is_error") else
                _clip(event.get("subtype", "ok"), 20)]
        if event.get("num_turns") is not None:
            bits.append("%s turns" % event["num_turns"])
        if event.get("duration_ms") is not None:
            try:
                bits.append("%.1fs" % (float(event["duration_ms"]) / 1000.0))
            except (TypeError, ValueError):
                pass
        # The result event is where a usage limit is reported, so its message
        # must survive into the line - runner scans the RAW line for quota
        # wording, but a reader needs to see it too.
        if event.get("result"):
            bits.append(_clip(event["result"], 200))
        return _row("done", " - ".join(bits))
