"""Which backend `lmi schedule` reaches Claude through: the one definition.

Three commands touch this vocabulary. `lmi schedule` reads it to pick a
backend, `lmi config schedule` writes it, and `lmi install claude` writes it
too - to `cli`, when it could not install the SDK. So the valid names, the
default, the parser and the writer live here, once, and the other two commands
import them.

That is a new precedent: commands otherwise import only from core/. It is
taken deliberately, and on the same reasoning that moved settings_path() into
core/claude.py. Three copies of a valid-values list is three chances for one
command to write a value another one refuses - a machine `lmi install` has
just provisioned into a mode `lmi schedule` will not accept. This module is
`schedule`'s rather than core/'s because `schedule` owns what the value
*means*; core/ has no opinion about backends.

**Nothing here may import the SDK, or anything that imports it.** `lmi config
schedule` and `lmi install claude` both import this module, and both have to
keep working on 3.9 with no extra installed - they are how a machine in that
state gets fixed. Whether the SDK can actually be imported is
commands/schedule/sdk.py's question, asked once per run by the runner.
"""

import re
from typing import NamedTuple

from ...core import config as core_config
from ...core import jsonfile
from ...core.errors import EXIT_USAGE, LmiError

# The two backends, spelled exactly. Lower case, and compared exactly: see
# parse() for why "SDK" is refused rather than folded.
SDK = "sdk"
CLI = "cli"
MODES = (SDK, CLI)

# The SDK is the default. A site that cannot install it is written to `cli` by
# `lmi install claude`, out loud and once - the fallback is the installer's
# job, never the runner's. A runner that quietly changed backend would be the
# one outcome worse than a runner that stops: both backends exit 0 on success,
# so the difference shows up only in cost, latency and which settings file was
# read.
DEFAULT = SDK

SECTION = "schedule"
KEY = "mode"

# What Claude is allowed to do, in the one form both backends read. The CLI
# backend renders this into `--allowed-tools=Edit,Write`; the SDK backend hands
# the list to ClaudeAgentOptions.allowed_tools. It lives here, with the rest of
# what the two backends must agree on, because two copies of it is the failure
# task 32 names: a task that works in one mode and mysteriously cannot write
# the state file in the other. Do not re-spell it in either backend.
ALLOWED_TOOLS = ["Edit", "Write"]

# The wording that earns an iteration a [QUOTA] tag, shared by both backends
# and unchanged from when there was only one. It lives beside ALLOWED_TOOLS for
# the same reason: [QUOTA] is the one tag that tells an unattended run its
# result is not to be trusted, and a backend that scanned for a different set
# of words would be silently less trustworthy than the other. Each backend
# scans its own RAW output with it, before anything renders that output.
QUOTA_RE = re.compile(
    r"usage limit|rate.?limit|quota|credit balance|insufficient credit"
    r"|too many requests|overloaded|exceeded your",
    re.IGNORECASE,
)

# What earns an iteration the verdict "the session this asked to resume is
# gone", in the one form both backends read. It sits beside QUOTA_RE for the
# same reason - a backend that scanned for a different set of words would be
# silently less trustworthy than the other - and with one extra rule of its own.
#
# **This pattern must never match quota wording.** A hit here discards the
# session handle and mints a fresh one, and a usage limit leaves the
# conversation perfectly intact: dropping it there loses the context in exactly
# the case continuity exists for, at exit 0, with nothing in the log to say so.
# A test asserts the two patterns do not overlap.
#
# The first alternative is claude 2.1.235's verbatim line, verified by running
# it: "No conversation found with session ID: <uuid>", exit 1, printed locally
# before any API call. The other two are near-misses from the same family,
# cheap to accept because a MISS means every remaining iteration failing
# identically against a conversation that no longer exists.
UNRESUMABLE_RE = re.compile(
    r"no conversation found|session not found|could not find session",
    re.IGNORECASE,
)

