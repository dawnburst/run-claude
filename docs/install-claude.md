# `lmi install claude`

Installs the **Claude Code CLI itself** on a machine with no route to the public
npm registry, then configures it: your `settings.json`, the auth token you are
asked for, the Windows Git Bash path, and onboarding marked complete.

**Prerequisite: Node.js 18 or newer.** Claude Code is an npm package and this
command installs it with `npm install -g`, so a Node runtime has to be on the
machine first — see [npm has to be there already](#what-it-does).

[← README](../README.md) · [`lmi schedule`](schedule.md) ·
[`lmi config`](config.md) · [`lmi upgrade`](upgrade.md) · [Status](status.md)

---

## What it does

It points npm at your internal Artifactory, runs
`npm install -g @anthropic-ai/claude-code`, and then installs the configuration
the site expects, marking onboarding complete so the first `claude` gets to work
instead of asking questions. It is the command you run **first** on a new
machine.

Two files in one folder, then: `lmi.json`, which says where to install *from*,
and `settings.json`, which is what Claude Code ends up configured *with* — plus
an optional third, a `statusline.js` for the `statusLine` that settings file
declares.

```
lmi install claude [--config PATH]
```

**It is interactive, and it needs a terminal.** It asks before repairing an
existing install, asks for the auth token, and asks for the Git Bash path when it
cannot find one. There is deliberately no `--yes`, so it cannot be driven from an
Ansible play, a Dockerfile or a CI step — an accepted cost, not an oversight.
What it will never do is *hang*: with no terminal, `input()` and `getpass()`
raise `EOFError`, and that becomes exit 2 with a message rather than a
provisioning run blocked forever with nobody there to answer it.

**npm has to be there already.** If `npm` is not on PATH the command stops with
exit 2 and says to install Node.js 18 or newer first. `lmi` deliberately does not
bootstrap a runtime, and it never invokes `sudo`.

## The config file

Everything that differs between sites lives in one JSON file.
[`examples/lmi.json`](../examples/lmi.json) is a complete one — copy it and edit it.

Searched in this order, first match wins:

1. `--config PATH`
2. `$LMI_CONFIG`
3. `./config/lmi.json`
4. `~/.lmi/config.json`
5. `default-config/`, packaged inside `lmi` itself

The working-directory default is `./config/lmi.json` — a checkout keeps its
config in one obvious place rather than loose in the root. This repository
ships one, pointing at the public npm registry; a site replaces it.

**The last entry is why `pip install lmi` is the whole installation.** A machine
with the wheel and nothing else can run `lmi install claude`: there is no file to
fetch, write or edit first. `lmi/commands/install/default-config/` holds the same
pair any config folder holds — an `lmi.json` with the two URLs that differ
between sites, `registry` and `index`, and the `settings.json` template beside it
carrying the 256K profile and the token placeholder. No `cafile`: that key is
checked to exist, so any value here would be exit 2 on a machine without that
file.

Both URLs point at the **public** sources — `registry.npmjs.org` and
`pypi.org/simple/` — so a machine with internet access is provisioned end to end
by `pip install lmi` and `lmi install claude`, with no config file at all. **A
site installs from its own mirrors by editing `default-config/lmi.json` before
building the wheel it distributes**, and its machines then need no config file
either.

Note what that does *not* change. `index` being public here is a value written in
a file, printed as `Config:` before anything runs, asked about before pip is
invoked, and visible in `~/.lmi/config.json` afterwards. `lmi` still refuses to
*infer* public PyPI from an absent `index` — see [the `index`
key](#the-config-file) below — because an inferred one is the same install with
nobody told. On an air-gapped machine that forgets to edit the file, the SDK
question is still asked first and a failing pip is still a `[WARN]` and the `cli`
backend, not a failed install.

Two properties keep a last-resort default from becoming the wrong-registry
provisioning the rules below exist to prevent:

- **It is last, and it is announced.** Every file a human put somewhere outranks
  it, and a run that falls through to it prints
  `Config:   .../default-config/lmi.json (packaged default)` before the first
  npm command. Otherwise a mistyped working directory would install from a
  registry nobody chose and read exactly like a normal run.
- **It is copied out before it is written to.** Just before recording the
  backend, `lmi install claude` copies **every file in the packaged folder** to
  `~/.lmi/` and says so. `schedule.mode` then lands in a file `lmi schedule`
  actually reads — writing it inside `site-packages` would be a correct-looking
  file that nothing looks at and that the next `pip install --upgrade` replaces.
  From then on the machine has an ordinary config folder to edit, and the next
  install finds it by the ordinary search.

Every file, not just the two: `lmi.json` becomes `~/.lmi/config.json` — the name
discovery looks for at the home level — and everything else keeps its own name.
So a `statusline.js`, or a `settings_switch_<name>.json` your site ships in that
folder, arrives in `~/.lmi/` where `lmi config switch` will actually find it.

**Anything already in `~/.lmi/` is backed up first.** The packaged default is
only reached when discovery found no config *file*, which is not the same as an
empty folder — a `~/.lmi` holding just a `settings.json`, or only switch files,
still falls through and gets copied into. Those files are copied to
`~/.lmi/backup_<timestamp>/` before anything is overwritten, and the count and
path are printed. A failed backup **stops the adoption** with nothing changed:
that copy is the only surviving version, and the packaged default is still in
the wheel if you run the command again. Earlier `backup_` folders are skipped
rather than copied, so generations never nest inside each other. Nothing is ever
deleted — clean them up yourself.

The packaged folder ships a **`statusline.js`**, and its template declares the
`statusLine` whose command runs it. Both halves or neither: a template declaring
a statusline with no script beside it installs a command pointing at nothing, and
a script with no declaration lands in `~/.claude` and is never run. Each is a
`[WARN]` at run time, so the shipped pair is pinned by the suite instead.

A file left at the **old** `./lmi.json` path is **exit 2**, not a silent skip.
Skipping it would let `~/.lmi/config.json` win — a different registry — while
an `lmi.json` sits in plain view in the working directory, which is the same
wrong-registry provisioning the `--config` rule below prevents, arrived at from
the other direction. The message says how to move it, and `--config ./lmi.json`
keeps it where it is.

A `--config` that points at a file which does not exist is **exit 2**, never a
quiet fall-through to the next candidate: an explicitly named file that silently
resolves to a different one is how a machine gets provisioned against the wrong
registry without anybody finding out.

```json
{
  "claude": {
    "registry": "https://artifactory.example.com/api/npm/npm-virtual/",
    "index": "https://artifactory.example.com/api/pypi/pypi-virtual/simple/",
    "cafile": "/etc/ssl/certs/corp-ca.pem"
  }
}
```

| Key | Required | Meaning |
|---|---|---|
| `registry` | **yes** | The npm registry URL to install from — your internal Artifactory. |
| `index` | no | The **Python** package index the Claude Agent SDK is installed from. Absent: the SDK is not installed and the machine is set to the `cli` backend. See [Backends](schedule.md#backends). |
| `cafile` | no | PEM file for the internal CA — `npm config set cafile`, and pip's `--cert` for the SDK. Checked for existence before any npm command runs. |
| `strict-ssl` | no | `true` or `false`, written straight through to `npm config set strict-ssl`, and `false` additionally buys pip a `--trusted-host` for the SDK install. **Omit it and neither tool's TLS is touched at all.** |

Four keys, and no more. Anything else in the file is ignored, and the whole
`claude` section is validated before a single npm command runs. `cafile` in
particular is checked for existence up front, because `npm config set cafile
/typo` succeeds and the mistake resurfaces much later as an unrelated TLS error
from the install step.

**Nothing about npm's TLS is inferred.** A config that sets neither key leaves the
machine's npm exactly as it was. `lmi` used to read "no `cafile`" as
"verification cannot work here" and run `npm config set strict-ssl false` — right
for an internal Artifactory behind a private CA the machine does not trust, wrong
for every registry whose certificate already verifies. That setting is **global
and permanent**: it covers every later `npm install` by that user, for every
package. Too much to switch off because a file omitted an unrelated key, and with
the packaged default to fall through to it would have become what a bare
`pip install lmi` did to a machine.

| Config | npm | pip (the SDK install) |
|---|---|---|
| neither key | nothing — TLS left alone | nothing — TLS left alone |
| `cafile` | `npm config set cafile <path>` | `--cert <path>` |
| `"strict-ssl": false` | `strict-ssl false`, with the warning below | `--trusted-host <index host>`, with a warning |
| `"strict-ssl": true` | `strict-ssl true` — the repair for a machine an older `lmi` turned it off on | nothing; pip verifies by default |
| `cafile` + `"strict-ssl": false` | **exit 2.** Contradictory: verification off means the CA is never consulted, so `cafile` would silently do nothing | |

One key for both tools, like `cafile`: it is one decision about one pair of
hosts, and two spellings for it would be two chances to configure half a
machine. The asymmetry that remains is real and deliberate — npm's setting is
**global and permanent** because npm has no per-invocation registry flag, while
pip's `--trusted-host` covers that one command and no `pip.conf` is ever
written.

The spelling is `strict-ssl`, npm's own, like `registry` and `cafile`.
`strict_ssl`, `strictSsl` and `strictSSL` are refused with exit 2 rather than
ignored, because an ignored one leaves TLS untouched while the config claims
otherwise. The consequence of not guessing is that a private CA now fails at
`npm install` — and at the SDK's `pip install` — instead of being waved through,
so the npm error names the certificate as one of its three hypotheses and says
which key fixes it.

An absent `index` means **"do not install the SDK"** — it never means public
PyPI. On an air-gapped machine reaching for pypi.org is a timeout; on a machine
with egress it would install an unvetted package from a different source than
everything else on the box, and exit 0, which defeats the only reason this
command exists. A site that wants only the CLI backend simply leaves the key
out.

The **`schedule`** section of the same file carries `mode`, which chooses the
backend. `lmi install claude` writes it and `lmi config schedule` changes it;
you rarely write it by hand. See [Backends](schedule.md#backends).

Everything that ends up in `~/.claude/settings.json` — the marketplaces, the
256K context profile, the gateway URL — lives in the settings template below,
not here. It used to be `marketplaces` and `env` keys in this file, which was
two spellings for one thing.

The auth token is **not** a config key either. This file is site-wide and meant
to be copied between machines; the token is per user, and it is prompted for.

## The settings template

Beside the `lmi.json`, in the same folder, sits a **`settings.json`**. It is a
raw Claude Code settings document, and it is what the command installs as
`~/.claude/settings.json` — verbatim, with `env.ANTHROPIC_AUTH_TOKEN` replaced
by the token you type and `CLAUDE_CODE_GIT_BASH_PATH` added on Windows.

[`examples/settings.json`](../examples/settings.json) is a complete one; this
repository ships one inside the package, at
[`lmi/commands/install/default-config/settings.json`](../lmi/commands/install/default-config/settings.json)
beside `default-config/lmi.json`, and a site replaces it.

```json
{
  "env": {
    "ANTHROPIC_AUTH_TOKEN": "<Token from the user input>",
    "ANTHROPIC_BASE_URL": "https://api.XXX.com",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "204800",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"
  },
  "extraKnownMarketplaces": {
    "my-marketplace": {
      "source": {"source": "url", "url": "https://git.example.com/m.git"}
    }
  },
  "theme": "dark"
}
```

**It is found beside whichever `lmi.json` won**, not at a fixed path. `--config
/site/lmi.json` reads `/site/settings.json`; `$LMI_CONFIG` brings its own; the
`./config/lmi.json` default reads `./config/settings.json`. One folder, one
site — a template resolved against the working directory instead could pair one
site's registry with another site's gateway and report success.

**What you write is what lands.** `lmi` validates only that the file is a JSON
object and that `env` maps strings to strings; every other key passes through
unexamined, because whether `mdel` is a typo for `model` is Claude Code's
schema's business and it reports that better than a duplicated validator would.
It is also what lets a setting Anthropic adds tomorrow work today, without `lmi`
learning it first. `extraKnownMarketplaces` is spelled exactly that way — any
other spelling writes cleanly, parses cleanly and is ignored.

**`env` values are strings** — `"256000"`, not `256000`. Claude Code types
`settings.json` `env` as string to string, so a JSON number writes cleanly,
parses cleanly and does nothing at all. `lmi` refuses one with exit 2 rather
than letting you discover that a month later.

**A missing `settings.json` is exit 2**, before npm runs. Installing the binary
and skipping the settings would leave a machine with no token, no base URL and
no marketplaces while the command reported success.

The `ANTHROPIC_AUTH_TOKEN` value in the file is a **placeholder** and is meant
to stay one — do not commit a real token to it. The prompt refuses a blank
answer precisely so the placeholder can never be installed as though it were a
token.

The one exception is a re-install on a machine that already has a real token.
`lmi install claude` reads the `env.ANTHROPIC_AUTH_TOKEN` out of the
`~/.claude/settings.json` it is about to replace, and if it finds one, offers
to keep it:

```
An auth token is already configured: sk-a...9f2c
Claude Code auth token (blank to keep the existing one):
```

Only the two ends of the token are ever shown, and only for a token long enough
that the hint is not the credential — anything shorter prints `****`. Enter then
keeps that token and nothing else: the template is still installed **whole**, so
every other value in the old file is replaced, exactly as on a first install.

The offer is made only when there is genuinely something to keep. No
`settings.json`, no `env.ANTHROPIC_AUTH_TOKEN`, a blank one, a file that no
longer parses, or a file holding your template's own placeholder — each of those
is "no token", the question loses its `(blank to keep the existing one)`, and a
blank answer is refused as before. An unreadable file is a `[WARN]` and not an
error: that file is about to be backed up and replaced regardless.

## The statusline script

A `settings.json` may carry a `statusLine` block, and the shipped template does:

```json
"statusLine": {
  "type": "command",
  "command": "node ~/.claude/statusline.js"
}
```

That block names a script, and a settings document cannot put one there. So the
third file in the config folder is a **`statusline.js`**, beside the `lmi.json`
and the `settings.json`, and `lmi install claude` copies it to
`~/.claude/statusline.js` — **byte for byte**, line endings, encoding and
executable bit included. It is your script; `lmi` moves it and does not edit it.
This repository ships a working one at
[`default-config/statusline.js`](../lmi/commands/install/default-config/statusline.js),
which is what the shipped
template's command runs.

Found beside whichever `lmi.json` won, for the same reason the template is:
`--config /site/lmi.json` gets `/site/statusline.js`. One folder, one site.

**Unlike `settings.json`, it is optional.** A config folder with no
`statusline.js` installs exactly as it did before this file existed, and says so
in one line. What `lmi` will not do is let the two halves disagree in silence,
because either one alone is a statusline that simply does not appear:

| Situation | What happens |
|---|---|
| Script beside the template, `statusLine` in it | copied to `~/.claude/statusline.js`, and the block installed with the rest of the template |
| `statusLine` in the template, no script beside it | nothing copied, and a `[WARN]` naming the path it looked at. Claude Code will run a command pointing at a file nobody wrote |
| Script beside the template, no `statusLine` in it | still copied — the file is where you asked for it — and a `[WARN]` saying nothing will run it |
| Neither | a single line saying no statusline was installed |

Both mismatches are warnings rather than exit 2 on purpose: only you know what
your `statusLine` command actually runs, and a site whose command runs something
else entirely has to keep installing.

An existing `~/.claude/statusline.js` is backed up to
`statusline.js.bk_<timestamp>` and then replaced, exactly like the settings file.
The copy happens **before** the settings are written, so `~/.claude` never holds
a `settings.json` naming a script that is not there yet.

## What it asks

At most three questions, and all of them are asked **before anything on the
machine changes**. Abandon the command at a prompt and nothing has been touched.

| Question | When | A blank answer |
|---|---|---|
| `Repair the installation?` | only when `claude` is already on PATH — the resolved path is printed first | keeps the default, **no**: exit 0, no npm command, no backup, no write |
| `Claude Code auth token` | on every run that is going to do anything — i.e. once the repair question, if it was asked at all, has been answered yes. Read with `getpass`, so it is never echoed into your scrollback | **is refused.** Asked again, up to three times, then exit 2 with nothing changed |
| `Claude Code auth token (blank to keep the existing one)` | the same question, in the one case where a blank has something to mean: a real token was read out of the `~/.claude/settings.json` about to be replaced. A masked hint at that token is printed above it | **keeps the token already on the machine.** Nothing else about the old file is kept |
| `Install the Claude Agent SDK…?` | only when `claude.index` is set — with no index there is nothing to consent to | keeps the default, **yes** |
| `Full path to bash.exe` | Windows only, and only when no Git Bash was found | skips it, with a `[WARN]` naming `CLAUDE_CODE_GIT_BASH_PATH` |

Declining the repair is not an error. You answered the question; the answer was
no; exit 0.

Declining the **SDK** question, on the other hand, is not a no-op — and the
question says so. It sets this machine to the `cli` backend, because leaving
the mode unset would leave the default pointing at a backend you have just
declined to install, and every `lmi schedule` afterwards would exit 2 on a
machine this command reported as provisioned.

## What it installs, besides Claude Code

When `claude.index` is set and you agreed, `lmi install claude` also runs one
pip command to install **`claude-agent-sdk`** — into `sys.executable`, the very
interpreter that will run `lmi schedule`, never a `pip` found on `PATH`.

Then it decides the backend by **importing the package in a subprocess**, not
by looking at pip's exit code. pip exiting 0 answers "did something get
installed somewhere", which is not the question: it can succeed into a
different interpreter entirely, and the machine would be written `sdk` while
every scheduled run afterwards exits 2.

Import works → mode `sdk`. Anything else → mode `cli`, with a `[WARN]` naming
the package, the index it was sought from, and `lmi config schedule --mode sdk`
as the way back once your Artifactory carries it. **A failing pip does not fail
the install**: it means one of two backends is unavailable and the other one —
driving the binary npm just installed — works fine. Everything else is still
written and the command exits 0.

There is deliberately no retry against public PyPI, and no `--user`,
`--break-system-packages` or `--target` retry. Each would either install from a
source your site has not vetted, or put the package somewhere `sys.executable`
cannot import it from, and both exit 0 while looking like a fix.

## What it writes

`~/.claude/statusline.js` — your script, byte for byte, when there is one beside
the template. See [The statusline script](#the-statusline-script) above.

`~/.claude/settings.json` — your template, whole. Any file already there is
copied to `settings.json.bk_<timestamp>` beside itself and then **replaced**,
not merged into. Two values are written in on the way past: `ANTHROPIC_AUTH_TOKEN`
gets the token you typed, and `CLAUDE_CODE_GIT_BASH_PATH` is added on Windows.

Replacing rather than merging is the point of the template — a site's settings
are the file the operator wrote, rather than that file plus an unknown residue
of every earlier install. It does mean **`model`, `theme` and any other key you
had hand-edited into `~/.claude/settings.json` are gone**, surviving only in the
timestamped backup. Put anything you want kept into the template. Backups are
never deleted; remove them yourself once you are happy.

`settings.json` is mode `600`, and it is `600`
for the whole of its existence: the temp file it is written through is *created*
`600` rather than created at the umask default and fixed afterwards, and the mode
is settled before the atomic replace publishes it. `~/.claude/` is `0755`, so the
tidier-looking order — write the token, then `chmod` — would leave it readable by
every user on the box for the length of the write, and leave nothing behind to
show it had. On Windows `os.chmod` only toggles the read-only bit and grants no
protection — `lmi` does not pretend otherwise there.

The `lmi.json` it read — `schedule.mode`, set to `sdk` or `cli`. This is written
**last**, after every Claude configuration file has been written successfully,
so the key only ever appears on a machine that got all the way through. The
rest of the document is merged into, never replaced: the `claude` and `lmi`
sections other commands depend on survive untouched.

`~/.claude.json`, one key: `hasCompletedOnboarding` set to `true`. **Lowercase
`b`.** `hasCompletedOnBoarding` is the natural way to write it, and it writes
cleanly, parses cleanly and does nothing — you meet the onboarding flow this
command promised to skip, and the run reports success. A key already exactly
`true` means the file is not rewritten at all: no backup and no churn on a 63 KB
document for a no-op. A key present but `false` is corrected.

Both writes are atomic — temp file beside the target, then `os.replace`. A
half-written `settings.json` is invalid JSON and Claude Code will not start
without it. An existing `~/.claude.json` that is **already** invalid JSON is
refused with exit 3 and left byte-identical, rather than treated as an empty
document and overwritten: that would silently discard everything you had
hand-edited. `~/.claude/settings.json` is the exception, and only because
nothing parses it any more — it is backed up byte for byte and replaced, so an
unparseable one no longer blocks an install that was going to overwrite it.

## Backups

Any file about to be modified, that already exists, is copied first to:

```
<name>.bk_<YYYYmmdd-HHMMSS>
```

— `settings.json.bk_20260806-141530`, `statusline.js.bk_20260806-141530`,
`.claude.json.bk_20260806-141530`. The copy
preserves the mode, because `~/.claude.json` is `600` and holds your per-project
history; a backup at the default 644 would publish it. If a backup fails, **the
file it was for is not modified** and the run stops there with exit 3: changing a
file we could not preserve first is not worth the risk.

Every backup is reported by full path at the end of the run, which is normally
the only moment you learn that a file you may want back exists. Normally, because
that summary is printed only when the run reaches the end: if a later step fails,
backups already taken are on disk but never announced. On a run that ended with
an error, look for `.bk_` beside `~/.claude/settings.json` and `~/.claude.json`
rather than assuming there is nothing there. **They are never pruned.**
A provisioning tool that deletes your previous configuration to keep a directory
tidy has its priorities backwards.

## Git Bash — Windows only

`CLAUDE_CODE_GIT_BASH_PATH` is resolved by Claude Code through
`require("path/win32")` and is **never read on Linux or macOS**. So on those
platforms this work does not run at all — not "runs and no-ops": nothing is
probed, `setx` is never called, and the variable never appears in
`settings.json`, where it would just be a meaningless line in a file you read.

Claude Code's own detection checks exactly two paths —
`C:\Program Files\Git\bin\bash.exe` and the `(x86)` variant — so a Git installed
anywhere else is invisible to it. That is what makes searching harder worth
doing. In order, first hit wins: an existing valid `CLAUDE_CODE_GIT_BASH_PATH`,
`InstallPath` from `HKLM\SOFTWARE\GitForWindows` in both registry views, the two
paths above, `C:\Program Files\Git\usr\bin\bash.exe`, a per-user install under
`%LOCALAPPDATA%\Programs\Git`, and finally a path derived from `where git`.

Every candidate is validated **the way Claude Code validates**: the basename must
be one of `bash.exe`, `sh.exe`, `bash`, `sh`, and the file must exist. Anything
else it warns about and ignores — so writing a path it rejects is worse than
writing nothing, because the machine looks configured and is not. The same check
is applied to the path you type at the prompt.

What is found is persisted twice, for different reasons: `setx` for the user
environment variable, so every future shell has it, and `settings.json` `env`, so
it applies however `claude` is launched. A failed `setx` is a `[WARN]`, not a
failed install — npm has already succeeded by then, and the `settings.json` half
still takes effect.

## When it does not work

- **`npm install -g` failed with `EBUSY`, `resource busy or locked`.** Claude
  Code is running. A running program's files cannot be replaced, so a repair
  install fails until every session is closed — other terminals, your editor's
  Claude Code extension, any `lmi schedule` run. Close them all and run
  `lmi install claude` again. This is **not** a permissions problem: an
  Administrator shell cannot clear a file lock, and re-running elevated fails
  identically. If it persists, something else is holding the files — antivirus
  scanning the npm prefix as it is written is the usual culprit on a corporate
  machine, and a prefix inside OneDrive or on a network share is the other. A
  half-written install left behind by an earlier failure clears with
  `npm uninstall -g @anthropic-ai/claude-code` before you retry.
- **`npm install -g` failed with `EACCES`.** The global `node_modules` is
  root-owned. Either re-run with `sudo` (an Administrator shell on Windows), or
  give npm a prefix you own — `npm config set prefix ~/.npm-global`, then put
  `~/.npm-global/bin` on your PATH — and run this again. `lmi` never invokes
  `sudo` itself: a provisioning tool that silently escalates is one nobody can
  audit. Note that `npm config set` *does* retry without `--global`, writing
  `~/.npmrc`, which needs no root and still governs every `npm install -g` you
  run. `npm install -g` has no such fallback, on purpose — dropping `-g` does not
  degrade, it installs into `./node_modules` of whatever directory you were in,
  creates no `claude`, and exits 0.
- **"npm reported success but `claude` is not on PATH".** Exit 0 with a `[WARN]`,
  and normally not a problem: this is what the first use of npm's global bin
  directory on a machine looks like, because the running process cannot see a
  PATH change made a moment ago. **Open a new terminal** and run `claude`. If it
  is still missing, add the `bin` subdirectory of `npm prefix -g` to your PATH.
  Exiting non-zero here would fail runs that in fact succeeded.
- **"certificate verification is now OFF".** Your config sets
  `"strict-ssl": false`, so verification is off for **every** npm install by this
  user, not just this one. The risk is not interception from outside — it is that
  anyone on the internal network who can answer as the registry host gets a
  package whose install scripts run. Point `cafile` at your internal CA and drop
  `strict-ssl` to close it. The warning repeats every run, deliberately. `lmi`
  never turns verification off on its own: a config that says nothing about TLS
  leaves the machine's npm alone.

## Exit codes

`0` and `2` mean the same thing for every `lmi` command. `4` matches `schedule`'s
`4` rather than exercising the freedom to differ, because a provisioning script
should not have to learn a per-command definition of "a bug in `lmi`".

| Code | Meaning | Scope |
|---|---|---|
| 0 | Done — including "you declined the repair" and the PATH warning above | global |
| 1 | An npm command failed | `install` |
| 2 | Bad or missing config, npm not on PATH, or no terminal to ask in | global |
| 3 | A Claude config file could not be read, backed up or written | `install` |
| 4 | A bug in `lmi` | `install` |

`3` is separate from `1` on purpose. When a config file cannot be *written*, npm
has already succeeded, so the outcome is a working `claude` with unwritten
settings — partial success, which wants its own code. Folding it into `1` would
report that the install failed.

`3` on its own tells you **nothing** about how far the run got, so do not key a
provisioning script off it as "partially done" — or as "nothing happened". Both
extremes occur:

- `~/.claude/settings.json` cannot be *backed up* — an unwritable `~/.claude/`,
  say — and that is checked before it is replaced, so the failure **there** is
  exit 3 with npm already done and the settings untouched.
- `~/.claude.json` is read *last*, after npm has installed Claude Code and after
  `settings.json` has been backed up and rewritten. An unparseable one **there**
  is exit 3 with the install done, the settings replaced, a
  `settings.json.bk_<stamp>` on disk — and no summary, because the run ends
  before the closing report that would have named it.

The message says which file it was, and every backup is named
`<original>.bk_<timestamp>` beside the original whether it was announced or not.
The exit code does not distinguish the two cases.

## What only a real machine can settle

The suite drives a **fake npm** on an exclusive PATH: it proves the argv, the
order and the exit codes, and proves nothing whatever about the real one. Five
checks need a real machine and are worth doing once per site — see
[Status](status.md#lmi-install-claude-five-checks-per-site).
