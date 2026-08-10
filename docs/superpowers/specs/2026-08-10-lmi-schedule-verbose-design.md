# lmi — design (`lmi schedule -v`, watching a run while it runs)

**Date:** 2026-08-10
**Status:** designed, not implemented.

Today `lmi schedule` is opaque while it works. You start it and wait. The log
gets claude's final text after each iteration ends, and nothing before that —
so a twenty-minute iteration is twenty minutes of a blank terminal, and the
prompt lmi actually sent is never recorded anywhere at all: it is composed,
written to a temp file, piped to claude on stdin, and deleted with the temp
directory when the run finishes.

`-v` fixes both halves. It logs the prompt, and it renders claude's activity
into the log **as it happens**.

---

## 1. Goal and non-goals

**Goal.** `lmi schedule -v` makes an unattended run observable: you can see the
exact document lmi asked claude to work from, and watch which tools claude runs
against which files while the iteration is still going.

**Non-goals.**

- **No change to what claude receives.** The document piped to claude under
  `-v` is byte-identical to the one piped without it. Verbose mode is
  write-only — the log is not in the prompt, is not referenced by the prompt,
  and no iteration is told it exists. It costs disk and scrollback, never
  tokens.
- **No verbosity levels.** One boolean. `-vv` and `--verbose=2` are a
  configuration surface nobody asked for, and `-f` already exists for anyone
  who wants to tune claude's own output further.
- **No new default.** Runs without `-v` behave exactly as they do today, down
  to the argv and the `--- claude output ---` fence text. This feature adds a
  path; it does not modify the existing one.
- **No log rotation, no size cap, no separate verbose log file.** `-l` already
  chooses where the log goes.
- **No pty.** If claude block-buffers when its stdout is not a terminal,
  lines arrive in chunks. Allocating a pty to defeat that is a large change
  with platform-specific behaviour, and today's code writes to a file — equally
  not a terminal — so streaming is never *worse* than the status quo.
- **No new runtime dependencies.** Standard library only, Python 3.9 floor,
  as everywhere else. `json` is stdlib.

---

## 2. Command surface

```
lmi schedule <prompt> ... [-v]
```

One new flag on schedule's subparser, `store_true`, dest `verbose`. `cli.py` is
not edited — the flag belongs to the command, like every other.

`Config` gains one field:

```python
verbose: bool = False
```

placed last, after `resume`, so the existing positional construction in
`build_config` and the `make_cfg` test factory keep working unchanged.

**`-v` is one switch, not a pair.** Passing `-v` is the whole of what a user
does; they never additionally need `-f "--verbose"`. That is the requirement
this feature was asked for under, and §3 is how it is met.

---

## 3. What `-v` puts on claude's command line

Today:

```python
[claude, "-p"] + DEFAULT_FLAGS + ["--add-dir", str(state_path.parent)] + cfg.user_flags
```

With `-v`, two flags are inserted after `DEFAULT_FLAGS` and before
`cfg.user_flags`:

```
--output-format stream-json --verbose
```

Position is load-bearing and follows the existing rule: lmi's flags go first so
that `-f` composes after them, exactly as README already promises for
`--allowed-tools` and `--add-dir`.

Both flags were confirmed against the installed CLI (`claude --help`):
`--output-format` takes `text | json | stream-json` and works only with
`--print`; `--verbose` is its own flag — claude's `-v` is `--version`, which
does not constrain lmi's flag namespace.

`--verbose` is included because `--output-format stream-json` in print mode has
historically required it. Whether it adds anything on top of stream-json is
§10's first open question, and is checked by a real run rather than assumed.

### 3.1 The `--output-format` collision, which must not be silent

`-f` flags are appended last, and claude's parser takes the last occurrence of
a repeated option. So:

```
lmi schedule task.md -i 30 -c 3 -v -f "--output-format json"
```

yields `--output-format stream-json ... --output-format json`, claude emits one
JSON object at the end instead of a stream, and the renderer is handed
something it cannot parse. The log goes quiet, the iteration still succeeds,
and the run exits 0 — the exact failure shape CLAUDE.md section 3 is a
catalogue of.

Two guards, both of them:

1. **Refused up front.** `config.py` rejects `-v` together with any
   `--output-format` token in `-f`, exit 2, naming both flags and saying that
   `-v` sets the output format itself. The check is a scan of the
   `shlex.split` result for a token equal to `--output-format` or beginning
   `--output-format=`. This is validation, not flag rewriting: lmi still never
   edits or filters a user's `-f`, it only declines a combination it cannot
   honour.
