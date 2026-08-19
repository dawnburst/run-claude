# lmi — design (`lmi schedule`, one session across the intervals)

**Date:** 2026-08-19
**Status:** designed, not implemented.

Today every iteration of `lmi schedule` is a **new claude session**. The only
memory carried across an interval is the state file, inlined into the next
prompt under `## CURRENT STATE`. That is deliberate and it works, but it is a
summary: whatever claude worked out and did not write down is gone the moment
the iteration ends.

The requirement is that a run keeps one session across its intervals. An
iteration that ends without finishing the task — most sharply, one cut short by
a usage limit — is continued by the next interval **with the context it already
had**, not with a fresh session reading a summary of it.

The state file does not go away. It becomes the second of two memories, and it
is the one that survives when the session cannot be resumed.

---

## 1. Goal and non-goals

**Goal.** `lmi schedule -i 60 -c 3 "<task>"` runs one claude session across all
three iterations. Iteration 2 resumes iteration 1's session; iteration 3 resumes
that same session. If iteration 1 died on a quota limit, iteration 2 picks up
its context anyway. With `-r`, a run restarted the next day resumes the session
the previous run left behind.

**It works identically in both backends.** `cli` and `sdk` are driven the same
way, through the same handle, decided by the runner. Parity is a requirement,
not an aspiration: items 40 and 43 are both cases of one backend being quietly
less capable than the other in a way no outcome revealed.

**Non-goals.**

- **No change to the prompt.** The composed document is what it is today:
  header, protocol, inlined `CURRENT STATE`, task — every iteration, resumed or
  not. A shorter continuation prompt would be a second prompt shape to test,
  and the fresh-session fallback in §7 would have to switch back to the full
  one. The state file stays authoritative, which is what makes that fallback a
  fallback rather than a downgrade.
- **No user-supplied session id.** lmi mints it. A flag for it is a
  configuration surface nobody asked for, and it would let two runs share one
  session by accident.
- **No forking, no session stores, no compaction management.** `fork_session`
  is never set (§9), the SDK's `session_store` is not used, and a session that
  auto-compacts is claude's business — the state file is why that is survivable.
- **No cross-machine or cross-directory transfer.** claude's session store is
  keyed by working directory (verified: `~/.claude/projects/<escaped cwd>/`), so
  a session is resumable from the `-d` that created it and nowhere else. §6
  detects the mismatch and says so rather than pretending.
- **No new runtime dependency.** `uuid` and `json` are stdlib; the Python 3.9
  floor and the standard-library-only rule are unchanged. The `sdk` extra's
  floor moves (§9), which is the one packaging consequence.
- **No retry loop.** At most one extra claude call per iteration, on exactly one
  condition (§7). Retry policy beyond that is not part of this.

---

## 2. Command surface

```
lmi schedule <prompt> ... [--no-session]
```

Session continuity is **on by default**. One new flag turns it off, long form
only — `-r`, `-c`, `-s`, `-i`, `-d`, `-l`, `-f`, `-t` and `-v` are all taken,
and a single letter for an opt-out nobody types often is not worth the
collision risk.

```python
parser.add_argument(
    "--no-session", dest="session", action="store_false", default=None,
    help="do not keep one claude session across iterations; each iteration "
         "starts fresh and carries only the state file",
)
```

`default=None` rather than `True`, so "the operator asked for it off" is
distinguishable from "nothing said anything" and the precedence rule in §3 has
something to read.

`Config` gains two fields, appended after `mode_source` so the existing
positional construction and the `make_cfg` factory keep working:

```python
session: bool = True
session_source: str = backend.DEFAULT_SOURCE
```

The sidecar's path is **not** a `Config` field. It is resolved at run time by
`paths.py`, like the state file, the log and the lock, none of which are on
`Config` either — `Config` carries what the operator asked for, `paths.py`
turns that into places on disk.

---

## 3. The switch, and where it is configured

Machine-level configuration goes in the `schedule` section of the resolved
`lmi.json`, beside the backend it already carries:

```json
{
  "schedule": {
    "mode": "sdk",
    "session": false
  }
}
```

Read by `backend.py`, which is already the one place the `schedule` section's
vocabulary lives, and for the same reason: `lmi config schedule` will want to
report and set it, and two spellings of one key is one command writing a value
another refuses.

