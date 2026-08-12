"""Arguments and validation for `lmi schedule`.

Validation lives with the command, not in cli.py, so that cli.py stays
pure parse-and-dispatch as commands accumulate.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import shlex

from . import backend
from ...core import config as core_config
from ...core import fs
from ...core.errors import EXIT_USAGE, LmiError

AT_FORMAT = "%Y-%m-%d %H:%M"


def add_arguments(parser):
    parser.add_argument(
        "prompt",
        help="the prompt text, or the path of a UTF-8 file containing it",
    )
    parser.add_argument(
        "-t", dest="at", metavar="WHEN",
        help='start at this time, "YYYY-MM-DD HH:MM" (quote it). Default: now',
    )
    parser.add_argument(
        "-i", dest="interval", type=int, metavar="MINUTES",
        help="minutes between iterations; requires -c. 0 runs them back to back",
    )
    parser.add_argument(
        "-c", dest="count", type=int, metavar="N",
        help="number of iterations; requires -i. Must be greater than 0",
    )
    parser.add_argument(
        "-d", dest="workdir", metavar="DIR",
        help="working directory for claude. Default: the current directory",
    )
    parser.add_argument(
        "-f", dest="flags", default="", metavar="FLAGS",
        help="extra claude flags. CLI mode appends them to the argv; SDK "
             "mode forwards them to the claude it spawns",
    )
    parser.add_argument(
        "-l", dest="log", metavar="PATH",
        help="log folder, or a full log file path",
    )
    parser.add_argument(
        "-s", dest="state", metavar="FILE",
        help="state file. Default: <workdir>/run-claude-state.md",
    )
    parser.add_argument(
        "-r", dest="resume", action="store_true",
        help="resume: keep the existing state file instead of backing it up",
    )
    parser.add_argument(
        "-v", "--verbose", dest="verbose", action="store_true",
        help="log the prompt and render claude's activity live as it happens",
    )
    # The same --config every other command takes, for the same file. It is
    # what makes "the discovery order is unchanged" true for this command too:
    # the backend is read from the `schedule` section of whichever lmi.json
    # discovery resolves, and --config is the first step of that order.
    #
    # There is deliberately no --mode here. The switch is configuration, and a
    # flag would need a precedence rule against the config file - one more way
    # for a run to use a backend the operator did not intend. Change it with
    # `lmi config schedule --mode ...`.
    core_config.add_argument(parser)


@dataclass
class Config:
    prompt_text: Optional[str]
    prompt_file: Optional[Path]
    at: Optional[datetime]
    interval_min: int
    max_runs: int
    work_dir: Path
    user_flags: List[str] = field(default_factory=list)
    log_arg: Optional[str] = None
    state_arg: Optional[str] = None
    resume: bool = False
    verbose: bool = False
    # Which backend reaches Claude, and what chose it. The source is carried
    # alongside the mode because the log header has to name both: two backends
    # that both exit 0 on success are told apart by nothing else.
    mode: str = backend.DEFAULT
    mode_source: str = backend.DEFAULT_SOURCE


def build_config(args):
    """Validate the parsed arguments and freeze them into a Config.

    The call order below is the order the four groups are validated in, and it
    is what decides which message a doubly-wrong command line reports.
    """
    interval_min, max_runs = _loop_shape(args)
    at = _parse_at(args)
    work_dir = _resolve_workdir(args)
    prompt_text, prompt_file = _classify_prompt(args)
    user_flags = shlex.split(args.flags) if args.flags else []
    _reject_output_format(args.verbose, user_flags)
    # Resolved here rather than in the runner so that a bad value ends the run
    # before the lock, the header and the loop - once, not as N skipped
    # iterations. getattr, because several callers build an args object by hand.
    mode, mode_source = backend.resolve(getattr(args, "config", None))
    _check_forwardable(mode, user_flags)
    return Config(
        prompt_text=prompt_text,
        prompt_file=prompt_file,
        at=at,
        interval_min=interval_min,
        max_runs=max_runs,
        work_dir=work_dir,
        user_flags=user_flags,
        log_arg=args.log,
        state_arg=args.state,
        resume=args.resume,
        verbose=args.verbose,
        mode=mode,
        mode_source=mode_source,
    )


def _check_forwardable(mode, user_flags):
    """-f works in BOTH backends. Validate it here so a bad flag costs exit 2.

    In CLI mode the flags are appended to the argv. In SDK mode they are handed
    to the SDK as `extra_args`, which the SDK renders onto the argv of the
    `claude` it spawns - so -f keeps meaning the same thing in both modes: the
    flags reach the same command line.

    Parsed at config time rather than at the first call, so a flag the SDK
    cannot forward ends the run with one message before the lock and before the
    header, instead of five times over as skipped iterations. The parse itself
    lives in sdk.py, because the mapping shape is the SDK's; nothing here
    imports the SDK, and sdk.parse_flags does not either.
    """
    if not user_flags or mode == backend.CLI:
        return
    from . import sdk
    sdk.parse_flags(user_flags)


def _reject_output_format(verbose, user_flags):
    """Refuse -v together with an --output-format of the user's own.

    -f is appended after lmi's flags and claude takes the last occurrence of a
    repeated option, so -f "--output-format json" silently overrides the
    stream-json that -v's renderer depends on: the activity block goes quiet
    and the iteration still exits 0. This is validation, not flag rewriting -
    lmi never edits or filters -f, it only declines a pair it cannot honour.

    A duplicate --verbose is deliberately NOT rejected here. That flag is a
    boolean, so a second occurrence is idempotent; --output-format is
    last-wins. Generalising this into flag deduplication would mean lmi
    learning claude's flag grammar, and risk dropping a user's flag silently.
    """
    if not verbose:
        return
    for token in user_flags:
        if token == "--output-format" or token.startswith("--output-format="):
            raise LmiError(
                "-v already sets --output-format stream-json, so it cannot be "
                "combined with an --output-format in -f. Drop one of the two: "
                "-v for the rendered activity log, or -f for your own format.",
                EXIT_USAGE,
            )


def _loop_shape(args):
    """(minutes between iterations, how many iterations).

    -i and -c are mutually required. argparse gives None when a flag is absent,
    so `-i 0` is distinguishable from "-i not given" without a sentinel.
    """
    if args.interval is not None and args.count is None:
        raise LmiError(
            "-i requires -c: an unattended loop must have a stop condition",
            EXIT_USAGE,
        )
    if args.count is not None and args.interval is None:
        raise LmiError(
            "-c requires -i: give the interval between iterations too", EXIT_USAGE
        )

    if args.interval is None:
        return 0, 1
    if args.count <= 0:
        raise LmiError("-c must be greater than 0", EXIT_USAGE)
    if args.interval < 0:
        raise LmiError("-i must not be negative", EXIT_USAGE)
    return args.interval, args.count


def _parse_at(args):
    """The -t start time, or None for "start now"."""
    if args.at is None:
        return None
    try:
        return datetime.strptime(args.at, AT_FORMAT)
    except ValueError:
        raise LmiError(
            "-t must look like YYYY-MM-DD HH:MM (quoted), got: " + args.at,
            EXIT_USAGE,
        )


def _resolve_workdir(args):
    """The -d working directory, defaulting to the current one."""
    if args.workdir is None:
        return Path.cwd()
    kind, reason = fs.classify(args.workdir)
    if kind == fs.DIR:
        return Path(args.workdir).resolve()
    if kind == fs.MISSING:
        raise LmiError(
            "working directory does not exist: " + str(args.workdir), EXIT_USAGE
        )
    if kind == fs.UNKNOWN:
        raise LmiError(
            "working directory cannot be used: %s (%s)" % (args.workdir, reason),
            EXIT_USAGE,
        )
    # It exists and is a file, or a fifo. "does not exist" sent people looking
    # for a typo in a path that was right all along.
    raise LmiError(
        "working directory is not a directory: " + str(args.workdir), EXIT_USAGE
    )


def _classify_prompt(args):
    """(prompt text, prompt file) - exactly one of the two is set."""
    # argparse accepts an empty positional, and Path("") is PosixPath('.'),
    # which classifies as a directory - so `lmi schedule ""` used to complain
    # that the prompt is a directory. It is simply missing.
    if not args.prompt.strip():
        raise LmiError(
            "the prompt is empty: give the prompt text, or the path of a "
            "UTF-8 file containing it",
            EXIT_USAGE,
        )
    # fs.kind, not Path.is_dir(): an inline prompt reaching 256 bytes without a
    # slash makes the raw pathlib call raise ENAMETOOLONG. Anything the OS will
    # not classify is simply not a path, so it is prompt text.
    kind = fs.kind(args.prompt)
    if kind == fs.DIR:
        raise LmiError(
            "the prompt argument is a directory: " + args.prompt, EXIT_USAGE
        )
    if kind == fs.FILE:
        return None, Path(args.prompt).resolve()
    return args.prompt, None
