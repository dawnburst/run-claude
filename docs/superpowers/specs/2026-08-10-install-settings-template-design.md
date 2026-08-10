# `lmi install claude` installs from a settings.json template

**Date:** 2026-08-10
**Status:** approved, not yet implemented

## The change in one paragraph

`lmi install claude` stops *composing* `~/.claude/settings.json` out of pieces of
`lmi.json` and starts *installing a file the operator wrote*. A `settings.json`
sitting in the config folder beside `lmi.json` is the whole content of the
settings file, verbatim, with one substitution: `env.ANTHROPIC_AUTH_TOKEN` is
replaced by the token the command asks for. An existing `~/.claude/settings.json`
is backed up with a timestamp and replaced rather than merged into. `lmi.json`'s
`claude` section loses the two keys that were duplicating the template —
`marketplaces` and `env` — and keeps `registry` and `cafile`.

## Why

The site's settings file is a Claude Code document with a schema Anthropic owns
and extends. Expressing it as two keys in `lmi.json` meant lmi had to grow a
translation for every setting a site wanted, and a site could only ever set the
settings lmi had learned. A template the operator writes is the same trade
`lmi config switch` already makes with its fragment: what you write is what
lands, and validation goes exactly as far as lmi can honestly judge.

The keys were also genuinely duplicated. `claude.marketplaces` existed only to be
copied into `extraKnownMarketplaces`, and `claude.env` only to be copied into
`env`. Two spellings for one thing is how the two drift.

## Decisions taken

Four questions were settled before design; each is recorded here with the option
chosen and the reason, because the rejected options are all defensible and will
be proposed again by whoever reads this next.

**Where the template lives: beside the `lmi.json` that won.** Not a fixed
`./config/settings.json`, and not a path key inside `lmi.json`. The config
*folder* is defined as the directory of whichever config file discovery
resolved, so `--config /site/lmi.json` reads `/site/settings.json`, `$LMI_CONFIG`
follows its own file, and the default `./config/lmi.json` reads
`./config/settings.json`. A fixed working-directory path would let `--config`
point at one site's `lmi.json` while the template came from another's. A path key
would add a second key to the section this change exists to reduce to one.

**A missing template is exit 2, not a warning.** It is refused before npm runs.
The alternative — install the binary, skip the settings write, print a warning —
produces a machine with no token, no base URL and no marketplaces while the
command reports success, which is the silent-failure class this codebase treats
as the expensive one.

**A blank token is refused.** The prompt no longer accepts blank. This is not
politeness: the template ships with a placeholder (`<Token from the user
input>`), and a blank answer would write that placeholder to
`~/.claude/settings.json` verbatim. See the new item 30 below.

**`cafile` stays in `lmi.json`.** Only `marketplaces` and `env` were duplicates.
`cafile` is the CA lmi hands to `npm config set cafile`; it has no
`settings.json` equivalent, and dropping it would mean every install on every
site running `npm config set strict-ssl false` and printing the TLS warning,
permanently.

## Architecture

### New: `lmi/commands/install/template.py`

Finding, reading and validating the settings.json template. The mirror of
`lmi/commands/config/fragment.py`, and deliberately shaped like it — the two
solve the same problem (a raw Claude Code document supplied by the operator) and
a reader who knows one should recognise the other.

```
template.NAME = "settings.json"
template.load(config_path) -> (doc, path)
```

`path` is `config_path.parent / NAME`. Every refusal is `EXIT_USAGE` (2) and
names the path:

| Condition | Why it is refused rather than tolerated |
|---|---|
| the file is absent | the decision above |
| `OSError` reading it | unreadable is not empty |
| not UTF-8 | decoded through `core.text.decode_with_bom` first, because Notepad and PowerShell's `Set-Content` both write a UTF-8 BOM and `json.loads` rejects one with a bare "Expecting value" |
| not valid JSON | Claude Code cannot start without a parseable settings file |
| not a JSON object | the same |
| `env` present and not an object | as `fragment._validate` |
| `env` value not a string | Claude Code types settings.json `env` as string-to-string; a JSON number writes cleanly, parses cleanly and does nothing |

