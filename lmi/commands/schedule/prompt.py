"""Composing the per-iteration prompt.

The text is run-claude.bat's :write_prompt_head / :write_prompt_tail with
one substitution: the tool names itself `lmi schedule`, because telling
claude it was started by run-claude.bat would be false.
"""

from ...core.errors import EXIT_USAGE, LmiError

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

```markdown
"""

TAIL = """```

## TASK

"""


def read_prompt_source(cfg):
    if cfg.prompt_file is None:
        return cfg.prompt_text
    raw = cfg.prompt_file.read_bytes()
    # Sniff the BOM. The .bat could only detect UTF-16 and warn; decoding it
    # properly is free here. ANSI text carries no BOM and stays undetectable
    # by construction - that limit is unchanged.
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("utf-8")
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
    return head + state_body + TAIL + task
