# lmi — design (scoped to `lmi config switch`)

**Date:** 2026-08-09
**Status:** designed, not implemented.

`lmi config switch` applies a partial `settings.json` fragment over Claude
Code's `~/.claude/settings.json`, changing only the keys the fragment names.
`lmi config switch origin` puts back the settings the machine had before the
first switch.

This is the third command in the skeleton `2026-08-03-lmi-schedule-design.md`
laid down. Nothing in `cli.py` changes. It is the first command to need code
that already lives inside another command's package, and section 6 is about
that.

---

## 1. Goal and non-goals

**Goal.** Move a machine between named Claude Code configurations — a gateway
and a direct endpoint, a large-context profile and a cheap one, one team's
marketplace set and another's — without hand-editing `settings.json`, and get
back to where you started with one command.

**Non-goals.**

- **Not an npm switcher.** The first draft of this request used
  `{"claude": {"registry": ...}}` as its example. That is lmi's *install*
  config shape, and `registry` there is the **npm** registry, written by
  `npm config set registry --global` into an npmrc. Claude Code's
  `settings.json` has no `registry` key. This command switches
  `settings.json` keys and nothing else; changing which Artifactory a machine
  installs from remains `lmi install`'s job.
- **No `lmi config status`.** `cat ~/.claude/settings.json` shows the state,
  and the switch prints what it changed. `CLAUDE.md` says not to add features
  that were not asked for.
- **No key removal.** A fragment sets and merges; it cannot delete. `null` is a
  value, not a tombstone.
- **No profile registry, no named profiles, no `list`.** A profile is a file
  you point at.
- **No env var.** Two ways to name a file: `--file`, or the default path.
- **No undo stack.** See section 5 — `origin` means pristine, not "one step
  back", and that was chosen deliberately over both alternatives.
- **No new runtime dependencies.** `dependencies = []` stays.

---

## 2. Command surface

```
lmi config switch                      # applies ./config/settings_switch.json
lmi config switch --file prod.json     # applies that file        (-f short)
lmi config switch origin               # restores the pristine settings.json
```

`config` is a normal command in the registry — `NAME`, `HELP`,
`add_arguments`, `run` — and builds its own nested subparser inside
`add_arguments`. `cli.py` keeps its single subparser level and learns nothing;
adding `switch` and any future `config` verb touches only this package.

**`origin` is a bare positional with `choices=["origin"]`. Paths only ever
arrive behind `--file`.** That is what removes the collision: a file called
`origin` cannot be mistaken for the keyword, and the keyword cannot be
shadowed by a file. No precedence rule is needed because the two never occupy
the same argument.

`lmi config` with no verb is **exit 2** with its own message — the three usage
lines above, raised as an `LmiError`, so `cli.main` prints it prefixed
`[ERROR]`. That is deliberately not argparse's bare sub-help, which `lmi` with
no command prints: a message this package owns is a message a test can assert
on, and the guard behind it is otherwise unpinnable. Without it the command
falls through to the default fragment search, which also exits 2 — so a
code-only assertion passes with the guard deleted, and in a directory holding
`config/settings_switch.json` the guardless command applies it and exits 0.

---

## 3. The switch file

A raw `settings.json` fragment. No wrapper:

```json
{
  "model": "opus",
  "env": {
    "ANTHROPIC_BASE_URL": "https://gateway.corp.local/",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "32000"
  }
}
```

What you write is what lands. Anyone who knows Claude Code's settings can write
one without knowing anything about lmi.

**Discovery.** `--file PATH` if given, otherwise `./config/settings_switch.json`.
That is the whole list. `--file` naming a file that does not exist is exit 2 and
never falls back to the default — the same rule `lmi install`'s `--config`
follows, and for the same reason: a named file that quietly resolves to a
different one is how a machine ends up in a configuration nobody chose.

