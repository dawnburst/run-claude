"""The SDK backend: the only module in lmi that imports claude_agent_sdk.

Same containment rule stream.py follows for claude's stdout schema, for a
sharper reason. `commands/__init__.py` imports every command at startup, so an
import failure here would break `lmi install claude` and `lmi upgrade` - the
two commands whose entire job is fixing a machine whose SDK is missing or
broken. The import therefore happens INSIDE the functions below, never at
module scope, and `tests/test_packaging.py` fails if any other module in lmi/
grows one.

This module's whole contract is `call()`: composed prompt, Config and session
handle in, the same `backend.Outcome` the CLI backend returns out. The runner cannot
tell the two apart, and nothing above the seam knows the SDK exists.
"""

import asyncio

from . import backend
from .stream import MessageRenderer
from ...core.errors import EXIT_USAGE, LmiError

# What a failed SDK call is recorded as.
#
# Non-zero, so the iteration is counted as failed, and deliberately NOT
# runner.ITERATION_ERROR_RC (90): that code means "the iteration never reached
# Claude at all", and a call that reached Claude and came back wrong is a
# different fact. Folding them together would make an unattended log unable to
# distinguish a broken backend from a broken workspace. Declared here rather
# than imported from runner.py, which imports this module; a test pins the two
# apart.
CALL_FAILED_RC = 91

# A stream that ends with no ResultMessage at all.
#
# This is a row in its own right and NOT a success. Mapping it to 0 is
# regression 1 with a new front end: the iteration is counted as a success, the
# run exits 0, and nothing was done. The SDK ends every completed query with a
# ResultMessage, so its absence means the stream was cut off - which is exactly
# the case that must be loud.
NO_RESULT_RC = CALL_FAILED_RC

MISSING = (
    "the Claude Agent SDK is not installed, and this machine is configured to\n"
    "    use the `%s` backend.\n"
    "    (%s)\n"
    "\n"
    "    Three ways out, in the order most sites want them:\n"
    "\n"
    "      - install it from your site's package index:\n"
    "            lmi install claude\n"
    "      - install it by hand, if lmi itself is already where you want it:\n"
    '            pip install "lmi[sdk]"\n'
    "      - or run the `%s` backend instead, which needs no Python package\n"
    "        at all and drives the `claude` command:\n"
    "            lmi config schedule --mode %s\n"
    "\n"
    "    lmi deliberately does not fall back on its own. Both backends exit 0\n"
    "    on success, so a run that quietly changed backend is indistinguishable\n"
    "    from one that did not - the fallback belongs to the installer, once,\n"
    "    written into a file a human can read."
)


def _import():
    """The SDK module, or exit 2 naming every way to fix it.

    Inside a function, never at module scope - see this module's docstring.
    """
    try:
        import claude_agent_sdk
    except ImportError as exc:
        raise LmiError(
            MISSING % (backend.SDK, exc, backend.CLI, backend.CLI), EXIT_USAGE
        )
    return claude_agent_sdk


def require(session=False):
    """Fail now if this backend cannot run at all.

    Called once per run, before the lock and before the header, so a machine
    with no SDK produces one message rather than N skipped iterations - and
    produces it before the log claims a run started.

    `session` is checked separately from the import because the two failures have
    different fixes and different blast radii: no SDK at all stops every run,
    while an SDK too old for `session_id` stops only the runs that want
    continuity - and those can still run with --no-session.
    """
    module = _import()
    if session:
        _require_session_fields(module)


# The two ClaudeAgentOptions fields one session across the intervals needs.
#
# Present in 0.2.136, the floor both pyproject.toml and install/sdk.REQUIREMENT
# name - verified by inspecting the installed package, which is why that floor
# does not move for this feature. The check below is for a machine whose
# installed SDK is OLDER than the floor, which an air-gapped mirror can easily
# be.
SESSION_FIELDS = ("session_id", "resume")