2. **Degrades visibly.** Independently, the renderer treats a line that is not
   a JSON object as a signal to warn once — `[WARN] claude is not emitting
   stream-json - logging its output verbatim` — and pass everything through
   raw from then on. Guard 1 cannot cover a future claude version that changes
   the format on its own; guard 2 can, and turns the silent case into a
   visible one.

**Duplicate `--verbose` stays allowed.** `-f "--verbose"` alongside `-v` puts
the flag on the line twice, which is harmless: it is a boolean, so the second
occurrence is idempotent. The distinction against `--output-format` is exactly
that one is idempotent and the other is last-wins — not a general policy of
deduplicating flags, which would require lmi to know claude's flag grammar and
would risk silently dropping something the user asked for.

### 3.2 The header

`_log_header` gains one line, in verbose runs only:

```
Verbose   : on - prompts logged, claude activity rendered live
```

The `Flags     :` line already prints `argv[1:]`, so the two new claude flags
appear there without further work. The new line exists because the *lmi-side*
behaviour — prompt logging, live rendering — is not visible from argv.

---

## 4. Prompt logging

Every iteration lmi composes one document with four parts:

| | Part | Changes between iterations? |
|---|---|---|
| ① | Header — "Unattended automated run", iteration label, paths | only the iteration label and start time |
| ② | The 7-rule state protocol | never — it is a module constant |
| ③ | `## CURRENT STATE` — the state file, inlined inside a computed fence | **yes** — it is the only memory between iterations |
| ④ | `## TASK` — the user's prompt text | never — read once before the loop |

**Iteration 1 logs the whole document. Every later iteration logs ③ only**,
under a header saying the rest is unchanged:

```
--- prompt sent to claude (full, 62 lines) ---
...
--- end of prompt ---
```

```
--- state sent to claude (header, protocol and task unchanged from iteration 1) ---
...
--- end of state ---
```

Nothing is lost. ② and ④ are provably identical to iteration 1's — ④ is read
once by `read_prompt_source` before the loop and ② is `prompt.HEAD`. ①'s two
varying facts, the iteration label and the start time, are already on the
`--- iteration N of M started ... ---` line immediately above.

The alternative, logging all four parts every iteration, was considered and
rejected: on a 50-iteration run it repeats roughly 2,250 lines of identical
boilerplate, which is the difference between a log you watch and a log you
scroll past.

### 4.1 "Iteration 1" means the first one that got that far

Keying off `n == 1` is wrong. If iteration 1 dies before `prompt.compose` — a
vanished temp workspace, a full disk — it is recorded as skipped by
`_iteration_rc` and the loop carries on, and iteration 2 would then log ③ alone
having never logged the full document once. The claim in its header would be a
lie about text that was never written.

So the state is "has the full prompt been logged yet", not "which iteration is
this". A small object owns it, created once in `_run_locked` and passed down
beside `tmp_dir`:

```python
class PromptLog:
    """Logs the composed prompt: in full the first time, ③ only after."""
    def __init__(self, verbose):
        self.verbose = verbose
        self.full_done = False

    def emit(self, log, composed, state_body):
        ...
```

`full_done` is set only after the full write has been emitted. A class rather
than a threaded boolean because the flag has to survive across three call
frames and come back mutated; a class states that plainly where an out
parameter would not.

`emit` is a no-op when `self.verbose` is false, so the call site in
`_one_iteration` is unconditional and there is no `if cfg.verbose` scattered
through the loop.

---

## 5. The streaming path

Today's invocation captures to a file and replays it after the fact:

```python
completed = subprocess.run(argv, stdin=prompt_fh, stdout=out_fh,
                           stderr=subprocess.STDOUT, cwd=str(cfg.work_dir))
output = out_path.read_text(encoding="utf-8", errors="replace")
for line in output.splitlines():
    log.line(line)
```

Verbose replaces the redirect with a pipe and a read loop:

```python
with open(prompt_path, "rb") as stdin_fh, \
        subprocess.Popen(argv, stdin=stdin_fh, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT,
                         cwd=str(cfg.work_dir)) as proc:
    quota = _pump(log, _decoded_lines(proc.stdout), render)
rc = proc.returncode
```

Four details, each of them a decision rather than a default:

- **`_decoded_lines`** is a one-line generator over the binary pipe —
  `for chunk in pipe: yield chunk.decode("utf-8", "replace").rstrip("\r\n")`.
  Iterating a `BufferedReader` yields each line as soon as it is complete, so
  the generator is what makes the loop live rather than buffered.