class Outcome(NamedTuple):
    """What one call to either backend comes back with.

    This was a bare `(rc, quota)` tuple until sessions arrived, and the third
    field is the one thing only the backend can know: whether claude said the
    conversation it was asked to resume does not exist. The runner needs it to
    tell "this session is gone" apart from every other failure, which it must
    not treat alike - a usage limit leaves the session perfectly usable (item
    54) and a missing conversation makes every remaining iteration fail
    identically (item 55).

    A NamedTuple rather than something the backend mutates, so the seam stays a
    function of its arguments: `call` reads a handle and returns a verdict, and
    nothing below the seam can quietly change the runner's state.
    """

    rc: int
    quota: bool
    unresumable: bool = False


# Whether one claude session is carried across the intervals.
#
# On by default: an iteration cut short - by a usage limit above all -
# continuing with the context it already had, rather than a summary of it, is
# the behaviour this command was asked for. `--no-session` and this key turn it
# off, and the header names which of the two did (item 58).
SESSION_KEY = "session"
SESSION_DEFAULT = True

# What the header, the report and `lmi config schedule` print when no config
# file said anything. Not a path, deliberately: "the default" is a different
# fact from "this file chose it", and the two must not be confusable.
DEFAULT_SOURCE = "default"

WHAT = "lmi config"

# Absent is not null. An absent "mode" key means "use the default"; a
# "mode": null is a value the operator wrote and is refused. `.get(KEY)` alone
# cannot tell them apart, and null is meaningful elsewhere in these documents -
# this is the same rule as template._validate and fragment._validate, in its
# fourth home. Do not simplify it back to `section.get(KEY) is None`.
_MISSING = object()

INVALID = (
    '"%s.%s" must be one of: %s\n'
    "    Got: %s\n"
    "    From: %s\n"
    "    There is deliberately no fall back to the default here: a run that\n"
    "    silently used a backend the operator did not choose is indis-\n"
    "    tinguishable from one that used the right one, because both exit 0."
)


SESSION_INVALID = (
    '"%s.%s" must be true or false\n'
    "    Got: %s\n"
    "    From: %s\n"
    "    There is deliberately no fall back to the default here, for the same\n"
    "    reason as the mode above: a run that silently dropped the session, or\n"
    "    kept one the operator asked it not to, is indistinguishable from one\n"
    "    that did as it was told - both exit 0."
)


def parse(raw, source):
    """One raw value into a mode name, or exit 2 naming both valid names.

    `source` is where the value came from - a config file path, or the flag
    that carried it - and appears in the message, because "cli or sdk" without
    "in this file" leaves the operator hunting for which of four discoverable
    config files said it.

    Case-sensitive on purpose. Folding "SDK" to "sdk" would mean this module
    deciding that a value the operator did not write is what they meant, and
    the values are two words long - there is nothing to be gained by guessing
    and a whole class of near-misses ("claude", "CLI ", "sdk\\n") to be got
    wrong quietly.
    """
    if isinstance(raw, str) and raw in MODES:
        return raw
    raise LmiError(
        INVALID % (SECTION, KEY, ", ".join(MODES), _shown(raw), source),
        EXIT_USAGE,
    )


def _shown(raw):
    """The offending value, quoted, with null spelled the way JSON spells it."""
    if raw is None:
        return "null"
    return repr(raw)


# --- reading --------------------------------------------------------------

def resolve(explicit_config):
    """(mode, where it came from). Never raises for a missing config file.

    Called once per run, before the lock and before the header, so a bad value
    ends the run with one message rather than as five skipped iterations.

    The discovery is core/config.py's, unchanged and unextended: --config,
    $LMI_CONFIG, ./config/lmi.json, ~/.lmi/config.json, with the pre-move
    ./lmi.json still refused at the point in the order it used to occupy. No
    new search path, no new precedence rule.
    """
    path, _ = core_config.find_optional(explicit_config)
    if path is None:
        return DEFAULT, DEFAULT_SOURCE
    return of_document(core_config.load(path), path)