OLD_SDK = (
    "the installed Claude Agent SDK cannot carry one claude session across the\n"
    "    iterations: its ClaudeAgentOptions has no `%s` field.\n"
    "\n"
    "    Two ways out:\n"
    "\n"
    "      - upgrade it, which is what the `sdk` extra already pins:\n"
    '            pip install --upgrade "lmi[sdk]"\n'
    "      - or run without continuity, which is how `lmi schedule` behaved\n"
    "        before this existed - every iteration fresh, the state file\n"
    "        carrying the work forward:\n"
    "            lmi schedule ... --no-session\n"
    "\n"
    "    Checked here, once, rather than at the call: passing a keyword the\n"
    "    dataclass does not define is a TypeError on every iteration of the\n"
    "    run, and importable has never meant able to build its options."
)


def _require_session_fields(module):
    """Exit 2 when the installed options object has no session fields.

    `dataclasses.fields` raises TypeError for anything that is not a dataclass -
    the suite's own fake among them - and that is treated as "nothing to check"
    rather than as a failure: this guard exists to catch an SDK older than the
    floor, not to legislate how the class is built.
    """
    import dataclasses
    try:
        names = {f.name for f in dataclasses.fields(module.ClaudeAgentOptions)}
    except TypeError:
        return
    missing = [name for name in SESSION_FIELDS if name not in names]
    if missing:
        raise LmiError(OLD_SDK % missing[0], EXIT_USAGE)


def describe(cfg, log):
    """The header lines this backend contributes. The CLI backend has its own.

    The two backends resolve different things, so they describe different
    things: there is no argv here to print, and no `claude` on PATH that lmi
    chose. What there is, is every option that decides what Claude may do -
    which is the half of the CLI's Flags line that actually matters.
    """
    log.line("SDK       : claude_agent_sdk %s" % _version())
    log.line("Tools     : " + ",".join(backend.ALLOWED_TOOLS))
    log.line("Permission: " + PERMISSION_MODE)
    log.line("Settings  : " + ",".join(SETTING_SOURCES))
    # The forwarded -f, for the same reason the CLI backend prints its whole
    # argv: an unattended run's log is its only record of what was actually
    # asked for. Printed only when there is something, so a plain run's header
    # does not grow a line that always says the same thing.
    extra = parse_flags(cfg.user_flags)
    if extra:
        log.line("Flags     : " + " ".join(
            "--%s" % k if v is None else "--%s %s" % (k, v)
            for k, v in extra.items()
        ))


def _version():
    """The installed SDK's version, or a placeholder. Never raises.

    A diagnostic that can fail the command it diagnoses is worse than no
    diagnostic - the same rule `lmi upgrade`'s version probe follows.
    """
    try:
        from importlib import metadata
        return metadata.version("claude-agent-sdk")
    except Exception:                       # noqa: BLE001 - any failure is "?"
        return "(version unknown)"


# --- -f, forwarded ---------------------------------------------------------

# Flags lmi will not forward, and why each one cannot be honoured.
#
# `extra_args` is appended AFTER the flags the SDK builds for itself, and the
# CLI takes the last occurrence of a repeated option - so a duplicate of one of
# these does not add anything, it overrides the SDK's own and breaks it:
#
#   output-format / input-format  the SDK's transport protocol with the CLI. Both
#                                 sides speak stream-json; override either and
#                                 the SDK can no longer parse its own child.
#   print                         the SDK owns the non-interactive mode.
#   permission-mode               invariant 3. lmi chooses a mode that cannot
#                                 wait for a keypress; -f must not undo that.
#
# Refused, never dropped: a flag silently ignored is the failure this whole
# option exists to avoid, because -f is where a site puts what it cannot say any
# other way.
_NOT_FORWARDED = {
    "output-format": "the SDK and the CLI speak stream-json to each other",
    "input-format": "the SDK and the CLI speak stream-json to each other",
    "print": "the SDK always runs the non-interactive mode",
    "permission-mode": "lmi sets a non-interactive permission mode (invariant 3)",
}

BAD_FLAG = (
    "-f cannot forward %s to the %s backend:\n"
    "    %s.\n"
    "    Everything else in -f is passed through to the `claude` command the\n"
    "    SDK runs, so drop just this one - or run the %s backend, which puts\n"
    "    your flags on the command line verbatim:\n\n"
    "        lmi config schedule --mode %s"
)

