# `lmi schedule` — dos and don'ts

`lmi schedule` runs Claude Code unattended: it loops `claude -p` in the
foreground, and the only memory carried between iterations is a state file.
Nobody is watching the terminal, so every mistake below is one that nobody
catches while it is happening.

The failures worth fearing here are not crashes. They are the runs that report
`exit 0`, `4 run, 4 succeeded, 0 failed`, and have done nothing useful — or
something you did not want. Those are marked **silent** below.

Hebrew version: [`schedule-dos-and-donts.he.md`](schedule-dos-and-donts.he.md).

---

## 1. The task you hand it

### ✅ Do: give it a done-condition it can actually test

The runner stops early the moment line 1 of the state file reads
`TASK_STATUS: COMPLETE`. That is your only stop condition other than running out
of iterations, so the task has to contain something Claude can check itself.

```bash
lmi schedule "Add type hints to every function in src/parsers/.
Done when: mypy --strict src/parsers/ exits 0 and the test suite still passes.
Run both before writing TASK_STATUS: COMPLETE." -i 10 -c 6
```

"Done when" plus a command that returns a verdict is the whole trick.

### ❌ Don't: write an open-ended prompt

```bash
lmi schedule "Improve the code quality of this project" -i 5 -c 20
```

There is no state in which this is finished, so `TASK_STATUS: COMPLETE` never
appears, all 20 iterations run, and each one re-reads a codebase the previous
one already changed. You pay for 20 calls and get 20 rounds of churn.

### ✅ Do: bound the scope to something one iteration can dent

The prompt tells Claude to work in chunks and stop when a meaningful piece is
done. That only works if a chunk exists. "Migrate `src/api/users.py` to the new
client" has chunks; "migrate the codebase" does not.

### ❌ Don't: ask a question

The prompt header tells Claude never to ask and never to wait for
confirmation — because with `-p` there is nobody to answer. A task phrased as
"decide whether we should..." wastes iterations on deliberation that ends up in
the state file instead of in your repository.

---

## 2. Permissions — the part that can bite hardest

The runner always passes `--allowed-tools=Edit,Write`. Anything you add with
`-f` is appended **after** that, so `-f` widens the blast radius and never
narrows it.

### ✅ Do: leave the default alone unless you have a specific need

`Edit,Write` lets it change files in the working directory. For most tasks that
is the entire job.

### ❌ Don't: hand it a shell unattended without thinking it through

```bash
lmi schedule "..." -f "--allowed-tools=Bash" -i 5 -c 12
```

Twelve unsupervised iterations with shell access, deciding on their own, with
nobody to say no. If a task genuinely needs a command, scope it as tightly as
your tooling allows and prefer one that cannot destroy anything — a test runner
or a linter, not a package manager or `git push`.

### ❌ Don't: use `--dangerously-skip-permissions` because the run kept stopping

The flag name is the warning. Unattended, it removes the last thing standing
between a bad decision and your filesystem. If iterations are stalling on
permissions, narrow the task instead.

### ✅ Do: assume every iteration is a fresh, slightly different opinion

Each iteration is a new session that only knows what the state file says. It
will not remember the caution the previous one showed.

---

## 3. Loop shape: `-i` and `-c`

They are mutually required — either both or neither, each alone exits 2. There
is deliberately no unlimited mode.

### ✅ Do: prove the task with a tiny run first

```bash
lmi schedule "<task>" -i 0 -c 1       # one iteration, no wait
```

Read the state file. Did it understand the goal? Is `## Next steps` sensible?
Only then scale up. One iteration costs almost nothing; twelve wrong ones cost
twelve times as much.

### ✅ Do: use `-i` as breathing room against rate limits

`-i 10` means ten minutes *after `claude` exits*, not ten minutes between
starts — iterations can never overlap. On a plan with tight limits, spacing runs
out is what keeps you from being throttled halfway through.

### ❌ Don't: pair `-i 0` with a large `-c` on a long task

```bash
lmi schedule "<task>" -i 0 -c 30
```

Thirty back-to-back sessions with no gap. If you hit a quota wall at iteration
6, the remaining 24 still run, each failing fast, and the log fills with
`[QUOTA]` while the loop grinds on. The runner is built never to abort on a
failed call — that is deliberate, and it is also why an unattended run can burn
through a lot of nothing.

### ✅ Do: read `-c` as a budget ceiling, not a target

The loop stops early on `COMPLETE`. Sizing `-c` generously is fine *if* the
task has a real done-condition; without one, `-c` is exactly what you will
spend.

---

## 4. The state file

This is the run's whole memory. Most of the silent failures live here.

### ❌ Don't: put it anywhere under `.claude/` — **silent**

Claude Code treats everything under `.claude/` as sensitive and refuses to Write
or Edit it. With `-p` there is nobody to approve the refusal. The result:
the run reports success, every iteration is counted as succeeded, and the state
file is still the untouched template — so iteration 1 repeats forever and
`TASK_STATUS: COMPLETE` can never appear.

The default (`<workdir>/run-claude-state.md`) is fine. If you use `-s`, keep it
out of `.claude/`.

