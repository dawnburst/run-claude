# `lmi config`

Three subcommands over the configuration `lmi install claude` wrote.
**`init`** puts the config folder `lmi` ships into `~/.lmi`, so the folder
exists before anything else needs it. **`switch`** applies a partial
`settings.json` over `~/.claude/settings.json`, and puts back the one the
machine started with. **`schedule`** shows or sets which backend `lmi schedule`
runs Claude through.

[← README](../README.md) · [`lmi schedule`](schedule.md) ·
[`lmi install claude`](install-claude.md) · [`lmi upgrade`](upgrade.md) ·
[Status](status.md)

---

## `lmi config init`

Copies the config folder packaged inside `lmi` to `~/.lmi`, and **keeps every
file that is already there**. Takes no arguments.

```bash
lmi config init
```

```
Config folder: /home/you/.lmi
  created  config.json
  kept     settings.json
  created  settings_switch_direct.json
  created  settings_switch_gateway.json
  created  statusline.js

Those are lmi's defaults, not a site's: edit the registry in config.json,
    the endpoint in the switch files, and re-run `lmi install claude` to
    install from your own source.
```

The four bootstrap scripts run this for you after they install the wheel, so a
fresh machine has the folder before you type anything. Run it by hand when
`~/.lmi` has been deleted, or to pick up a file a newer `lmi` ships that your
folder does not have yet.

**Nothing is overwritten and nothing is backed up** — those are the same
sentence. Every destination that already exists is left exactly as it is,
whatever it holds, so running this repeatedly is safe on a folder you have spent
a year editing: an edited `settings.json`, a switch file of your own, a
`statusline.js` you wrote. Only the missing files are written. A second run in a
row therefore says so and changes nothing, at exit 0.