SHORT_FLAG = (
    "-f can only forward long options (--like-this) to the %s backend, and got:\n"
    "    %s\n"
    "    The SDK forwards flags as a name/value mapping, which has no way to\n"
    "    spell a single-dash option. Use the long form, or run the %s backend:\n\n"
    "        lmi config schedule --mode %s"
)


def parse_flags(user_flags):
    """The -f tokens as the SDK's `extra_args` mapping. {} when there are none.

    The SDK renders `{"model": "sonnet"}` as `--model sonnet` onto the argv of
    the `claude` it spawns, so -f keeps meaning what it means in CLI mode: the
    flags reach the same command line. That is why this is a token-shape
    conversion and NOT a translation into ClaudeAgentOptions fields - lmi never
    learns what any individual flag means, which is the rule item 26 is about.
    Only the four in _NOT_FORWARDED are known by name, and only to refuse them.

    A value beginning with `-` is not treated as a value, because it cannot be
    told apart from the next flag; write `--flag=-value` for those, which the SDK
    renders in the equals form the CLI always binds.
    """
    extra = {}
    tokens = list(user_flags)
    while tokens:
        token = tokens.pop(0)
        if not token.startswith("--"):
            raise LmiError(
                SHORT_FLAG % (backend.SDK, token, backend.CLI, backend.CLI),
                EXIT_USAGE,
            )
        name, sep, value = token[2:].partition("=")
        if not sep:
            if tokens and not tokens[0].startswith("-"):
                value = tokens.pop(0)
            else:
                value = None
        _refuse_owned(name)
        extra[name] = value
    return extra


def _refuse_owned(name):
    why = _NOT_FORWARDED.get(name)
    if why:
        raise LmiError(
            BAD_FLAG % ("--" + name, backend.SDK, why, backend.CLI, backend.CLI),
            EXIT_USAGE,
        )


# --- the options ----------------------------------------------------------

# Invariant 3: nothing in the unattended runner may ever wait for a keypress.
# The SDK's default permission mode is not that - it asks. acceptEdits is the
# narrowest mode that still lets the state file be written, which is the one
# thing every iteration must be able to do.
#
# `can_use_tool` is never set anywhere in this module, and must not be: a
# callback that awaits anything is a keypress wait wearing a library's clothes,
# and it would hang an unattended run rather than fail it. Do not add one.
PERMISSION_MODE = "acceptEdits"

# Where Claude Code reads its settings from.
#
# The single sharpest asymmetry between the two backends. The CLI backend read
# ~/.claude/settings.json by virtue of BEING the CLI; the SDK loads settings
# only from the sources it is told to load. Omit the user source and SDK mode
# runs against the wrong endpoint with no credentials - while `lmi config
# switch`, whose entire purpose is changing that file, silently stops affecting
# `lmi schedule` at all.
#
# Do not simplify this back to omitting the argument, and do not trim it to
# just "user": project and local are what the CLI reads too, and a backend that
# reads a different set of files from the other one is a difference nobody can
# see in the result.
SETTING_SOURCES = ["user", "project", "local"]