`~` expansion goes through the guarded `expanduser` (it raises `RuntimeError`
for a `~someuser` that cannot be resolved), and classification through
`core.fs.classify`, so an over-long or unreadable path is exit 2 rather than an
`ENAMETOOLONG` traceback.

**Validation.** Only what lmi can honestly judge:

- the file must parse as JSON, through the BOM-aware decoder — a Windows editor
  writes a UTF-8 BOM and `json.loads` rejects one with a bare "Expecting value";
- the top level must be an object;
- if there is an `env` block, every value must be a **string**.

The `env` rule is not fussiness. Claude Code types `settings.json` `env` as a
map of string to string, and a JSON number there writes cleanly, parses
cleanly, and the setting does nothing — the same silent failure
`install/config._env` already refuses.

Every other key passes through unexamined. Whether `mdel` is a typo for `model`
is Claude Code's schema's business, and it reports that better than a
duplicated validator would. This is also what keeps the command working when
Anthropic adds a setting.

---

## 4. Merge semantics

Recursive, and only for objects:

- both sides are objects → merge them key by key, recursing;
- otherwise → the fragment's value replaces what was there, whole.

```
settings.json   {"env": {"A": "1", "B": "2"}, "model": "sonnet"}
fragment        {"env": {"A": "9"}}
result          {"env": {"A": "9", "B": "2"}, "model": "sonnet"}
```

`B` and `model` survive because they were never mentioned. That is the whole
requirement — *switch only the configuration mentioned in the file* — and it is
why the merge recurses rather than replacing `env` wholesale.

A list replaces a list; there is no element-wise merging. Merging lists has no
single correct answer (append? union? by index?) and guessing produces settings
nobody wrote.

`null` sets a key to `null`. It does **not** remove it. Deleting is out of scope
(section 1), and the alternative — `null` meaning "delete" — makes it impossible
to ever set a key to `null` deliberately.

---

## 5. The origin snapshot

`~/.claude/settings.json.lmi-origin`, mode 0600.

**Written on a switch only if it does not already exist.** Later switches leave
it alone. So after `switch prod` then `switch dev`, the snapshot still holds the
settings the machine had before `prod` — not the prod-shaped ones.

**`switch origin`** copies the snapshot back over `settings.json` and then
deletes the snapshot, so the next switch establishes a fresh pristine point.

**`switch origin` with no snapshot is exit 2**: "no switch has been made, so
there is nothing to restore." Not a silent no-op — a user typing it expects
their settings to change, and a command that does nothing while exiting 0 leaves
them believing it did.

### Why pristine rather than one-step-back

Three models were considered. With `settings.json` at S0, `switch prod` → S1,
`switch dev` → S2:

| | after two switches, `origin` gives | can you reach S0? |
|---|---|---|
| one snapshot, overwritten each switch | S1 | **no** — S0 was overwritten |
| a stack, popped per `origin` | S1, then S0 | yes, in two commands |
| **one snapshot, written once** | **S0** | **yes, always** |

The middle option is the most capable and needs a stack on disk plus something
to show its depth — machinery this command does not otherwise need. The first
makes `origin` mean a different thing depending on history, and loses the real
settings after the second switch, which is the outcome a user would least
expect from a word that means *original*.

The third was chosen: `origin` names one state, that state never moves, and the
word means what it says.

**Intermediate states are not recoverable, deliberately.** After `prod` → `dev`,
the prod-shaped `settings.json` is gone. It is reproducible by re-applying
`prod.json`, which is the file that produced it — so a timestamped backup on
every switch would be storing something already stored, in a directory that
never gets pruned. `lmi install` writes `.bk_<stamp>` backups because it
overwrites settings from values that live in a prompt and cannot be replayed;
this command's inputs are files on disk.

### The line that must not invert

`if the snapshot does not exist: write it` is the whole mechanism. Inverted —
written unconditionally — `origin` silently becomes "undo one step" while still
being spelled `origin`, and a user's real settings are unrecoverable after the
second switch. Nothing observable afterwards distinguishes the two: the file is
present either way, and a single switch behaves identically. It gets a
`MANDATORY` test that switches three times and asserts the snapshot still equals
S0.

