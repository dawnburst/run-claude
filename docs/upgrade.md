# `lmi upgrade`

Installs a newer `lmi` from the package index named in the config file, over the
installation it is currently running from — so an installed `lmi` can update
itself with no clone and no access beyond the index that provisioned it.

[← README](../README.md) · [`lmi schedule`](schedule.md) ·
[`lmi install claude`](install-claude.md) · [`lmi config`](config.md) ·
[Status](status.md)

---

```
lmi upgrade [--version VERSION] [--config PATH]
```

It exists because the install scripts need a clone, and the
[install guides](install/) say the clone is disposable — re-cloning it every
time you want a newer `lmi` defeats that.

## The config file

`lmi upgrade` reads the **same config file** as `lmi install claude`, found by
[the same search order](install-claude.md#the-config-file) — but its own
top-level section, `lmi`. Copy [`examples/lmi.json`](../examples/lmi.json) and
point it at wherever your lmi comes from:

```json
{
  "lmi": {
    "index": "https://artifactory.example.com/api/pypi/pypi-virtual/simple/",
    "repo": "https://github.com/dawnburst/run-claude.git",
    "cafile": "/etc/ssl/certs/corp-ca.pem",
    "version_check": true
  }
}
```

| Key | Required | Meaning |
|---|---|---|
| `index` | one of the two | The Python package index to install from — pip's `--index-url`. It **replaces** pip's default index rather than adding to it, so an air-gapped machine cannot silently resolve `lmi` from public PyPI. |
| `repo` | one of the two | A git URL. `lmi upgrade` then installs the newest **version tag** from it, and every command can report when one appears. See [Upgrading from the repository](#upgrading-from-the-repository). |
| `cafile` | no | A CA certificate file — pip's `--cert`. Checked for existence when the config is read, not when pip runs, for the same reason `claude.cafile` is: a typo here would otherwise surface much later as an unrelated TLS error. |
| `version_check` | no | `false` silences the once-a-day "a newer lmi is available" line on this machine. Absent means on. See [Being told a newer version exists](#being-told-a-newer-version-exists). |

**One of `index` and `repo` is required**, and naming neither is exit 2 pointing
at both — lmi does not guess where its own code should come from. With both, the
**repo wins**, and `--source index` overrides that for one run; whichever ran is
named in the output, because both end in the same `Upgraded 0.2.1 → 0.3.0`.

The packaged `default-config/lmi.json` carries a `repo` and deliberately **no
`index`**: `lmi` is not published to public PyPI, so an index there would point a
self-upgrade at a stranger's package that happens to share the name, while a git
URL names one repository and can be confused with nothing.

**Keep that file outside the clone.** The install scripts leave the clone
disposable, and a config at `./config/lmi.json` goes away with it — as does the
`settings.json` beside it. A machine you intend to upgrade in place wants both
at the home level instead, where discovery finds them from any directory:

```bash
mkdir -p ~/.lmi && cp examples/lmi.json ~/.lmi/config.json
# then edit ~/.lmi/config.json: set "lmi.index" to your site's package index
```

`lmi install claude` and `lmi config init` put them there for you when they fall
through to the [packaged default](install-claude.md#the-config-file). That copy
carries `lmi.repo` and no `lmi.index`, for the reason above — so a machine
provisioned from the wheel can already upgrade itself from the repository, and a
site that installs from its own mirror still has one key to add.

## Upgrading from the repository

With `lmi.repo` set, `lmi upgrade` installs the newest version tag in that
repository:

```
Config:  /home/op/.lmi/config.json
Running: lmi 0.2.1, installed in /home/op/.local (user site)
Source:  repo https://github.com/dawnburst/run-claude.git
Newest:  v0.3.0
Replace lmi 0.2.1 with v0.3.0? [y/N]
```

It is **one pip command** — pip clones the repository, builds it and installs
the result:

```
$ python -m pip install --user --index-url <your index> --no-deps       "lmi @ git+https://github.com/dawnburst/run-claude.git@v0.3.0"
```

so the machine needs `git`, and needs nothing else that a wheel install does not
already need. `--version 0.3.0` installs the tag `v0.3.0`; the `v` is added when
you leave it off, so tags are expected to look like `v0.3.0`.

**Tags that are not plain versions are ignored, not ordered.** `nightly`,
`v1.0-rc1` and `release_final` are invisible to this command: there is no
ordering for them that is not a guess. Versions themselves are compared as
numbers, so `0.10.0` is correctly newer than `0.9.0`.

> **The `index` key still matters on an air-gapped machine, even when the repo
> is the source.** pip clones the repository and then builds it in an isolated
> environment that it populates **from a package index** — `setuptools` and
> `wheel` come from there, not from the repository. So a `repo`-only config on a
> machine with no route to PyPI clones successfully and then fails fetching build
> dependencies, which reads like a build error rather than a network one. Set
> both keys: `repo` for the code, `index` for the build. `lmi upgrade` passes
> your `index` and `cafile` to pip on repo installs for exactly this reason, and
> says so in the failure message.

If the repository cannot be reached, or has no version tags, the lookup says so
and pip is asked for the repository's default branch instead — the same
degradation as the index probe: a diagnostic never blocks the thing it
diagnoses.

## Being told a newer version exists

Every lmi command checks, **at most once a day**, whether the repository has a
newer version tag than the one running, and prints one line if it does:

```
[lmi] a newer lmi is available: 0.3.0 (running 0.2.1). Run: lmi upgrade
```

That is all it does. It **never upgrades anything**: an lmi that replaced its own
binary because it noticed a tag would be changing behaviour on a machine nobody
touched, which is the opposite of what an unattended runner is for.

It is printed **before** the command runs, so on a scheduled `lmi schedule` job
it lands in the log beside the header rather than four hours later at the bottom.

| | |
|---|---|
| **What it reads** | `git ls-remote --tags` against `lmi.repo`. No clone, no fetch, nothing written anywhere. |
| **How often** | Once every 24 hours. The answer is cached in `~/.lmi/version-check.json`, keyed by the repo URL so that re-pointing `lmi.repo` does not report the old remote's tags. |
| **How long it may take** | 3 seconds, then it is abandoned. It is the only network call on `lmi schedule`'s startup path, and an unreachable git host must not delay an unattended run. |
| **When it says nothing** | No config file, no `lmi.repo`, no `git`, no network, a timeout, no version tags, a tag or a running version it cannot parse, and `lmi upgrade` itself — which is about to say the same thing with more detail. |
| **Turning it off** | `"version_check": false` in the `lmi` section. Worth doing on an air-gapped machine, where the git host is unreachable by design: it then costs nothing rather than one abandoned lookup a day. |

Every failure inside the check is silent, including the unparseable config file
that `lmi upgrade` itself refuses with exit 2. A line printed before every
command must never be able to break the command — and a check that cried wolf
would teach you to ignore it, so the one that matters would be ignored too.

## What it asks

At most one question, asked **before anything on the machine changes**:
whether to replace the running `lmi` with the version it found (the newest on
the index, or the one named by `--version`). Abandon it there and nothing has
been touched. There is deliberately no `--yes` — this command replaces the
binary that is currently executing it, and that is not something to automate
past. It has the same no-keypress-when-unattended guard as `lmi install
claude`: with no terminal, the question cannot be asked, and rather than hang
forever waiting for one, the command exits 2.

## `--version`

Omit it and `lmi upgrade` asks the index for the newest version. Pass one to
pin an exact version instead — including going **back** to a known-good
version if a newer one turns out to be bad.

An unchanged version number means exactly that: nothing to install, exit 0.
`scripts/install-linux.sh` passes `--force-reinstall` because the version does
not change on every source change during development; `lmi upgrade`
deliberately has no such flag, so if a site republishes `0.1.0` with different
content inside, `lmi upgrade` reports "already at the newest" and changes
nothing. Bump the version in `pyproject.toml` to ship new code.

## What it upgrades, and what it refuses

`lmi upgrade` upgrades exactly the two installation shapes the install scripts
produce:

- a **virtual environment of its own** — `~/.local/share/lmi/venv`, the shape
  `install-linux.sh` and `install-macos.sh` create.
- a **`pip install --user`** install — the shape `install-windows.cmd`
  produces.

Anything else is refused with exit 2, before pip is invoked, rather than
guessed at:

- **An editable checkout** (`pip install -e`, what a repo clone under active
  development looks like). Upgrading it would install a released wheel over a
  working tree — it would look exactly like a successful upgrade while
  discarding whatever is uncommitted there.
- **A pipx install.** Upgrading it from underneath pipx would leave pipx's own
  record describing a version that is no longer installed. The message says to
  run `pipx upgrade lmi` instead.
- **Anything else** — a system-wide install, in particular. A wrong guess here
  installs a second copy that nothing on `PATH` ever reaches, which is worse
  than refusing.

## Verification

Success is confirmed by running the **installed console script** in a fresh
subprocess and reading what it reports — never by reading this process's own
`lmi.__version__`. That value was imported before pip ran, so it is always the
*old* version, whatever pip just put on disk: a command that trusted it would
report "upgraded 0.1.0 → 0.2.0" while 0.1.0 was still what ran.

## Exit codes

`0` and `2` mean the same thing for every `lmi` command; `4` matches
`schedule`'s and `install`'s.

| Code | Meaning | Scope |
|---|---|---|
| 0 | Upgraded, already at the newest (or the requested) version, or you answered no | global |
| 1 | The pip install failed | `upgrade` |
| 2 | Bad config, an installation shape `lmi upgrade` cannot handle, no terminal to ask in, Ctrl-C at the prompt, or a bad `--version` | global |
| 3 | pip succeeded, but the installed command now reports the wrong version | `upgrade` |
| 4 | A bug in `lmi` | `upgrade` |

`3` is separate from `1` on purpose: by the time verification runs, pip has
already succeeded and the machine has changed, so "the upgrade failed" would be
the wrong sentence for what happened.

Whether pip can displace a running `lmi.exe` on Windows is not yet settled —
see [Status](status.md#still-to-verify).

---

---