- **Bytes, decoded `utf-8` with `errors="replace"`** — not text-mode `Popen`.
  Text mode decodes through the locale codepage, which on the site's Windows
  machines is not UTF-8, so the two paths would disagree about the same bytes.
  `errors="replace"` matches what `read_text` does today: a half-written line
  must never end an iteration.
- **`Popen` as a context manager**, so the pipe is closed and the child waited
  on even if the loop raises. Without it, an exception mid-stream leaves claude
  running while `_iteration_rc` records a skip and the loop moves on.
- **`stderr=subprocess.STDOUT`**, unchanged, so claude's diagnostics stay
  interleaved in the order they happened.
- **No `out-N.txt` in verbose mode.** The temp directory still holds
  `prompt-N.txt`; there is nothing to capture to a file when the lines are
  consumed as they arrive.

### 5.1 One pump for both paths

The two paths differ only in where lines come from. Everything after that is
shared:

```python
def _pump(log, lines, render=None):
    """Log each line as it arrives. True if any smells like a quota problem."""
    quota = False
    for raw in lines:
        if QUOTA_RE.search(raw):
            quota = True
        log.line(render(raw) if render else raw)
    return quota
```

Non-verbose passes `output.splitlines()` and no renderer, which is exactly
today's behaviour. Verbose passes the live decoded pipe and the renderer from
§6.

**The quota scan reads the raw line, never the rendered one.** Under
stream-json the quota wording lives inside a JSON error or result event, and a
renderer that summarised such an event without carrying its message through
would silently disable the `[QUOTA]` tag. Scanning before rendering makes that
impossible regardless of how the renderer evolves.

Moving the scan from whole-text to per-line is behaviour-identical for the
existing path: every alternative in `QUOTA_RE` is a within-line phrase, and `.`
does not cross newlines, so nothing that matches today stops matching.

The `[QUOTA]` block itself is emitted after the pump returns, from the same
code as today.

### 5.2 Fence text

Non-verbose keeps `--- claude output ---` / `--- end of claude output ---`
verbatim; changing it would be a gratuitous diff in the path this feature is
not touching. Verbose uses `--- claude activity ---` /
`--- end of claude activity ---`, because what is between them is rendered
events, not claude's output.

---

## 6. The renderer

New module, `lmi/commands/schedule/stream.py`. It stays inside the command
rather than moving to `core/`: it encodes claude's event schema, which is this
command's concern, and `core/` earns a module when a second caller appears, not
on the guess that one might.

One public class, because rule 2 below needs to warn *once* and therefore needs
somewhere to remember that it has:

```python
class Renderer:
    """Turns one stream-json line into one log line."""
    def __init__(self, log):
        self.log = log
        self.warned = False

    def render(self, raw_line) -> str:
        ...
```

`_one_iteration` builds one per iteration and passes the bound
`renderer.render` as `_pump`'s `render` argument, which keeps `_pump` ignorant
of both JSON and the logger.

Raw JSON line in, one log line out. Recognised shapes, and what each becomes:

```
[claude] init    model=claude-opus-5 session=a3f2b1c8 cwd=/home/shaharz/repo/lmi
[claude] text    I'll take lmi/core/ one module at a time.
[claude] tool    Bash   python3 -m pytest tests/ -q
[claude] result  Bash   420 passed, 1 skipped in 1.74s
[claude] done    ok - 11 turns, 108.4s, 31.2k in / 4.1k out
```

Three rules govern it:

1. **An unrecognised event type renders as one line, never a crash and never a
   dump**: `[claude] event   <type>`. A schema addition must degrade to one
   uninformative line, not to a traceback that `_iteration_rc` turns into a
   skipped iteration.
2. **A line that is not a JSON object** triggers §3.1's guard 2: warn once,
   then pass everything through verbatim.
3. **Tool inputs are summarised to their most identifying field**, truncated —
   `file_path` for Read/Edit/Write, `command` for Bash, `pattern` for Grep,
   nothing when none is recognised. **The `content` field is never rendered.**
   A `Write` of a 400-line file would otherwise put that file into the log
   twice a minute, which defeats the readability this feature exists for.

`--include-partial-messages` is deliberately *not* passed by `-v`: it streams
text token by token, which is maximally live and minimally readable afterwards.
It remains available through `-f` for anyone who wants it, which is what `-f`
is for.

---

## 7. What must not regress