- `backend.SESSION_KEY = "session"`, `backend.SESSION_DEFAULT = True`.
- `backend.resolve_session(explicit_config)` → `(bool, source)`, mirroring
  `resolve()`. Discovery is `core_config.find_optional`'s, unchanged.
- **Absent is not null.** The `_MISSING` sentinel already in that module is
  reused: an absent `session` key means the default, `"session": null` is a
  value the operator wrote and is exit 2. This is the same rule as
  `template._validate`, `fragment._validate` and `of_document`, in its fifth
  home. A non-boolean (`"true"`, `1`, `"off"`) is exit 2 too, naming the file —
  the mode's `parse()` refuses near misses rather than guessing, and a boolean
  has even less to guess about.

**Precedence: the flag beats the config file beats the default.** `--no-session`
is a command-line statement about this run and must win; there is only one sane
order here. CLAUDE.md's note that `schedule` deliberately has no `--mode` flag
is not contradicted — that flag was refused because a *backend* chosen by
neither the file nor the flag is unreadable afterwards, and the answer here is
the same one: whatever wins is named in the header (§8), with its source.

**`lmi config schedule --session` is deliberately not part of this change.**
The key is *read* here and nowhere written: a site that wants continuity off
everywhere hand-edits the `schedule` section, the same way it would any other
key lmi does not have a subcommand for. Adding a writer means a second key
under `_confirm_it_wins` (item 39) and a second thing for `lmi install claude`
to consider, which is a change to another command and belongs in its own one.
The reading side is worth having now because `--no-session` on every invocation
of an unattended scheduled job is a footgun a machine-level key removes.

---

## 4. The handle, and the file it lives in

A new module, `lmi/commands/schedule/session.py`. It owns the whole concept, so
that neither backend and neither of the two commands that write config learn
what a session id is:

```python
NAME_SUFFIX = ".session.json"

class Handle(NamedTuple):
    id: str          # the uuid4 lmi minted, or the one read back from disk
    resuming: bool   # False on a fresh mint: pass --session-id, not --resume
    created: str     # when the id was first minted, for the header
```

**The id is minted by lmi, before the first call.** `uuid.uuid4()`, rendered in
the canonical hyphenated form because `claude --session-id` requires a valid
UUID (verified on 2.1.235: `Error: Invalid session ID. Must be a valid UUID.`).
Minting rather than observing is mechanism A of the three considered, and the
reason it is the only workable one is short: without `-v` the CLI backend logs
claude's plain text output, which contains no session id anywhere, so observing
one would mean forcing `--output-format stream-json` on a non-verbose run —
which is item 26's bug arriving from the other side. Minting also means the
handle exists *before* the call, so an iteration killed mid-flight still leaves
a resumable id on disk.

**The sidecar** is `<state file>.session.json` — `run-claude-state.md.session.json`
for the default state file. Derived from the state file's name, not a fixed name
in the folder like `run-claude.lock`, because a directory can legitimately hold
two state files for two tasks and the session belongs to the *task*. It is
resolved by `paths.py` (`resolve_session(cfg, state_path)`), which means it
inherits the existing path rules for free: the writability probe, the UNC
refusal and the `-s`-inside-`.claude` warning all already apply to that
directory.

```json
{
  "session_id": "6f1c…",
  "created": "2026-08-19 14:02:11",
  "work_dir": "/home/op/project"
}
```

Read and written through `core/jsonfile.py`, never by hand, so the sidecar
inherits every guarantee that module exists for: the temp file born 0600 rather
than chmod-ed afterwards (item 20), `O_BINARY` so the write stays LF on Windows
(section 4 rule 4), the atomic replace, and the refuse-don't-discard read
(item 19).

`work_dir` is recorded because the session store is cwd-keyed: a run whose `-d`
has moved can be told *why* its resume is about to fail, before it fails
(§6). `created` is recorded because it is the one fact that reveals a session
older than the state file beside it, and §8 prints it.