---

## 6. Promoting `jsonfile.py` to `core/`

`lmi/commands/install/jsonfile.py` — read-or-empty, back up, write atomically,
preserve mode, refuse unparseable input — is exactly what this command needs,
and commands never import each other.

`CLAUDE.md` §2 says when to act: *"`core/` is for code with no command
flavour… If a second command ever needs the path helpers in it, promote them
then, not in advance."* This is that moment, and the module qualifies: nothing
in it knows what Claude Code is.

**Moves to `lmi/core/jsonfile.py` unchanged, except for the exit code.** Today
it imports `install.exit_codes.EXIT_CONFIG_WRITE` and hardcodes `3` into every
error. In `core/` it cannot know a command's codes, so each function takes the
code as a parameter and the caller supplies its own. Both commands happen to use
`3`, so no behaviour changes.

**`~/.claude/settings.json` also moves.** `install/settings.py::path()` is the
only part of that module both commands need; `merge`, `token_of`,
`MARKETPLACES_KEY` and `TOKEN_KEY` are install-flavoured and stay. The path
becomes `core/claude.py::settings_path()`, so two commands cannot drift about
where Claude Code's settings live. `install/settings.py::path()` becomes a
one-line call to it, keeping install's callers untouched.

**What must not change.** Every existing `jsonfile` test moves with the module
and must stay green — including the two `MANDATORY` ones, which pin the
0600-birth window and the refusal to overwrite unparseable JSON. `CLAUDE.md`
§3 item 20 refers to `jsonfile.write` by name and needs its path updated.
`install/runner.py`'s import changes; nothing else about install does.

This is a refactor of shipped, reviewed code, so it is one commit of its own,
before any new behaviour — a green suite after the move proves the move.

---

## 7. Package structure

```
lmi/commands/config/
  __init__.py      NAME="config", HELP, add_arguments, run
  args.py          the nested subparser, and switch's arguments
  fragment.py      finding, reading and validating the switch file
  merge.py         the recursive merge
  origin.py        the snapshot: write-once, restore, remove
  runner.py        the flow
  exit_codes.py    this command's codes (3, 4)
lmi/core/
  jsonfile.py      promoted from commands/install/ (section 6)
  claude.py        settings_path()
```

`merge.py` is its own module because it is pure, total, and the piece most
worth testing exhaustively: no I/O, no error paths, one function. `origin.py`
is separate because the write-once rule is the command's single most
consequential line and deserves to be readable without the flow around it.

Registration, one line:

```python
from . import config, install, schedule

COMMANDS = [config, install, schedule]
```

**Alphabetical**, and this changes an existing choice deliberately. The
`lmi install` spec put `install` before `schedule` on the grounds that registry
order is `--help` order and should follow the lifecycle a user moves through.
That reasoning scales badly: with three commands the lifecycle order is
arguable — you configure after installing, but you also re-configure between
scheduled runs — and with a fourth it becomes a debate every time. Alphabetical
has no opinion to disagree with, and a reader scanning `--help` for a command
they already know the name of is better served by a predictable position than by
a narrative. The `lmi install` spec's §3 note about `--help` order is superseded
by this one.

---

## 8. Behaviour

**`lmi config switch [--file PATH]`**

1. resolve the fragment path (section 3) and read + validate it
2. read `~/.claude/settings.json` — absent is `{}`, unparseable is exit 3
3. write the origin snapshot **if it does not exist**, at mode 0600
4. merge (section 4)
5. write `settings.json` atomically; force 0600 if the result holds
   `ANTHROPIC_AUTH_TOKEN`
6. print the keys that changed, and whether a snapshot was created

**`lmi config switch origin`**

1. no snapshot → exit 2
2. copy the snapshot over `settings.json`, atomically, preserving 0600
3. delete the snapshot
4. print what was restored

