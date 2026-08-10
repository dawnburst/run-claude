"""Finding, reading and validating the settings.json template.

The template is what `lmi install claude` puts in ~/.claude/settings.json: a raw
Claude Code settings document the operator wrote, installed verbatim but for the
auth token. What you write is what lands.

The mirror of lmi/commands/config/fragment.py, and deliberately shaped like it -
the two solve the same problem and someone who knows one should recognise the
other. Validation goes exactly as far as lmi can honestly judge and no further:
the file must be a JSON object, and an `env` block must map strings to strings.
Every other key passes through unexamined, because whether "mdel" is a typo for
"model" is Claude Code's schema's business and it reports that better than a
duplicated validator would. It is also what lets a setting Anthropic adds
tomorrow work today, without lmi learning it first.

Not merged into settings.py: that module is content, with no filesystem in it
beyond path(), and the reasons a file on disk can be wrong are a separate
concern from what a settings document should contain.
"""

import json

from ...core import fs
from ...core.errors import EXIT_USAGE, LmiError
from ...core.text import decode_with_bom

# Beside the lmi.json that discovery resolved, not at a path of its own. The
# config *folder* is the directory the config file came from, so --config,
# $LMI_CONFIG and the ./config/ default each carry their own template with them.
NAME = "settings.json"
ENV_KEY = "env"

# A template with no "env" key and one with "env": null are different documents,
# and doc.get(ENV_KEY) collapses them into the same None. See _validate.
_MISSING = object()

EXAMPLE = """{
  "env": {
    "ANTHROPIC_AUTH_TOKEN": "<Token from the user input>",
    "ANTHROPIC_BASE_URL": "https://gateway.example.com/"
  },
  "theme": "dark"
}"""


def load(config_path):
    """(the template, the path it came from). Raises LmiError on anything wrong.

    `config_path` is the lmi.json that was resolved; the template is its
    neighbour.
    """
    path = config_path.parent / NAME
    _require(path)
    doc = _parse(path)
    _validate(doc, path)
    return doc, path


def _require(path):
    """A missing template is an error, not an install with no configuration.

    Refused here, before npm runs, because the alternative - install the binary
    and skip the settings write - leaves a machine with no token, no base URL
    and no marketplaces while the command reports success.
    """
    if _kind(path) == fs.FILE:
        return
    raise LmiError(
        "no settings template found. `lmi install claude` installs this file as "
        "~/.claude/settings.json.\n"
        "    Expected it beside the config file, at:\n"
        "      %s\n"
        "    Create one. A minimal template:\n\n%s"
        % (path, "\n".join("      " + line for line in EXAMPLE.splitlines())),
        EXIT_USAGE,
    )


def _kind(path):
    """fs.classify, but an unanswerable path is a usage error.

    Path.is_file() raises ENAMETOOLONG rather than returning False.
    """
    kind, reason = fs.classify(path)
    if kind == fs.UNKNOWN:
        raise LmiError(
            "the settings template path cannot be used: %s (%s)" % (path, reason),
            EXIT_USAGE,
        )
    return kind


def _parse(path):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LmiError(
            "the settings template cannot be read: %s (%s)" % (path, exc),
            EXIT_USAGE,
        )
    # Through the BOM decoder: Notepad and PowerShell's Set-Content both write a
    # UTF-8 BOM, and json.loads rejects one with a bare "Expecting value".
    try:
        text = decode_with_bom(raw)
    except UnicodeDecodeError as exc:
        raise LmiError(
            "the settings template is not UTF-8: %s (%s)" % (path, exc),
            EXIT_USAGE,
        )
    try:
        return json.loads(text)
    except ValueError as exc:
        raise LmiError(
            "the settings template is not valid JSON: %s (%s)" % (path, exc),
            EXIT_USAGE,
        )


def _validate(doc, path):
    if not isinstance(doc, dict):
        raise LmiError(
            "the settings template must contain a JSON object: %s" % path,
            EXIT_USAGE,
        )
    # The sentinel, not doc.get(ENV_KEY) is None, which cannot tell an absent key
    # from "env": null and so lets the second through. Silent: compose would then
    # either write the token into a block the operator explicitly nulled or drop
    # it entirely, while "env": [] and "env": "x" beside it are exit 2.
    env = doc.get(ENV_KEY, _MISSING)
    if env is _MISSING:
        return
    if not isinstance(env, dict):
        raise LmiError(
            '"env" must be a JSON object: %s' % path, EXIT_USAGE
        )
    for key, value in env.items():
        if not isinstance(value, str):
            raise LmiError(
                '"env.%s" must be a string, not %s: %s\n'
                "    Claude Code types settings.json env as string-to-string; a "
                "number is silently ignored."
                % (key, type(value).__name__, path),
                EXIT_USAGE,
            )