**An unparseable sidecar is moved aside, not discarded and not fatal.**
`jsonfile.read` raises; the handler renames the file to
`<name>.<run_ts>.bak`, warns, and mints fresh. Refusing the run outright would
fail a whole overnight job over the *continuity* file while the actual memory —
the state file — was intact; overwriting it in place would discard whatever was
in there, which is what item 19 forbids. Moving it aside is the only option that
does neither.

**A sidecar that cannot be written is a `[WARN]`, not exit 2.** The lock lives
in the same directory and has already proved it writable, so this is exotic; if
it happens, the run keeps its handle in memory and continuity across *this*
run's intervals is unaffected — only tomorrow's `-r` loses it. That is a
degradation worth announcing and not worth aborting for, which is the same
weighing as item 36. The state file's write stays fatal (item 1); this is not
that file.

---

## 5. Backup-or-resume, in the same breath as the state file

`state.prepare` backs the state file up and writes a fresh template unless `-r`
was given, in which case it keeps it. **The sidecar follows the identical rule,
with the same `run_ts` stamp, in the same function call:**

| | state file | sidecar |
|---|---|---|
| no `-r` | backed up to `.<run_ts>.bak`, fresh template written | backed up to `.<run_ts>.bak`, fresh id minted |
| `-r` | kept | kept, and iteration 1 **resumes** it |
| `--no-session` | as above | **not read, not written, not backed up** |

The two must move together. Handled separately, a run without `-r` starts a
clean state file and resumes yesterday's session — two memories that disagree,
each of them plausible, and a run that exits 0 either way. That is new
must-not-regress item 56.

**`-r` with no sidecar is a fresh mint, not an error.** The state file is what
`-r` is about; a task resumed from a state file written before this feature
existed, or one whose sidecar was pruned, simply starts a new session and says
so in the header.

`--no-session` touches the sidecar not at all. It is an opt-out for a run, not a
reset of the machine's state: an operator who runs one iteration with
`--no-session` to test something must not thereby destroy the session a
`-r` run would have continued.

---

## 6. The seam

`prepare` / `describe` / `call` keep their shape. Two changes:

**`call` takes the handle.**

```python
def call(self, cfg, log, composed, state_path, tmp_dir, n, handle): ...
```

`handle` is `None` when session mode is off, which is the only branch either
backend takes on the subject. Neither backend decides anything about sessions:
the runner mints, persists, resumes and drops.

**`call` returns an `Outcome`, not a bare pair.**

```python
class Outcome(NamedTuple):
    rc: int
    quota: bool
    unresumable: bool
```

The third field is what §7 needs and what nothing else can supply: only the
backend sees the output that says the session is gone. A NamedTuple rather than
a mutated handle, so the seam stays a function of its arguments; `rc, quota =`
unpacking sites are updated, and the CLAUDE.md prose describing "the same
`(exit code, quota?)` pair" is updated in the same change — `tests/test_docs.py`
pins some of that wording, deliberately.

**CLI backend.** `prepare` builds the argv *up to* the session flags; the flags
are appended per iteration:

```
claude -p --allowed-tools=Edit,Write [-v flags] --add-dir <state dir> \
       (--session-id <uuid> | --resume <uuid>) <-f flags…>
```

`--session-id` on a fresh mint, `--resume` when resuming. The session flags go
**before** `cfg.user_flags`, because `-f` is appended last on purpose and that
ordering is load-bearing elsewhere; §10 is what stops a user's `-f` from
overriding lmi's own.

**SDK backend.** The same two values, as options:

```python
ClaudeAgentOptions(..., session_id=handle.id)          # fresh mint
ClaudeAgentOptions(..., resume=handle.id)              # resuming
```

`fork_session` is never set. A forked resume returns a *different* session id
each iteration, so the sidecar's handle would go stale while every iteration
appeared to resume correctly.

**The work-dir check, both backends, before the call.** If the sidecar's
`work_dir` is not `cfg.work_dir`, warn once naming both paths and why it
matters (the store is cwd-keyed). The resume is still attempted — lmi does not
know claude's store layout is the only path, and §7 handles the failure — but
the operator gets the reason in advance instead of a bare "no conversation
found".

---

## 7. When a resume fails — and when it must not be treated as one

Two failures look alike at the exit-code level and must not be conflated.

