"""The state file: template, backup-or-resume, and the completion check."""

import os
import re

from ...core.errors import EXIT_USAGE, LmiError

# Only the FIRST line is ever tested against this. A whole-file search is
# wrong and fails silently: real claude restates the protocol sentence
# "write TASK_STATUS: COMPLETE on the first line only when ..." inside the
# state file, so a file-wide match stops the loop after one iteration while
# line 1 still says IN_PROGRESS. This is landmine 14 in CLAUDE.md.
# \b (not "whitespace or end of line") matches the .bat's PowerShell regex,
# so "COMPLETE." counts and "COMPLETED" does not.
COMPLETE_RE = re.compile(r"^\s*TASK_STATUS:\s*COMPLETE\b")

STATE_TEMPLATE = """\
TASK_STATUS: IN_PROGRESS

## Goal

See the TASK section of the prompt supplied by lmi schedule.
Restate it here in your own words during the first iteration.

## Completed

- nothing yet

## In progress

- nothing yet

## Next steps

- read the task and plan the first chunk of work

## Notes and blockers

- state file created by lmi schedule on {now}
"""


def write_template(path, now_str):
    body = STATE_TEMPLATE.format(now=now_str)
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
    except OSError as exc:
        # The .bat swallows this and still logs success, after which the
        # loop can never see COMPLETE and repeats iteration 1 forever.
        # Fail loudly instead.
        raise LmiError(
            "cannot write the state file %s: %s" % (path, exc), EXIT_USAGE
        )


def prepare(path, resume, run_ts, log):
    if path.exists():
        if resume:
            log.line("State file       : keeping the existing file, -r was given")
            return
        backup = path.with_name(path.name + "." + run_ts + ".bak")
        try:
            os.replace(str(path), str(backup))
        except OSError:
            log.warn(
                "Could not back up the existing state file - it is reused as is."
            )
            return
        log.line("State file       : old state backed up to " + str(backup))
        log.line(
            "                   a new run starts clean - pass -r to continue "
            "an old task"
        )
    else:
        log.line("State file       : created new")
    write_template(path, _now_str())


def _now_str():
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def check_complete(path):
    try:
        with open(path, "rb") as fh:
            first = fh.readline()
    except OSError:
        return False
    if first.startswith(b"\xef\xbb\xbf"):
        first = first[3:]
    return COMPLETE_RE.search(first.decode("utf-8", "replace")) is not None