The last two rows are CLAUDE.md item 18 *moving*, not disappearing. It lives in
`config._env` today, guarding `claude.env` in `lmi.json`; with that key gone the
same failure reappears one file over, in the template.

The `env` check uses the `_MISSING` sentinel rather than `doc.get("env") is
None`, for the reason `fragment._validate` does: an absent key and `"env": null`
are different documents, and `null` is a value everywhere else in a settings
file.

### Changed: `lmi/commands/install/config.py`

`Config` becomes:

```python
@dataclass(frozen=True)
class Config:
    registry: str
    cafile: Optional[Path]
    settings: Dict          # the parsed template
    settings_source: Path   # where it came from
    source: Path            # the lmi.json
```

`marketplaces` and `env` fields go. `DEFAULT_ENV`, `_env` and `_object` go with
them. `EXAMPLE` shrinks to `registry` and `cafile`.

`build_config` calls `template.load(path)` and puts the result on the Config, so
the promise in its docstring — "never returns a partial Config" — still holds and
every config error still surfaces before npm runs.

### Changed: `lmi/commands/install/settings.py`

`merge` and `_merged` go. In their place:

```python
settings.compose(template, token, bash_path) -> dict
```

A deep copy of the template — `copy.deepcopy`, because the caller must not
mutate a document the Config owns — with `env[TOKEN_KEY]` set to `token` and
`env[gitbash.VAR]` set when `bash_path` is not None. The `env` block is created
if the template has none.

`path()`, `token_of`, `TOKEN_KEY` and `ENV_KEY` stay. `MARKETPLACES_KEY` stays
too, although nothing merges through it any more: the operator now writes
`extraKnownMarketplaces` by hand in the template, so the README naming the exact
spelling matters more than it did, not less, and
`test_the_readme_names_the_silent_keys` pins it through this constant.

### Changed: `lmi/commands/install/runner.py`

`_run` no longer reads `~/.claude/settings.json`. The `jsonfile.read` of that
file goes; the one in `_write_onboarding_flag` for `~/.claude.json` stays.

`_ask_for_token(*)` no longer inspects an existing token to phrase the question —
there is nothing to keep. It asks `prompts.secret("Claude Code auth token")` and
re-asks on a blank answer, up to three attempts, then `EXIT_USAGE`. A loop rather
than an immediate refusal because a mistyped or half-pasted token is the common
case; bounded rather than unbounded because an unbounded loop with a
non-terminal stdin would be a hang if `prompts.secret` ever stopped raising
`EOFError` — it does raise, which is what makes even the unbounded form safe
today, and the bound is the belt to that brace.

`_write_settings(cfg, token, bash_path, path, stamp, backups)`:

1. `_back_up(path, stamp, ...)` — unchanged, and now load-bearing (item 31).
2. `settings.compose(cfg.settings, token, bash_path)`.
3. `jsonfile.write(..., mode=0o600)` — unconditional now, where it used to be
   conditional on a token being present, because a token is always present.

### Data flow

```
config/lmi.json      --> config.build_config --+
config/settings.json --> template.load --------+--> Config
                                                     |
   token (prompt) ----------------------------+      |
   git bash path (Windows) -------------------+      |
                                              v      v
                                        settings.compose
                                              |
                    jsonfile.backup           v
   ~/.claude/settings.json --> .bk_<stamp>   jsonfile.write(0600)
                                              |
                                              v
                                    ~/.claude/settings.json
```

The order in `_run` is unchanged and still load-bearing: every question is asked
before anything is modified, and npm runs before any Claude config file is
touched.

## Error handling

Nothing new in kind. Template errors are exit 2 and are raised inside
`build_config`, which is the first thing `_run` calls — before `npm.find`, before
any question, before any write. `jsonfile.backup` failing is still exit 3 with
"Nothing was changed". `runner.run`'s blanket `except Exception -> EXIT_INTERNAL`
still covers the unforeseen.