**A quota failure keeps the session.** An iteration that hit a usage limit has
an intact session; the next interval resumes it. This is the scenario the
feature was asked for, and discarding the handle on *any* non-zero exit would
throw the context away in exactly that case, while exiting 0 at the end of the
run. New must-not-regress item 54.

**Only the session actually being gone drops the handle.** Detected by
`backend.UNRESUMABLE_RE`, which joins `QUOTA_RE` in that module for the stated
reason that one pattern is what keeps the two backends equally loud. It matches
claude's own wording, verified on 2.1.235:

```
$ claude -p --resume 11111111-2222-3333-4444-555555555555 "hi"
No conversation found with session ID: 11111111-2222-3333-4444-555555555555
$ echo $?
1
```

Scanned over the same raw text `QUOTA_RE` is scanned over, in the same place —
`_pump` for the CLI backend, `_Sink._scan` for the SDK's messages and stderr —
so item 28's rule holds for it too: the scan reads what claude said, never what
the renderer kept.

**On a hit, the iteration retries once, fresh.** `[WARN]` naming the id and the
reason; mint a new id; write the sidecar; call again with `--session-id`. The
retry's `rc` is the iteration's `rc`; `quota` is **either attempt's** — the tag
under-reporting is the dangerous direction (item 43), and a limit reported by
the first attempt is no less real for the second having been made.

**The commonest way this fires is the scenario the feature was asked for.** If
iteration 1 hits the usage limit immediately, claude may never have created a
session at all. Then iteration 2 resumes an id that was written to the sidecar
but never existed, gets the wording above, warns, mints fresh and runs — one
wasted local lookup, no wasted interval, and the state file still carries
whatever iteration 1 managed. Continuity is lost in that case because there was
never any context to keep, which is the honest outcome and is visible in the
log rather than inferred.

Retrying in-iteration rather than next-interval is affordable precisely because
the failed resume costs nothing: the session lookup fails locally, immediately,
with no API call — which the probe above demonstrates. Without the retry the
interval is burnt doing nothing, which for `-i 60 -c 3` is a third of the run.

**Both new must-not-regress items live here.** Dropping the handle on quota is
item 54. Retrying more than once, or not dropping the handle at all, is item
55 — a handle that is never dropped means every remaining iteration fails
identically against a session that no longer exists, each failure looking like
claude's.

**SDK mode checks the id it got back.** `_Sink` already walks every message, and
the init message carries `session_id` (`stream.py` already renders it in its
init row). When it is present and differs from the requested id, warn naming
both: that is a session silently substituted for the one asked for, which is
otherwise invisible. CLI mode cannot do this — its plain output carries no id,
and changing that is item 26 — so this check is **SDK-only and documented as
such**, with the corresponding real-run check added to `docs/status.md`. An
asymmetric check that is declared beats a symmetric one that is faked.

---

## 8. What the log says

The header gains one line, in the block with `Backend`:

```
Session   : on - 6f1c… (new)
Session   : on - 6f1c… (resuming, created 2026-08-19 14:02:11)
Session   : off (--no-session)
Session   : off (from /home/op/.lmi/config.json)
```

This is item 33's rule applied to the second switch in the same command, and for
the identical reason: a resumed iteration and a fresh one both exit 0, neither
marks the state file, and cost and latency are the only other difference. Which
means the source is half the line — `on` alone does not say whether a file, a
flag or nothing at all chose it. New must-not-regress item 58.

Per-iteration, at most three new lines, and only when there is something to say:
the `[WARN]` for a work-dir mismatch (§6), the `[WARN]` + retry notice for a
dropped session (§7), and the `[WARN]` for an id mismatch in SDK mode. A healthy
run says nothing per iteration — the header already named the id.

---

## 9. The SDK floor, and one check before the lock

`ClaudeAgentOptions` must have both `session_id` and `resume`. Passing a keyword
a dataclass does not define is a `TypeError` on **every** iteration, which is
item 44's failure with a new field name: importable is not the same as able to
build its options.

Two halves, both required:

- **The floor moves, in both spellings at once.** The `sdk` extra's constraint
  in `pyproject.toml` and `install/sdk.REQUIREMENT` must stay one string —
  `tests/test_packaging.py` already pins their equality. The exact version is
  determined empirically during implementation, by inspecting an installed SDK
  for the two fields, and not guessed here.
