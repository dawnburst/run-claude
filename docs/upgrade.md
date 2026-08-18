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
top-level section, `lmi`. The
shipped `default-config/lmi.json` in this repository does **not** have one: `lmi` is
never published anywhere, so the only honest default is none at all rather
than a placeholder that would resolve a stranger's package of the same name
from public PyPI. Copy [`examples/lmi.json`](../examples/lmi.json) and point
`lmi.index` at your site's own package index:

```json
{
  "lmi": {
    "index": "https://artifactory.example.com/api/pypi/pypi-virtual/simple/",
    "cafile": "/etc/ssl/certs/corp-ca.pem"
  }
}
```

| Key | Required | Meaning |
|---|---|---|
| `index` | **yes** | The Python package index to install from — pip's `--index-url`. It **replaces** pip's default index rather than adding to it, so an air-gapped machine cannot silently resolve `lmi` from public PyPI. |
| `cafile` | no | A CA certificate file — pip's `--cert`. Checked for existence when the config is read, not when pip runs, for the same reason `claude.cafile` is: a typo here would otherwise surface much later as an unrelated TLS error. |

**Keep that file outside the clone.** The install scripts leave the clone
disposable, and a config at `./config/lmi.json` goes away with it — as does the
`settings.json` beside it. A machine you intend to upgrade in place wants both
at the home level instead, where discovery finds them from any directory:

```bash
mkdir -p ~/.lmi && cp examples/lmi.json ~/.lmi/config.json
# then edit ~/.lmi/config.json: set "lmi.index" to your site's package index
```

`lmi install claude` puts them there for you when it falls through to the
[packaged default](install-claude.md#the-config-file) — but that copy carries no
`lmi` section, for the reason above, so this stays a deliberate step.

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
