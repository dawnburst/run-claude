This is a test of the run-claude.bat runner. Work strictly inside the current
working directory.

The task has five numbered steps. Do exactly ONE step per run: the lowest
numbered step that is not yet recorded as done in the state file. Then stop and
let the runner call you again.

Step N means: append one line to runner-test.txt reading

    step N done at <current date and time>

Rules:
- Never do more than one step in a single run, even if it seems trivial.
- After finishing your step, record it under Completed in the state file and
  write the next step under Next steps.
- Keep TASK_STATUS: IN_PROGRESS until step 5 is done. Only after step 5 is
  written to runner-test.txt, set TASK_STATUS: COMPLETE on the first line of
  the state file.
- If runner-test.txt does not exist yet, create it.