- **`sdk.require()` checks the fields, once per run.** It already runs before
  the lock and before the header, which is exactly where a machine that cannot
  do this should be told: `dataclasses.fields(ClaudeAgentOptions)` must contain
  both names, or exit 2 naming the two ways out —
  `pip install "lmi[sdk]" --upgrade`, or `--no-session` to run without
  continuity on the SDK that is installed. Checked only when session mode is on,
  so an older SDK still runs everything it could run before.

`tests/commands/schedule/test_sdk_fake_shapes.py` grows the assertion that the
real dataclass has both fields, and keeps skipping rather than passing when the
extra is absent. That module is where item 43's lesson lives: a set of field
names is only as good as the last time somebody compared it against the
installed package.

---

## 10. `-f` collisions

While session mode is on, these tokens in `-f` are exit 2: `--resume`, `-r`,
`--continue`, `-c`, `--session-id`, `--fork-session` (and their `=value` forms).
The two short ones are *claude's* spellings, seen inside `-f`; lmi's own `-r`
and `-c` are unaffected and keep meaning the state file and the iteration
count.

The reason is item 46's, exactly: `-f` is appended last and the CLI takes the
last occurrence of a repeated option, so a user's `--resume` does not *add* a
flag, it silently replaces the one lmi is using to hold the run together — and
the log still reads clean. In SDK mode the same tokens fight `session_id` /
`resume` through `extra_args`, which the SDK also appends last.

The message names `--no-session` as the way to take the wheel: **with
`--no-session` these flags pass through untouched.** That is the escape hatch
for an operator who wants to drive resumption themselves, and it keeps this from
being lmi confiscating a flag. Refused, never dropped — a silently ignored `-f`
is the failure `-f` validation exists to prevent.

This is validation, not flag rewriting, and it is the same narrow shape as
`_reject_output_format`: six names known by name, only to decline them, no
grammar learned. New must-not-regress item 57.

---

## 11. Cost, and what the operator should expect

A resumed session replays a growing conversation. Iteration 3 of a long run
carries iterations 1 and 2 in its context, so input tokens per iteration grow
across a run — much of it cache-eligible, none of it free, and a `-c 10` run
costs more than the same run does today. A long enough session will auto-compact,
which is claude's business and survivable precisely because the state file is
still authoritative and still inlined.

This belongs in `docs/schedule.md` next to the feature, phrased as what it is: a
trade, made deliberately, with `--no-session` as the way out for a site that
would rather pay the summary's price than the transcript's.

---

## 12. New must-not-regress items (CLAUDE.md section 3)

Appended as 53–59; the list is never renumbered, because `tests/test_docs.py`
pins item 22 by name and several specs cite items by number.

53. **The session id is minted by lmi, never learned from claude's output.**
    Without `-v` the CLI backend logs plain text that carries no id, so
    observing one means forcing `--output-format stream-json` on a run that did
    not ask for it — item 26 from the other side. **Silent:** an observed-id
    design works perfectly under `-v` and silently loses continuity without it,
    which is how most unattended runs run.
54. **A quota failure must not discard the session.** The handle is dropped only
    on `UNRESUMABLE_RE`, never on a non-zero exit in general. **Silent:** the
    one scenario this feature exists for — a usage limit at iteration 1 —
    quietly becomes three unrelated fresh sessions, and the run still exits 0
    with three successes.
55. **The handle is dropped on exactly the failure that means it is gone, and
    the retry happens at most once.** Never dropping it means every remaining
    iteration fails identically against a dead session, each failure looking
    like claude's own; retrying without a bound turns one dead session into an
    unbounded call loop inside a single iteration.
56. **The sidecar is backed up or kept in the same breath as the state file.**
    One rule, `-r`, applied to both. **Silent:** a run without `-r` starts a
    clean state file and resumes yesterday's session, two memories disagreeing
    plausibly, exit 0 either way.
57. **`-f` may not carry the session flags while session mode is on.** Six
    names, refused with exit 2, `--no-session` named as the way to take over.
    **Silent:** `-f` is last and last wins, so the user's flag replaces lmi's
    and the log reads clean.