def _options(cfg, state_path, on_stderr, handle):
    """ClaudeAgentOptions carrying exactly what _claude_argv carries.

    One for one with the CLI backend's argv, which is the specification:

        --allowed-tools=Edit,Write   -> allowed_tools
        --add-dir <state dir>        -> add_dirs
        subprocess.run(cwd=...)      -> cwd
        -p                           -> implicit in query()

    Nothing may be dropped on the way across. The two backends have to grant
    the same tools and the same directories, or a task that works in one mode
    mysteriously cannot write the state file in the other.
    """
    module = _import()
    kwargs = dict(
        allowed_tools=list(backend.ALLOWED_TOOLS),
        add_dirs=[str(state_path.parent)],
        cwd=str(cfg.work_dir),
        permission_mode=PERMISSION_MODE,
        setting_sources=list(SETTING_SOURCES),
        stderr=on_stderr,
        # -f, onto the argv of the `claude` the SDK spawns - see parse_flags.
        extra_args=parse_flags(cfg.user_flags),
    )
    if handle is not None:
        # The CLI backend's --session-id / --resume pair, one for one: exactly
        # one of the two, ever.
        #
        # `fork_session` is never set here and must not be. A forked resume
        # returns a NEW session id every iteration, so the sidecar's handle goes
        # stale while every iteration still looks like a correct resume - and the
        # run exits 0 throughout. `continue_conversation` is absent for a
        # related reason: it means "the most recent conversation in this
        # directory", which is claude choosing rather than lmi, and any other
        # claude run in the same -d between two intervals would silently steal
        # the continuity.
        if handle.resuming:
            kwargs["resume"] = handle.id
        else:
            kwargs["session_id"] = handle.id
    return module.ClaudeAgentOptions(**kwargs)


# --- the call -------------------------------------------------------------

def call(cfg, log, composed, state_path, handle=None):
    """Run one iteration through the SDK. A backend.Outcome.

    The CLI backend's signature and return, exactly - the handle included. Everything above the seam
    speaks `rc`, because `_log_iteration_result`, `ITERATION_ERROR_RC` and
    `EXIT_CALL_FAILED` already do and a second vocabulary would mean two ways
    to read the same log.

    One event loop per iteration, created and torn down right here. The runner
    stays synchronous and every wait in it stays a `time.sleep` - invariant 3's
    other half. Do not make run(), _run_locked or _one_iteration async.

    An exception is handled two different ways, and the split is the whole of
    item 45 - it was found by the first real run, against a real SDK:

      * a ResultMessage HAS already arrived. Claude was reached, answered, and
        the answer was an error - the SDK yields the result and only then raises
        on the error envelope that follows it. Letting that propagate throws
        away both facts the sink has already worked out: `rc`, which is
        CALL_FAILED_RC rather than "never reached Claude at all", and `quota`,
        which is the [QUOTA] tag and the only warning an unattended run gets
        that its result is not to be trusted. So it is recorded and returned.
      * no ResultMessage arrived. Then nothing is known about the call and the
        exception is re-raised, reaching _iteration_rc, which records the
        iteration as skipped and lets the loop carry on - invariant 2's
        exception half, and item 12.

    Do not simplify this back into "exceptions are not caught": that spelling
    made an expired login and an exhausted quota both read as a *skipped*
    iteration with no [QUOTA] tag, which is the wrong fact twice over.
    """
    log.line("--- claude activity ---")
    sink = _Sink(cfg, log, handle)
    try:
        asyncio.run(_drive(cfg, composed, state_path, sink, handle))
    except Exception as exc:                # noqa: BLE001 - see the docstring
        if not sink.saw_result:
            raise
        sink.failed(exc)
    log.line("--- end of claude activity ---")
    return backend.Outcome(sink.rc, sink.quota, sink.unresumable)


async def _drive(cfg, composed, state_path, sink, handle):
    module = _import()
    options = _options(cfg, state_path, sink.stderr, handle)
    # prompt as a plain string: query() takes the text directly, so there is no
    # prompt-N.txt and no out-N.txt in this mode. The runner's temp workspace
    # still exists for the CLI backend - this backend simply does not use it.
    async for message in module.query(prompt=composed, options=options):
        sink.message(message)


