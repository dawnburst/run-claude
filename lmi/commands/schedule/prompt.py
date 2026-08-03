"""Composing the per-iteration prompt.

The text is run-claude.bat's :write_prompt_head / :write_prompt_tail with
one substitution: the tool names itself `lmi schedule`, because telling
claude it was started by run-claude.bat would be false.
"""

import re

from ...core import text as textlib
from ...core.errors import EXIT_USAGE, LmiError

# Everything through "## CURRENT STATE - {state_file}" and the blank line
# after it. The fence that follows is generated in compose(), not baked in
# here - see _fence_for below for why.
HEAD = """\
# Unattended automated run

You were started by the command lmi schedule with the -p flag.
Nobody is watching the terminal: never ask a question and never wait for
confirmation. Decide on your own and write down what you decided.

Iteration: {iter_label}
Started: {started}
Working directory: {work_dir}
State file: {state_file}

## State protocol - read this first

The state file above is the only memory shared between iterations. Its
current contents are copied under CURRENT STATE below.

1. Start from CURRENT STATE. Continue where the previous iteration stopped
   and never redo work that is already listed as completed.
2. Whenever you make progress, update the state file with Write or Edit.
   Do it as you go, not only at the end, so an interrupted run is not lost.
3. Keep the state file factual, self contained and under about 200 lines.
   A fresh session must be able to continue from it alone.
4. Keep this layout in the state file:
      TASK_STATUS: IN_PROGRESS
      ## Goal
      ## Completed
      ## In progress
      ## Next steps
      ## Notes and blockers
5. Write TASK_STATUS: COMPLETE on the first line only when the whole task is
   really finished. The runner stops looping as soon as it sees COMPLETE, so
   never write it while work remains.
6. If you are blocked, keep TASK_STATUS: IN_PROGRESS, describe the blocker
   under Notes and blockers and record the smallest useful next step.
7. Work in sensible chunks. Stopping this iteration once a meaningful piece
   of work is done is fine, as long as the state file is up to date first.

## CURRENT STATE - {state_file}

"""

# The part after the closing fence. The fence line itself is generated in
# compose(), so this starts with the blank line that used to follow it.
TAIL = """
## TASK

"""


def _fence_for(body):
    """Pick a backtick fence long enough that `body` cannot close it early.

    The state file is written by claude and may legitimately contain its own
    fenced code block (e.g. under "Notes and blockers"). A fixed 3-backtick
    fence around the whole CURRENT STATE block would be closed by that inner
    fence, and everything after it - potentially including the literal text
    "## TASK" - would leak out of the block and into the document, leaving
    two "## TASK" headings and no way for claude to tell which is real.

    CommonMark's own rule for this is to make the closing fence at least as
    long as the opening one, so: find the longest run of consecutive
    backticks anywhere in the body, and use one more than that (minimum 3).
    That makes the fence unclosable by the body's own content, whatever the
    content is. This length is *computed*, not fixed at 3 - do not
    "simplify" it back to a literal ``` later, that is the bug being fixed.
    """
    runs = re.findall(r"`+", body)
    longest = max((len(r) for r in runs), default=0)
    return "`" * max(3, longest + 1)


def read_prompt_source(cfg):
    if cfg.prompt_file is None:
        return cfg.prompt_text
    raw = cfg.prompt_file.read_bytes()
    # Sniff the BOM, through the same helper the state file uses. The .bat
    # could only detect UTF-16 and warn; decoding it properly is free here.
    # ANSI text carries no BOM and stays undetectable by construction - that
    # limit is unchanged.
    try:
        return textlib.decode_with_bom(raw)
    except UnicodeDecodeError as exc:
        raise LmiError(
            "the prompt file %s is not UTF-8 and has no byte order mark; "
            "save it as UTF-8 (%s)" % (cfg.prompt_file, exc),
            EXIT_USAGE,
        )


def compose(cfg, state_path, iter_label, started_str, state_body):
    head = HEAD.format(
        iter_label=iter_label,
        started=started_str,
        work_dir=cfg.work_dir,
        state_file=state_path,
    )
    task = read_prompt_source(cfg)
    if not task.endswith("\n"):
        task += "\n"
    fence = _fence_for(state_body)
    return (
        head
        + fence + "markdown\n"
        + state_body
        + fence + "\n"
        + TAIL
        + task
    )
