"""The state file: template, backup-or-resume, and the completion check."""

import os
import re

from ...core import text as textlib
from ...core.errors import EXIT_USAGE, LmiError
from . import paths

# Only the FIRST line is ever tested against this. A whole-file search is
# wrong and fails silently: real claude restates the protocol sentence
# "write TASK_STATUS: COMPLETE on the first line only when ..." inside the
# state file, so a file-wide match stops the loop after one iteration while
# line 1 still says IN_PROGRESS. This is landmine 14 in CLAUDE.md.
# \b (not "whitespace or end of line") matches the .bat's PowerShell regex,
# so "COMPLETE." counts and "COMPLETED" does not.
# re.IGNORECASE is required, not a stylistic choice: the .bat's PowerShell
# "-match" operator is case-insensitive by default (the case-sensitive form
# is the distinct "-cmatch", which is not used). A state file is meant to be
# interchangeable between run-claude.bat and lmi schedule, so
# "task_status: complete" on line 1 must be COMPLETE to both or neither.
# Do NOT tighten this to case-sensitive later - that would silently diverge
# from the .bat again. Being case-insensitive cannot reopen landmine 14: the
# read below is still line-1-only, so lenient casing cannot make prose
# deeper in the file match.
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
    if not head:
        return False
    # PowerShell's Get-Content auto-detects UTF-16 from its BOM, so a state
    # file hand-edited in a Windows editor may arrive that way.
    lines = textlib.decode_with_bom(head, "replace").splitlines()
    first_line = lines[0] if lines else ""
    return COMPLETE_RE.search(first_line) is not None
