"""Arguments and validation for `lmi schedule`.

Validation lives with the command, not in cli.py, so that cli.py stays
pure parse-and-dispatch as commands accumulate.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import shlex

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
    # -i and -c are mutually required. argparse gives None when a flag is
    # absent, so `-i 0` is distinguishable from "-i not given" with no
    # sentinel variable - unlike the .bat, which needed INTERVAL_GIVEN.
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
        interval_min, max_runs = 0, 1
    else:
        interval_min, max_runs = args.interval, args.count
        if max_runs <= 0:
            raise LmiError("-c must be greater than 0", EXIT_USAGE)
        if interval_min < 0:
            raise LmiError("-i must not be negative", EXIT_USAGE)

    at = None
    if args.at is not None:
        try:
            at = datetime.strptime(args.at, AT_FORMAT)
        except ValueError:
            raise LmiError(
                '-t must look like YYYY-MM-DD HH:MM (quoted), got: ' + args.at,
                EXIT_USAGE,
            )

    if args.workdir is None:
        work_dir = Path.cwd()
    else:
        work_dir = Path(args.workdir)
        if not work_dir.is_dir():
            raise LmiError(
                "working directory does not exist: " + str(args.workdir), EXIT_USAGE
            )
        work_dir = work_dir.resolve()

    candidate = Path(args.prompt)
    prompt_text, prompt_file = None, None
    if candidate.is_dir():
        raise LmiError(
            "the prompt argument is a directory: " + args.prompt, EXIT_USAGE
        )
    if candidate.is_file():
        prompt_file = candidate.resolve()
    else:
        prompt_text = args.prompt

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
