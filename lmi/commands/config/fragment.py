"""Finding, reading and validating the settings.json fragment.

A fragment is a raw settings.json fragment - what you write is what lands.
Validation goes exactly as far as lmi can honestly judge and no further: the
file must be a JSON object, and an `env` block must map strings to strings.
Every other key passes through unexamined, because whether "mdel" is a typo for
"model" is Claude Code's schema's business and it reports that better than a
duplicated validator would. It is also what keeps this command working when
Anthropic adds a setting.
"""

import json
from pathlib import Path

from ...core import fs
from ...core.errors import EXIT_USAGE, LmiError
from ...core.text import decode_with_bom

DEFAULT_NAME = "config/settings_switch.json"
ENV_KEY = "env"

# A fragment with no "env" key and a fragment with "env": null are different
# documents, and doc.get(ENV_KEY) collapses them into the same None. See
# _validate.
_MISSING = object()

EXAMPLE = """{
  "model": "opus",
  "env": {
    "ANTHROPIC_BASE_URL": "https://gateway.example.com/"
  }
}"""


def load(explicit):
    """(the fragment, the path it came from). Raises LmiError on anything wrong."""
    path = _find(explicit)
    doc = _parse(path)
    _validate(doc, path)
    return doc, path


def _find(explicit):
    if explicit is not None:
        path = _expand(explicit)
        # An explicit --file that does not exist must NOT fall back to the
        # default. A named file that quietly resolves to a different one is how
        # a machine ends up in a configuration nobody chose.
        if _kind(path) != fs.FILE:
            raise LmiError(
                "the file given with --file does not exist: %s" % path, EXIT_USAGE
            )
        return path

    default = Path.cwd() / DEFAULT_NAME
    if _kind(default) == fs.FILE:
        return default
    raise LmiError(
        "no switch file found. Looked for:\n"
        "      %s\n"
        "    Create one, or pass --file PATH. A minimal fragment:\n\n%s"
        % (default, "\n".join("      " + l for l in EXAMPLE.splitlines())),
        EXIT_USAGE,
    )


def _expand(raw):
    """Path(raw).expanduser().absolute(), without the one way it explodes.

    expanduser() raises RuntimeError for a "~someuser" whose home it cannot look
    up, and unguarded that reaches the CLI as a traceback.
    """
    try:
        return Path(raw).expanduser().absolute()
    except RuntimeError as exc:
        raise LmiError(
            "the switch file path cannot be expanded: %s (%s)" % (raw, exc),
            EXIT_USAGE,
        )


def _kind(path):
    """fs.classify, but an unanswerable path is a usage error.

    Path.is_file() raises ENAMETOOLONG rather than returning False.
    """
    kind, reason = fs.classify(path)
    if kind == fs.UNKNOWN:
        raise LmiError(
            "the switch file path cannot be used: %s (%s)" % (path, reason),
            EXIT_USAGE,
        )
    return kind


def _parse(path):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LmiError(
            "the switch file cannot be read: %s (%s)" % (path, exc), EXIT_USAGE
        )
    # Through the BOM decoder: Notepad and PowerShell's Set-Content both write a
    # UTF-8 BOM, and json.loads rejects one with a bare "Expecting value".
    try:
        text = decode_with_bom(raw)
    except UnicodeDecodeError as exc:
        raise LmiError(
            "the switch file is not UTF-8: %s (%s)" % (path, exc), EXIT_USAGE
        )
    try:
        return json.loads(text)
    except ValueError as exc:
        raise LmiError(
            "the switch file is not valid JSON: %s (%s)" % (path, exc), EXIT_USAGE
        )


def _validate(doc, path):
    if not isinstance(doc, dict):
        raise LmiError(
            "the switch file must contain a JSON object: %s" % path, EXIT_USAGE
        )
    # The sentinel, not doc.get(ENV_KEY) is None, which cannot tell an absent
    # key from "env": null and so let the second through. Silent failure: null
    # is a value everywhere else here, so deep_merge would set env to null and
    # discard the whole block - ANTHROPIC_AUTH_TOKEN and all - at exit 0, while
    # "env": [] and "env": "x" beside it are exit 2.
    env = doc.get(ENV_KEY, _MISSING)
    if env is _MISSING:
        return
    if not isinstance(env, dict):
        raise LmiError('"env" must be a JSON object: %s' % path, EXIT_USAGE)
    for key, value in env.items():
        if not isinstance(value, str):
            raise LmiError(
                '"env.%s" must be a string, not %s: %s\n'
                "    Claude Code types settings.json env as string-to-string; a "
                "number is silently ignored."
                % (key, type(value).__name__, path),
                EXIT_USAGE,
            )