What lands is what the wheel carries — `config.json` (the packaged `lmi.json`,
under the name discovery looks for at the home level), the `settings.json`
template, the `statusline.js` that template declares, and a gateway/direct
switch pair. Their URLs are the public npm registry, public PyPI and
`gateway.example.com`: enough to work end to end on a machine with internet
access, and **a placeholder to replace** on a machine with a registry of its
own. See [the packaged default](install-claude.md#the-config-file) for how the
same folder reaches a machine through `lmi install claude`.

This does not provision Claude Code — no npm, no `~/.claude`. It only creates
the folder those steps read from, which is why it is safe to run at any time and
why the installer scripts can run it unattended.

The shipped `direct` switch names `https://api.anthropic.com` explicitly rather
than removing `ANTHROPIC_BASE_URL`. That is not a shortcut: a fragment cannot
delete a key, and `null` is refused because `env` values must be strings. A
switch can only ever point the endpoint somewhere.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Files were copied, or everything was already there. |
| 3 | `~/.lmi` could not be written, or the folder inside the wheel is incomplete — a broken install of `lmi` itself. |
| 4 | A bug in `lmi`. |

---

## `lmi config switch`

The command you run afterwards, repeatedly. Moving Claude Code between a
gateway and the direct API, or between models, is one command rather than a hand
edit of the file everything else depends on.

```
lmi config switch                  list the switch files you have
lmi config switch <name>           apply settings_switch_<name>.json
lmi config switch --file PATH      apply that fragment
lmi config switch origin           restore the pristine settings.json
```

### Named switch files

A site usually has several configurations — a gateway, the direct API, a
model — and wants each of them a word away from any directory. So switch files
live **beside the `lmi.json` that discovery resolves**, exactly where
`lmi install claude` looks for its `settings.json`, and are named
`settings_switch_<name>.json`:

```
~/.lmi/config.json                    the config file itself
~/.lmi/settings.json                  the install template
~/.lmi/statusline.js                  the script that template declares
~/.lmi/settings_switch_gateway.json   lmi config switch gateway
~/.lmi/settings_switch_direct.json    lmi config switch direct
~/.lmi/settings_switch_opus.json      lmi config switch opus
```

`--config PATH` and `$LMI_CONFIG` move the folder, so the switch files travel
with the rest of a site's configuration rather than being stranded in whichever
directory you happened to be standing in. `lmi config switch` with no argument
lists what is there:

```
$ lmi config switch
Switch files in /home/u/.lmi:
  direct    settings_switch_direct.json
  gateway   settings_switch_gateway.json
  opus      settings_switch_opus.json

Apply one with: lmi config switch <name>
Restore with:   lmi config switch origin
```

A folder with no switch files in it is **exit 2**, not an empty list at exit 0 —
a bare `lmi config switch` that lists nothing has done nothing, and reporting
that as success is the shape this project spends most of its care avoiding. An
unknown name is exit 2 too, and names the ones that do exist: "I mistyped it"
and "it is in the other folder" look identical otherwise.

A **name is a name, not a path.** Letters, digits, dot, dash and underscore
only — `lmi config switch ../../etc/passwd` is exit 2 rather than a way to merge
an arbitrary JSON document into `settings.json`. Use `--file` for a fragment
that lives somewhere else.

`origin` is **reserved**: it restores, so a `settings_switch_origin.json` can
never be selected. It is not silently ignored — the listing prints a `[WARN]`
naming the file and telling you to rename it, because a fragment sitting in the
folder beside the ones that work, that no command can ever reach, is otherwise
invisible.

### Everything else

`--file` (`-f`) is the only way to name a **path**, and a name and a `--file`
together are exit 2: two sources for one merge, and picking either silently is
how the wrong configuration lands while the command reports the other.

A bare `lmi config switch` still applies `./config/settings_switch.json` when
that file exists, exactly as it did before names existed. The listing is what a
bare switch means only when it does not.

A `--file` that points at a file which does not exist is **exit 2**, never a
quiet fall-through to `./config/settings_switch.json`. Same rule and same reason
as [`--config`](install-claude.md#the-config-file): an explicitly named file
that silently resolves to a different one is how a machine ends up in a
configuration nobody chose.

`origin` **wins over `--file`**, and the fragment is then ignored without
comment: `lmi config switch origin --file prod.json` restores the pristine
settings and never looks at `prod.json`. `origin` is the more destructive of the
two and you named it explicitly, so quietly applying a fragment instead would be
the worse of the two surprises.

The command writes no log file — everything it does is printed, including the
path of the fragment it used and the top-level keys it wrote.

### The fragment

A **raw `settings.json` fragment**, not an `lmi` config file. There is no
wrapper key and no translation layer: what you write is what lands in
`~/.claude/settings.json`. [`examples/settings_switch.json`](../examples/settings_switch.json)
is a complete one — copy it to `~/.lmi/settings_switch_<name>.json` and edit it.

```json
{
  "model": "opus",
  "env": {
    "ANTHROPIC_BASE_URL": "https://gateway.example.com/",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "32000"
  }
}
```

`registry` is **not** a `settings.json` key. It belongs to
[`lmi install claude`](install-claude.md), which hands it to npm to write into
an npmrc; put it in a fragment and you get a `registry` key in `settings.json`
that nothing anywhere reads, with no error to tell you so.

Validation goes exactly as far as `lmi` can honestly judge and no further: the
file must be a JSON object, and an `env` block must map strings to strings.
**The `env` values are strings** — `"32000"`, not `32000`. Claude Code types
that block as string to string, so a JSON number writes cleanly, parses cleanly
and does nothing at all; exit 2 now is cheaper than finding out in a month.
Every other key passes through unexamined, deliberately: whether `mdel` is a
typo for `model` is Claude Code's own schema's business, it reports that better
than a duplicated validator would, and it is what keeps this command working on
the day Anthropic adds a setting.

The fragment is read through the same BOM-aware decoder as everything else here,
so a file saved by Notepad or PowerShell's `Set-Content` — both of which write a
UTF-8 BOM that `json.loads` rejects with a bare "Expecting value" — is read
correctly rather than reported as broken JSON.

### What the merge does

The fragment is merged **recursively**, so a switch touches only what it names.
Two objects merge key by key; anything that is not two objects replaces whole.
Applying `{"env": {"A": "9"}}` to a settings file holding
`{"env": {"A": "1", "B": "2"}}` leaves `{"env": {"A": "9", "B": "2"}}` — `B`
survives, and so do `model`, `theme` and every key the fragment never mentions.

Two consequences worth having in front of you before you write one:

- **A list replaces a list**, rather than being appended to or unioned. Merging
  lists has no single right answer, and guessing produces a `permissions.allow`
  that nobody wrote. A fragment naming a list must therefore give the whole one.
- **`null` sets a key to `null`; it does not delete it.** `{"model": null}`
  leaves `"model": null` in `settings.json`. There is deliberately no delete
  syntax — `switch origin` is how you get back to a file that never had the key.

### `origin` — the settings you had before any of this

`lmi config switch origin` restores the `settings.json` this machine had before
the **first** switch, not before the last one. The first switch copies your
settings to `~/.claude/settings.json.lmi-origin`, mode `600` because
`settings.json` may carry `ANTHROPIC_AUTH_TOKEN` and `~/.claude/` is `0755`.
That snapshot is written **once — only if it is not already there** — and no
later switch touches it. So however many fragments you apply, in whatever order,
`origin` keeps meaning "the state `lmi` found on this machine".

Restoring **uses the snapshot up**: it is copied back over `settings.json` and
then removed, so the next switch establishes a fresh pristine point and a second
`origin` in a row tells you there is nothing left to restore instead of silently
repeating itself. Running `origin` when no switch has ever been made here is
**exit 2**, with the reason, rather than a success that did nothing.

**Intermediate states are not recoverable, and that is the design.** After
`--file prod.json` and then `--file dev.json`, the prod-shaped `settings.json`
is gone; `origin` skips past it to what you had before either. Nothing is lost
that cannot be rebuilt — applying `prod.json` again produces that state again,
which is the whole point of the fragment being a file you keep. It is also why
this command takes no timestamped `.bk_` backups of its own, unlike
`lmi install claude`, which edits documents no fragment could reconstruct.

`settings.json` is written **atomically** — a temp file beside it, then
`os.replace` — because a half-written one is invalid JSON and Claude Code will
not start without it. An existing `settings.json` that is *already* invalid JSON
is refused with exit 3 and left byte-identical rather than treated as an empty
document and overwritten, which would silently discard everything you had
hand-edited. A merged result holding `ANTHROPIC_AUTH_TOKEN` is written `600`;
otherwise the file keeps the mode it already had, and one created from nothing
is born `600` rather than at the umask default. A restore always writes `600`,
since the snapshot it comes from is `600` and the file it lands on must not be
looser — so a `settings.json` that started at `644` comes back from `origin`
at `600`.

### Exit codes

| Code | Meaning | Scope |
|---|---|---|
| 0 | The fragment was applied, or the pristine settings were restored | global |
| 2 | No fragment found, a `--file` that does not exist, a fragment `lmi` will not accept — not UTF-8, not JSON, not an object, a non-string `env` value — or `origin` with nothing to restore | global |
| 3 | A settings file could not be read or written | `config` |
| 4 | A bug in `lmi` | `config` |

`3` and `4` keep the meanings they have in `lmi install claude`, so a script
does not have to learn a per-command vocabulary. There is deliberately **no
`1`**: in the other two commands `1` means "the external thing we shelled out to
failed", and this command shells out to nothing at all — no npm, no `claude` —
so a `1` here would have no meaning to give it.

---

## `lmi config schedule`

Shows or sets which backend `lmi schedule` runs Claude through. See
[Backends](schedule.md#backends) for what the two are.

```bash
lmi config schedule                    # show
lmi config schedule --mode cli         # set
lmi config schedule --mode sdk --config ./config/lmi.json
```

With no `--mode` it prints three things, and the third is the one you cannot
deduce from the other two:

```
Backend    : sdk
Chosen by  : default
--mode goes to: /home/you/.lmi/config.json
             (no config file exists yet; it would be created)
```

`Chosen by` is the file the value came from, or `default` when no config file
said anything — an absent `mode` key falls back without naming a file at all,
which is why "where would a change go?" is a separate line.

The write goes to whichever config file [the usual search
order](install-claude.md#the-config-file) resolves. When nothing is found it creates
`~/.lmi/config.json` — the machine-level file, since a backend is a property of
the machine, and a config file created inside a checkout gets committed by
accident — and then **re-runs discovery to confirm the file it just wrote is
the one that wins**. If it is not, that is exit 2 naming both paths. Writing
`~/.lmi/config.json` while a higher-priority `./config/lmi.json` exists would
otherwise report success while `lmi schedule` kept the old backend for ever.

An invalid `--mode` is exit 2 **before any file is touched**, with the same
message `lmi schedule` produces for the same bad value in a config file — one
list of valid names, in one place.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Shown, or written. |
| 2 | A mode that is not `sdk` or `cli`; a `--config` that does not exist; a config file that is not valid JSON; or the shadowed-write case above. |
| 3 | The config file could not be read or written. |
| 4 | A bug in lmi. |