def _section(doc, path):
    """The `schedule` section, `_MISSING` when absent. Refuses a non-object.

    Shared by both keys in the section deliberately: two copies of "what is a
    valid schedule section" is two chances for one key to accept a document the
    other refuses, in a file three commands write to.
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


def of_document(doc, path):
    """(mode, source) out of one already-loaded config document.

    Split from resolve() so `lmi config schedule` can report the mode of a file
    it has already read without reading it twice, and so the sentinel rule
    below has exactly one implementation.
    """
    section = _section(doc, path)
    if section is _MISSING:
        return DEFAULT, DEFAULT_SOURCE
    raw = section.get(KEY, _MISSING)
    if raw is _MISSING:
        return DEFAULT, DEFAULT_SOURCE
    return parse(raw, path), str(path)


def parse_session(raw, source):
    """One raw value into a bool, or exit 2.

    `isinstance(True, bool)`, so `1` is refused rather than folded: JSON spells
    this key `true`, and guessing at `1` or `"true"` is the near-miss class
    parse() refuses for the mode, for the same reason - there is nothing to be
    gained by guessing and a whole family of typos to get wrong quietly.
    """
    if isinstance(raw, bool):
        return raw
    raise LmiError(
        SESSION_INVALID % (SECTION, SESSION_KEY, _shown(raw), source), EXIT_USAGE
    )


def resolve_session(explicit_config):
    """(continuity on?, where that came from). Never raises for a missing file.

    Discovery is core/config.py's, unchanged and shared with resolve(): one
    lookup order governs both keys in this section, so a machine cannot end up
    reading its mode from one file and its session policy from another.
    """
    path, _ = core_config.find_optional(explicit_config)
    if path is None:
        return SESSION_DEFAULT, DEFAULT_SOURCE
    return session_of_document(core_config.load(path), path)


def session_of_document(doc, path):
    """(continuity on?, source) out of one already-loaded config document."""
    section = _section(doc, path)
    if section is _MISSING:
        return SESSION_DEFAULT, DEFAULT_SOURCE
    raw = section.get(SESSION_KEY, _MISSING)
    if raw is _MISSING:
        return SESSION_DEFAULT, DEFAULT_SOURCE
    return parse_session(raw, path), str(path)


# --- writing --------------------------------------------------------------

def write(path, mode, code):
    """Set `schedule.mode` in the config file at `path`. The ONLY writer.

    Both `lmi config schedule` and `lmi install claude` come through here.
    Two implementations would be two chances to get one of the rules wrong in
    only one of them, and the one that matters most - task 12's check that the
    file written is the file discovery would then find - is invisible when it
    is wrong.

    Everything else comes from core/jsonfile.py and must not be
    re-implemented here: an unparseable config file is refused rather than
    overwritten (nothing is written, and the message names the file), the temp
    file is born 0600 rather than chmod-ed to it afterwards, and O_BINARY keeps
    the write LF on Windows. The exit code to raise with is a parameter,
    because core/ cannot know a command's codes.

    The document is merged into, not replaced: an lmi.json carries the
    "claude" and "lmi" sections two other commands depend on, and writing only
    what this command knows about would silently unprovision the machine.
    """
    parse(mode, "the mode to write")
    doc = jsonfile.read(path, WHAT, code)
    section = doc.get(SECTION, _MISSING)
    if section is _MISSING:
        section = {}
    if not isinstance(section, dict):
        # Replacing it would discard whatever the operator put there. Refuse,
        # the way jsonfile.read refuses a document it cannot parse.
        raise LmiError(
            'the "%s" section must be a JSON object: %s\n'
            "    Refusing to overwrite it - fix or move the file and run this "
            "again." % (SECTION, path),
            code,
        )
    section = dict(section)
    section[KEY] = mode
    doc[SECTION] = section
    jsonfile.write(path, doc, WHAT, code)