58. **The header names the session and what chose it.** Item 33's rule for the
    second switch in this command: both a resumed and a fresh iteration exit 0
    and neither marks the state file, so nothing else in an unattended run's
    only record distinguishes them.
59. **`fork_session` is never set, and the SDK's session fields are verified
    before the lock.** A fork returns a new id per iteration, so the sidecar
    goes stale while every iteration looks like a correct resume; an SDK without
    the two fields is a `TypeError` on every iteration, which is item 44 with a
    new field name.

---

## 13. Testing

Everything below runs against the existing fakes. No test may reach a real
`claude` (section 4 rule 3).

**`fake_claude` gains two knobs.** `FAKE_SESSION_GONE=<n>` makes the fake print
the verified unresumable wording and exit 1 when it is given `--resume` on call
*n*, which is what exercises §7's retry without a real session store.
argv is already recorded per call, so `--session-id` / `--resume` are asserted
from what the fixture already captures. The id-mismatch check of §7 is SDK-only
and so is tested against the **SDK fake**, whose init message is given a
`session_id` that differs from the requested one — `fake_claude` has no part in
it, and giving it one would test a path CLI mode does not have.

**Marked MANDATORY**, one per silent failure above:

- iteration 2 resumes iteration 1's id after iteration 1 **failed on quota**
  (item 54) — the scenario the feature was requested under, asserted on argv in
  CLI mode and on the options in SDK mode;
- a run without `-r` backs up the sidecar and mints a new id; with `-r` it keeps
  and resumes (item 56);
- an unresumable resume drops the handle, retries **once**, and the sidecar then
  holds the new id (item 55);
- each of the six `-f` tokens is exit 2 with session mode on, and passes through
  with `--no-session` (item 57);
- the header line is present, names the id, and names the source (item 58).

**Ordinary coverage:** the default is on with no config file; `schedule.session:
false` turns it off and names the file; `--no-session` beats the file; a
non-boolean and an explicit `null` are each exit 2; the sidecar round-trips; an
unparseable sidecar is moved aside and the run continues; an unwritable sidecar
is a `[WARN]` and the run continues with in-run continuity; a work-dir mismatch
warns before the call; `--no-session` leaves the sidecar's bytes untouched.

**`test_docs.py`** grows needles for the new user-facing facts, the way it
already does for the three silent keys: that the documentation spells
`--no-session` and `schedule.session`, and that item 54's rule is still stated
in CLAUDE.md — that one exists nowhere else and has no symptom when inverted,
which is the same argument that keeps the item-22 check in that module.

**Re-measure the suite count** and write the measured figure into CLAUDE.md
section 4.1 — measured, not adjusted by the number of tests believed added.
Both numbers: without the extra, and with `pip install -e ".[sdk]"`. Section 4.1
notes the second has been arithmetic for four consecutive changes; this change
touches the SDK's options, so it is the one to settle it in a venv.

**One real run, no credential.** The smoke test written up in
`docs/schedule.md` — two iterations, no valid credential, both backends — is
what found item 45, and this change alters what iteration 2 sends. Do it before
trusting any of this.

---

## 14. Documentation to update

- `docs/schedule.md`: the feature, the sidecar and where it lives, the `-r`
  interaction, the working-directory constraint, `--no-session`, the six refused
  `-f` flags, the cost note from §11, and the new header line in the Logging
  section.
- `docs/config.md`: `schedule.session`, beside `schedule.mode`.
- `docs/status.md`: what has actually been run, and the two checks only a real
  run settles — that a `--resume` iteration really does carry the earlier
  context, and the SDK id-mismatch warning.
- `README.md`: one line, since continuity changes what the command *is*.
- `CLAUDE.md`: section 2's file list (`session.py`), section 3's items 53–59,
  the `Outcome` change to the seam's description, and the re-measured counts.

---

## 15. Open questions

None blocking. Two things are deliberately left to implementation, both
empirical:

1. **The exact `sdk` extra floor** (§9), which is read off an installed SDK
   rather than guessed, and moves in both spellings at once.
2. **Whether the SDK's init message exposes `session_id` on the version at the
   floor** (§7's mismatch check). If it does not, the check is dropped rather
   than faked, and `docs/status.md` records that the id-substitution failure is
   unobserved in both backends — a declared gap, not a silent one.