### ❌ Don't: put it on a Windows network share — **it looks like contention**

The lock file is created next to the state file, and Windows cannot byte-range
lock a file on a share. The attempt fails with "Invalid argument", which is
indistinguishable from another run holding the lock, so you get **exit 3**,
"another run is working on this state file", with nothing else running.

`lmi` refuses a UNC state file up front and tells you the escape hatch: keep the
working directory on the share and put the state file on a local drive with
`-s C:\lmi\run-claude-state.md`.

### ✅ Do: read line 1 before believing the summary

Only the **first line** is tested for `TASK_STATUS: COMPLETE`. That is
deliberate: Claude reliably restates the protocol sentence *"write TASK_STATUS:
COMPLETE on the first line only when…"* inside the state file, so a whole-file
search would match that prose and stop the loop after one iteration.

For you, the practical version is: `head -1 run-claude-state.md`. If it says
`IN_PROGRESS` and the run reported success, the run ended because it ran out of
iterations, not because the task is done.

### ✅ Do: use `-r` when you mean "carry on"

Without `-r`, an existing state file is backed up and a fresh template written —
the run starts from zero. With `-r` it continues from what is there. If you are
resuming yesterday's work and forget `-r`, you get a correct-looking run that
redoes everything.

### ✅ Do: hand-edit the state file between runs when it has drifted

It is just Markdown. If `## Next steps` has gone off course, fix it before the
next run — that is cheaper than arguing with it through the prompt. Writing
`TASK_STATUS: COMPLETE` on line 1 yourself is a legitimate way to stop a loop.

---

## 5. Where it runs

### ✅ Do: run on a branch, with everything committed

```bash
git switch -c unattended/type-hints
git status          # clean
lmi schedule "<task>" -d ~/work/myrepo -i 10 -c 6
```

Unattended edits are much easier to judge as a diff, and trivial to throw away.

### ❌ Don't: point `-d` at a directory with uncommitted work you care about

`Edit,Write` is enough to overwrite it, and there is no undo. The same goes for
running in `$HOME` or anywhere with unrelated files in reach.

### ❌ Don't: assume it inherits your shell's environment for auth

It runs `claude` with the working directory you gave it. If your credentials or
proxy settings come from a shell profile that a scheduled task does not load,
every iteration fails identically.

---

## 6. Prompt files and encoding

### ✅ Do: keep prompt files UTF-8

A prompt file must be UTF-8, or carry a UTF-16 BOM. Both are detected.

### ❌ Don't: save a Hebrew prompt as ANSI / Windows-1255 — **undetectable**

ANSI carries no byte-order mark, so it cannot be told apart from UTF-8 by
construction. `lmi` does not try to guess, and it is not going to warn you. In
Notepad, "Save as → UTF-8"; in VS Code, the encoding is in the status bar.

### ✅ Do: prefer a prompt file over a long inline prompt

A file is versionable, reviewable, and does not need shell quoting. Long inline
prompts also once triggered an `ENAMETOOLONG` crash because a 143-character
Hebrew sentence is over 256 bytes with no slash in it — that is fixed, but a
file is still the better habit.

---

## 7. While it runs, and afterwards

### ✅ Do: search the log for `[ERROR]` and `[QUOTA]`

```bash
grep -E '\[ERROR\]|\[QUOTA\]' run-claude-*.log
```

A failing `claude` call never fails the runner — it is logged, the iteration is
counted as failed, and the loop continues. That is the right behaviour for an
unattended tool and it means the log is the only place the failures surface.
`[QUOTA]` specifically means the output looked like a quota, rate-limit or
overload problem; check your usage before trusting the result.

### ❌ Don't: read "N succeeded" as "the work is done"

"Succeeded" means `claude` exited 0. It does not mean anything changed, and it
does not mean the change was right. The state file and `git diff` are the real
report.

### ✅ Do: know what the exit codes mean

| Code | Meaning |
|---|---|
| 0 | the loop finished — either `COMPLETE` on line 1, or `-c` iterations ran |
| 1 | a `claude` call failed |
| 2 | usage error: bad arguments, a prompt file that is not UTF-8, an unusable path |
| 3 | another run holds the lock on this state file |
| 4 | a bug in `lmi` |

Exit 3 with nothing else running used to mean a state file on a share; that is
now refused up front, so today it usually means what it says.

### ✅ Do: let the lock do its job

A second instance on the same state file is blocked deliberately. If you want
two tasks running at once, give each its own working directory or its own `-s`.

---

## 8. The short version

**Do**

- Give it a done-condition it can verify itself, and say so in the prompt.
- Trial-run with `-i 0 -c 1` and read the state file before scaling up.
- Keep the default `--allowed-tools=Edit,Write`.
- Run on a branch with a clean tree.
- Check `head -1` of the state file and `grep [ERROR]` the log afterwards.

**Don't**

- Write an open-ended task and give it 20 iterations.
- Widen permissions with `-f` because it kept stopping.
- Put the state file under `.claude/` or on a network share.
- Save the prompt file as ANSI.
- Believe "N succeeded" without looking at the diff.
