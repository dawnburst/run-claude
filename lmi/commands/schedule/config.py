"""Arguments and validation for `lmi schedule`.

Validation lives with the command, not in cli.py, so that cli.py stays
pure parse-and-dispatch as commands accumulate.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import shlex

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
        help="extra claude flags, appended after --allowed-tools=Edit,Write",
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


def build_config(args):
    """Validate the parsed arguments and freeze them into a Config.

    The call order below is the order the four groups are validated in, and it
    is what decides which message a doubly-wrong command line reports.
    """
    interval_min, max_runs = _loop_shape(args)
    at = _parse_at(args)
    work_dir = _resolve_workdir(args)
    prompt_text, prompt_file = _classify_prompt(args)
    return Config(
        prompt_text=prompt_text,
        prompt_file=prompt_file,
        at=at,
        interval_min=interval_min,
        max_runs=max_runs,
        work_dir=work_dir,
        user_flags=shlex.split(args.flags) if args.flags else [],
        log_arg=args.log,
        state_arg=args.state,
        resume=args.resume,
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