class _Sink:
    """Everything one iteration's messages turn into: log lines, rc, quota.

    Separate from the async generator above so that the only `async` in this
    command is the four lines that have to be.
    """

    def __init__(self, cfg, log, handle=None):
        self.log = log
        self.verbose = cfg.verbose
        self.renderer = MessageRenderer(log)
        self.quota = False
        # No ResultMessage yet, and that is a failure until one arrives. The
        # default must never be 0: a stream cut off before its result would
        # otherwise be counted as a successful iteration that did nothing.
        self.rc = NO_RESULT_RC
        # Whether claude said the conversation it was asked to resume does not
        # exist. Read off the same raw text the quota scan reads, never off a
        # rendered row - see _scan.
        self.unresumable = False
        # The session this iteration ASKED for, so the id that answers can be
        # compared against it. SDK-only, and declared as such: CLI mode's plain
        # output carries no session id at all.
        self.handle = handle
        self._warned_id = False
        # Whether Claude answered at all, which is what call() splits on. Not
        # derivable from `rc`: NO_RESULT_RC and CALL_FAILED_RC are the same
        # number by design, so the code alone cannot say whether a result was
        # seen.
        self.saw_result = False

    def message(self, message):
        # Scanned BEFORE anything renders it, and off the message's own
        # attributes rather than off a rendered line. Item 28, restated for a
        # shape where "the raw line" no longer exists: under the SDK the
        # usage-limit wording lives inside a result or an assistant text block,
        # and scanning afterwards would mean any future renderer change that
        # summarised such a message without carrying its text through silently
        # disabled [QUOTA] - the one tag that tells an unattended run its
        # result is not to be trusted. Scanning first makes that impossible
        # however stream.py evolves.
        self._scan(_raw_text(message))
        self._check_id(message)
        if _rate_limited(message):
            self.quota = True
        if type(message).__name__ == "ResultMessage":
            self.saw_result = True
            self.rc = _rc_of(message)
        if self.verbose:
            self.log.line(self.renderer.render(message))
        elif type(message).__name__ == "ResultMessage":
            # Without -v the CLI backend logs claude's plain output and nothing
            # else, so this backend logs the final result text and nothing
            # else. The activity rendering is what -v buys, in both modes.
            for line in str(getattr(message, "result", "") or "").splitlines():
                self.log.line(line)

    def _check_id(self, message):
        """Warn when the session that answered is not the one asked for.

        Free here, because every message is walked already - and impossible in
        CLI mode, whose plain output carries no id and whose format lmi must not
        change (item 26). So this is an asymmetry between the backends, which is
        acceptable only because it is declared: docs/status.md records that the
        CLI cannot observe a substituted session, rather than the two modes
        looking equally careful.

        Once per iteration. A stream carries the id on nearly every message, and
        the second warning would say nothing the first did not.
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

    def failed(self, exc):
        """The SDK raised after Claude had already answered.

        Scanned like everything else, because the exception text is where the
        SDK puts the error envelope's message and a usage limit can be reported
        there and nowhere else. Logged as an [ERROR] rather than a traceback:
        the iteration is a failed call, which the summary already counts, and
        the reason a reader needs is the one line - the rendered `done` row
        immediately above carries the rest.
        """
        text = "%s: %s" % (type(exc).__name__, exc)
        self._scan(text)
        self.log.error("the SDK reported the call failed - " + text)

    def stderr(self, line):
        """The SDK's stderr callback: the underlying binary's diagnostics.

        CLI mode gets these through stderr=subprocess.STDOUT. Without this they
        vanish, and an unattended run's only record loses the half of the
        output that says why something failed. Scanned for quota wording too,
        for the same reason as everything else here.
        """
        text = line.rstrip("\r\n")
        self._scan(text)
        self.log.line(text)

    def _scan(self, text):
        if not text:
            return
        if backend.QUOTA_RE.search(text):
            self.quota = True
        if backend.UNRESUMABLE_RE.search(text):
            self.unresumable = True


def _session_id_of(message):
    """The session id a message reports, across the two shapes that carry one.

    ResultMessage and AssistantMessage have a `session_id` field; SystemMessage
    carries its init payload in `data`. Both verified against 0.2.136, the floor
    version - which is also why no version check guards this: the fields have
    been there as long as the floor has.
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