## Regressions this creates, for CLAUDE.md section 3

The list is appended to, never renumbered.

**Item 18 is reworded in place.** Same rule, new home: `template._validate`
refuses a non-string `env` value, for the reason `config._env` used to.

**Item 19 narrows, and says so.** A hand-corrupted `~/.claude/settings.json` used
to be exit 3 with nothing written. It is now backed up and replaced — which is
the point of the change. The rule stays whole for `~/.claude.json`, which is
still read through `jsonfile.read`, and for `lmi config switch`, which still
merges into what it finds.

**New item 30 — the placeholder token must never be written.** The shipped and
example templates carry `"ANTHROPIC_AUTH_TOKEN": "<Token from the user input>"`.
If the token prompt accepted a blank answer, `compose` would leave that string in
place and `jsonfile.write` would put it in `~/.claude/settings.json`. **Silent:**
the install reports success, the settings file looks fully configured, the token
is present and the right shape at a glance — and every Claude Code call 401s with
an error that points at the gateway, not at lmi. The guard is the refusal of a
blank token, and a test asserting the placeholder string never appears in the
written document.

**New item 31 — the backup is now the only copy.** Replacing wholesale means the
`.bk_<stamp>` file is the sole surviving record of what the machine had.
`jsonfile.backup` must stay *before* the write and must stay fatal on failure;
downgrading it to a warning, or moving it after the write, would make a failed
copy silently unrecoverable. This was true-but-cheap under merging, where the
user's own keys survived in the merged document; it is now the whole safety net.

## Documentation and shipped files

| File | Change |
|---|---|
| `examples/lmi.json` | `claude` section drops `marketplaces` and `env`; keeps `registry`, `cafile` |
| `examples/settings.json` | already added; becomes the documented example template |
| `config/lmi.json` | drops `env`; leaves `registry` only |
| `config/settings.json` | **new.** Ships the 256K env profile, telemetry off, the token placeholder. No marketplaces and no `ANTHROPIC_BASE_URL` — those are site-specific and `examples/settings.json` is where they are shown |
| `README.md` | the template documented under `lmi install claude`; config-key table trimmed to `registry`/`cafile`; the token-prompt row corrected — blank is no longer accepted; the exit-code notes on reading `~/.claude/settings.json` corrected |
| `CLAUDE.md` | `template.py` in the section 2 tree; items 18 and 19 reworded in place; items 30 and 31 appended |

`config/settings.json` is not optional. With the template required,
`config/lmi.json` alone no longer installs, and
`tests/test_docs.py::test_the_shipped_default_config_is_accepted_by_the_validator`
goes red without it.

## Testing

New `tests/commands/install/test_template.py`, one test per refusal in the table
above plus the accepting cases, modelled on the existing
`tests/commands/config/` fragment tests.

Updated:

- `tests/commands/install/test_config.py` — the `DEFAULT_ENV` and `claude.env`
  tests go; new tests that `build_config` finds the template beside the config
  file and that a missing one is exit 2.
- `tests/commands/install/test_settings.py` — the `merge` tests become `compose`
  tests: the token lands, the Git Bash var lands on Windows and not off it, the
  template is not mutated, a template with no `env` block gets one.
- `tests/commands/install/test_runner.py` — a blank token is re-asked and then
  refused; the placeholder never reaches the written file (MANDATORY, item 30);
  an existing settings.json is backed up and then fully replaced rather than
  merged; an unparseable existing settings.json is replaced rather than refused.
- `tests/test_docs.py` — the two key-set assertions shrink to
  `{"registry", "cafile"}` and `{"registry"}`; new assertions that
  `examples/settings.json` and `config/settings.json` both pass `template.load`.

The whole suite runs with `python3 -m pytest tests/ -q`.

## Out of scope

No change to `lmi config switch`, `lmi schedule` or `lmi upgrade`. No change to
`core/jsonfile.py`. No new command-line flags — the template's location is
derived from `--config`, which already exists.