- **Invariant 3** — nothing waits for a keypress. The prompt is still fed on
  stdin from a file; the read loop blocks on a pipe, not on a terminal.
- **Invariant 2** — a failing claude call must not fail the runner. `Popen`
  plus `returncode` returns a non-zero exit exactly as `check=False` does; the
  exception half stays with `_iteration_rc`, whose `except LmiError: raise`
  clause must remain first (regression 12).
- **Regression 3** — the state file goes through the same BOM-aware decoder, so
  what `check_complete` reads and what `PromptLog` logs still agree.
- **Regression 11** — the computed `## CURRENT STATE` fence is unchanged. Note
  that a state body containing a fence is now also written into the log; the
  log is not a markdown document being parsed by anything, so no fence
  computation is needed there.
- **Non-verbose argv is byte-identical to today's**, which is the cheapest
  possible statement that this feature cannot break existing runs.

**One new entry for CLAUDE.md section 3**, since it is silent-class:
`-v` with an `--output-format` in `-f` is refused, and a non-JSON line warns
and falls back to verbatim. Inverted, the log goes quiet and the run reports
exit 0 — nothing afterwards distinguishes "claude did nothing worth showing"
from "lmi could not read what claude said".

---

## 8. Testing

`python3 -m pytest tests/ -q` after every change, as always.

**Config** — `-v` sets the field; absent leaves it `False`; `-v` with
`-f "--output-format json"` is exit 2 and the message names both flags;
`-f "--output-format=json"` is caught too; `-f "--verbose"` with `-v` is
accepted.

**argv** — `--output-format stream-json --verbose` present with `-v` and
positioned before the `-f` flags; argv without `-v` byte-identical to the
current expectation.

**Prompt logging** — iteration 1's log contains the protocol text and the task
text; iteration 2's contains the state body but not the protocol text; the
iteration-2 header claims "unchanged from iteration 1" only when a full prompt
really was logged. That last one takes a fixture where iteration 1 raises
before `compose` — it is §4.1's bug, and the test is the only thing that keeps
the header honest.

**Renderer** — one test per recognised event type; an unknown type yielding one
`[claude] event` line; a `Write` event whose `content` is 400 lines yielding
one line that does not contain the content; a non-JSON line producing the
`[WARN]` once and verbatim passthrough after.

**Behaviour under verbose** — `[QUOTA]` still fires when the wording is inside
a JSON event; a non-zero exit still counts as a failed iteration and the loop
continues; no `out-*.txt` is created, which is what proves the streaming path
was taken.

**Liveness** — the one test with a timing element, and the only one that can
tell live from buffered. `fake_claude` gains a mode where it prints a line,
waits (bounded, ~5s) for a marker file, then prints a second line and exits.
The test makes `Logger.line` create that marker when it sees the first line.
Under capture-then-dump the marker never appears, the fake gives up, and the
second line is missing — red. The bounded wait means a regression fails
cleanly instead of hanging the suite.

Tests pinning §3.1 and §4.1 are marked `MANDATORY` in their docstrings, per the
existing convention for silent failures.

---

## 9. Documentation

- **README** — `-v` row in the flags table; a short verbose section with an
  example of the rendered output; the recommendation to pair it with `-l`
  outside the working directory, since a verbose log contains claude's own
  prior output and sits where claude works by default; the note that `-v`
  passes `--verbose` for you.
- **CLAUDE.md** — `stream.py` in the architecture listing; the new section 3
  entry from §7.
- **`tests/test_docs.py`** — a check that README documents `-v`, matching how
  that module already guards the three silent keys.
- **`docs/verbose-log-example.md`** — the working document this design came
  from. Fold its example into README's verbose section and delete it, rather
  than leaving two descriptions of the same output to drift apart.

---

## 10. Open questions, to be settled by a real run

Neither blocks implementation; both are recorded so they are not quietly
assumed.

1. **Does `--verbose` add anything on top of `--output-format stream-json`?**
   It is passed because stream-json in print mode has historically required it,
   and a duplicate boolean is harmless either way. If a real run shows it
   changes nothing and is not required, it can be dropped from the pair — a
   one-line change, and §3.1's collision guard is unaffected.
2. **Does claude block-buffer its stdout when it is a pipe?** If it does, the
   rendered lines arrive in bursts rather than smoothly. Nothing in this design
   changes if so, but README should not promise smoothness that the CLI does
   not deliver.

Both belong in README's existing real-run checks section, which already records
that regressions 1 and 2 were found by real runs rather than by tests — as this
feature's whole point is behaviour a fake CLI cannot exhibit.