Reading and validating before writing anything means a malformed fragment
leaves the machine untouched. The snapshot is written before the merge, so a
failure during the merge still leaves a recoverable state.

---

## 9. Exit codes

| Code | Owner | Meaning |
|---|---|---|
| 0 | global | done |
| 2 | global | usage: no fragment, `--file` at a nonexistent path, unparseable fragment, non-string `env` value, `origin` with no snapshot |
| 3 | config | `settings.json` or the snapshot could not be read or written |
| 4 | config | a bug in lmi |

No code `1`: this command runs no external process, so there is nothing for the
analogue of "the thing we shelled out to failed" to mean. `3` and `4` keep the
meanings they have in `lmi install`, so a script does not have to learn a
per-command vocabulary.

---

## 10. Testing

`python3 -m pytest tests/ -q`, added under `tests/commands/config/`. The `home`
fixture redirects `HOME` and `USERPROFILE`, so no test can reach a real
`~/.claude`.

*Merge* — siblings survive at depth 1, 2 and 3; a scalar replaces a scalar; a
list replaces a list rather than merging element-wise; an object replacing a
scalar and a scalar replacing an object both behave; `null` sets rather than
deletes; neither input is mutated.

*Fragment* — `--file` at a nonexistent path is 2 and does not fall back to the
default; the default path is used when `--file` is absent; a UTF-8 BOM is
tolerated; a non-object top level is 2; a non-string `env` value is 2; an
unknown key passes through untouched.

*Origin* — **MANDATORY:** three successive switches leave the snapshot equal to
the state before the first. Restoring puts that state back and removes the
snapshot; a second `origin` is exit 2; `origin` before any switch is exit 2; the
snapshot is 0600 and stays 0600 through a restore.

*Flow* — an invalid fragment writes nothing at all; an unparseable existing
`settings.json` is exit 3 and leaves the file byte-identical; a result carrying
a token leaves `settings.json` at 0600; keys not named by the fragment are
unchanged end to end.

*Promotion* — every existing `tests/commands/install/test_jsonfile.py` case
passes against `core/jsonfile.py`, both `MANDATORY` ones included, and the full
install suite stays green.

*Registration* — `[c.NAME for c in COMMANDS] == ["config", "install",
"schedule"]`, alphabetical. `tests/test_cli.py::test_the_registry_lists_every_command_in_help_order`
asserts the exact list and will need updating; that is the intended tripwire,
and updating it is correct rather than a test weakened to pass. Its docstring
currently explains the lifecycle rationale and must be rewritten to say
alphabetical, or it will contradict the list directly above it.

**What tests cannot cover:** that Claude Code actually honours a switched
setting. `README.md` gains a one-line check — switch a profile that changes
`model`, run `claude`, confirm the model changed.

---

## 11. Documentation

- `README.md`: an `lmi config switch` section — the three invocations, the
  fragment shape, merge semantics, what `origin` restores and what it does not,
  the exit codes, and the real-run check.
- `examples/settings_switch.json`: a fragment switching `model` and an `env`
  key, ready to copy.
- `CLAUDE.md`: `config` added to the architecture map; `core/jsonfile.py` and
  `core/claude.py` added; §3 item 20's path updated; a new §3 item for the
  write-once snapshot rule.

---

## 12. Decisions

1. **Settings keys only**, not npm. §1.
2. **Raw fragment, no wrapper.** §3.
3. **Recursive merge; lists replace; `null` sets, never deletes.** §4.
4. **`origin` is the pristine state, snapshot written once.** §5, with the two
   rejected models and why.
5. **No per-switch timestamped backups** — the fragment reproduces the state.
   §5.
6. **`origin` with nothing to restore is exit 2**, not a silent success. §5.
7. **`--file` for paths, `origin` as a bare word** — no collision possible. §2.
8. **`jsonfile.py` promoted to `core/`**, exit code parameterised; `settings_path()`
   promoted alongside it. §6.

**Open questions:** none.