def _rc_of(message):
    """The exit code one ResultMessage means. The whole mapping, in one place.

        subtype == "success"   -> 0
        any other subtype      -> CALL_FAILED_RC
        no ResultMessage       -> NO_RESULT_RC   (see _Sink.rc's default)

    BOTH fields are consulted, and both are load-bearing. `subtype` alone is
    not enough, which a real run settled: with no valid credential the SDK
    returns a ResultMessage carrying **`subtype == "success"` and
    `is_error == True`** - the CLI's own wording for it is "returned an error
    result: success" - so gating on the subtype counted a call that did nothing
    as a successful iteration. That is regression 1 with a new front end, and it
    is the exact reason item 41 exists.

    `is_error` alone is not enough either: it has to be trusted to be set,
    whereas the subtype check treats every value it does not recognise as a
    failure. So a zero requires both to agree, and either one is allowed to fail
    the call. Verified against claude-agent-sdk 0.2.136; do not narrow this to
    one field again in either direction.
    """
    if getattr(message, "is_error", False):
        return CALL_FAILED_RC
    return 0 if getattr(message, "subtype", None) == "success" else CALL_FAILED_RC


# Every attribute that can carry the wording QUOTA_RE looks for, across the
# message types the SDK actually emits. An allowlist rather than "stringify the
# whole object", so that adding one is a deliberate act with a reason beside it.
#
# `rate_limit_info` is the one that must never be dropped: it is the entire
# payload of RateLimitEvent, which is the SDK's OWN name for the thing [QUOTA]
# exists to catch. Scanning only result/content/data - as this did at first -
# meant a real rate limit was the one event that could not raise the tag, while
# the CLI backend caught it for free by scanning whole raw lines. That is a
# silent asymmetry in the one signal that tells an unattended run its result is
# not to be trusted, in the direction that under-reports. See CLAUDE.md item 43.
_TEXT_ATTRS = (
    "result",               # ResultMessage: the final text
    "error",                # AssistantMessage
    "errors",               # ResultMessage
    "api_error_status",     # ResultMessage: where an HTTP 429 surfaces
    "stop_reason",          # ResultMessage, AssistantMessage
    "terminal_reason",      # ResultMessage
    "tool_use_result",      # UserMessage
)

# A RateLimitEvent is deliberately NOT in the list above, and this is the second
# half of item 43. It is structured telemetry rather than prose, and the SDK
# emits it on healthy runs too - the one seen on a real successful iteration
# carried `status='allowed'`. Running QUOTA_RE over it tagged **every** such run,
# because its repr contains the literal "RateLimitInfo" and "rate_limit_type"
# and the pattern's `rate.?limit` clause matches both. So it is read by its
# `status` field instead.
#
# Both directions of getting this wrong make the tag worthless: scanning nothing
# meant a real limit was never flagged, and scanning the repr meant every run
# was. A regex is for prose; a struct gets read.
_RATE_LIMIT_OK = "allowed"


def _rate_limited(message):
    """True when a rate-limit event says a limit was actually applied.

    Anything that is not exactly the healthy status counts, including a status
    this code cannot read at all: under-reporting is the dangerous direction for
    [QUOTA], so an event whose shape changed should flag rather than go quiet.
    """
    info = getattr(message, "rate_limit_info", None)
    if info is None:
        return False
    status = getattr(info, "status", None)
    if status is None and isinstance(info, dict):
        status = info.get("status")
    return str(status) != _RATE_LIMIT_OK


def _raw_text(message):
    """Every scrap of text a message carries, for the quota scan only.

    Never rendered and never logged - it exists so the scan reads what the SDK
    actually said rather than what stream.py chose to keep. Everything is taken
    through str(), because several of these fields are dicts or dataclasses
    whose repr is what carries the wording.
    """
    parts = [str(getattr(message, name, "") or "") for name in _TEXT_ATTRS]
    content = getattr(message, "content", None)
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            parts.append(str(getattr(block, "text", "") or ""))
            parts.append(str(getattr(block, "thinking", "") or ""))
            inner = getattr(block, "content", None)
            if isinstance(inner, str):
                parts.append(inner)
            elif isinstance(inner, list):
                parts.extend(
                    str(b.get("text", "")) for b in inner if isinstance(b, dict)
                )
    data = getattr(message, "data", None)
    if isinstance(data, dict):
        parts.extend(str(v) for v in data.values())
    return " ".join(p for p in parts if p)
