"""The state file: template, backup-or-resume, and the completion check."""

import os
import re

from ...core import text as textlib
from ...core.errors import EXIT_USAGE, LmiError
from . import paths

# Only the FIRST line is ever tested against this, and that is the whole point.
# A whole-file search is wrong and fails silently: claude reliably restates the
# protocol sentence "write TASK_STATUS: COMPLETE on the first line only when
# ..." inside the state file, so a file-wide match stops the loop after one
# iteration while line 1 still says IN_PROGRESS - a run that reports "1 run, 1
# succeeded" and exit 0 with four fifths of the task abandoned. Do not
# "optimise" the read below into a search over the file.
# \b rather than "whitespace or end of line", so "COMPLETE." counts as complete
# and "COMPLETED" does not.
# re.IGNORECASE is deliberate: a hand-edited state file whose line 1 reads
# "task_status: complete" means the task is complete. It cannot reopen the
# false-positive above, because the read below is still line-1-only, so lenient
# casing can never reach prose deeper in the file.
COMPLETE_RE = re.compile(r"^\s*TASK_STATUS:\s*COMPLETE\b", re.IGNORECASE)

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
        # Swallowing this would log success and then loop on an untouched
        # template forever, since the loop can never see COMPLETE in a file
        # nobody can write. Fail loudly instead.
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
    write_template(path, paths.now_str())


def read_body(path):
    """The state file as text, for inlining into the next prompt.

    Decoded through the same BOM logic as check_complete, deliberately: a
    UTF-16 state file that the completion check reads correctly must not be
    inlined into the prompt as mojibake. errors="replace" because a state file
    claude has half-written must never end the run.
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return ""
    return textlib.decode_with_bom(raw, "replace")


def check_complete(path):
    # A fixed head read (rather than a binary readline()) so a UTF-16 first
    # line - whose newline byte 0x0A shows up as half of a 2-byte code unit -
    # is never cut mid code-unit before decoding. The status line is always
    # short, so 4096 bytes comfortably covers it regardless of encoding.
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        return False
    # A state file hand-edited in a Windows editor can arrive as UTF-16, so the
    # BOM decides the encoding here too. An empty file decodes to no lines at
    # all, which the fallback below turns into "not complete".
    lines = textlib.decode_with_bom(head, "replace").splitlines()
    first_line = lines[0] if lines else ""
    return COMPLETE_RE.search(first_line) is not None
