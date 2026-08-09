# lmi — design (`lmi upgrade`, the CLI upgrading itself)

**Date:** 2026-08-09
**Status:** designed, not implemented.

Today the only way to upgrade `lmi` is to re-run an install script, which needs
a clone — and the install guides say the clone is disposable. On a provisioned
machine there is nothing left to re-run. This adds `lmi upgrade`: one command
that fetches a newer `lmi` wheel from the site's internal Python index and
installs it over the installation it is currently running from.

It is the same shape as `lmi install claude` seen from the other side. That
command provisions Claude Code from an internal npm registry named in a config
file; this one provisions `lmi` from an internal PyPI index named in the same
file.

---

## 1. Goal and non-goals

**Goal.** On a machine with no checkout, `lmi upgrade` replaces the running
`lmi` with a newer one from the internal index, having said what it was about
to do and been told to go ahead — and refuses to report success unless the
installed command actually answers with the new version.

**Non-goals.**

- **No `--check` mode**, and **no nudge from other commands.** `lmi schedule`
  and `lmi install` make no network call to see whether an upgrade exists.
  A background version check on an unrelated command needs caching, an opt-out
  and a failure mode of its own, and nobody asked for one.
- **No new installation shapes.** `lmi upgrade` upgrades the two shapes the
  install scripts produce, and refuses everything else (§3). It never creates an
  installation, never touches `PATH`, and never creates or moves the symlink.
- **No repair or reinstall.** Asking pip to install the version that is already
  installed is a no-op that reports "already up to date". Repairing a damaged
  installation is the install scripts' job.
- **No new runtime dependencies.** Standard library only, Python 3.9 floor, as
  everywhere else.
- **`lmi upgrade` does not upgrade Claude Code.** `npm install -g` always
  fetches the newest, so `lmi install claude` is already that command.

---

## 2. Command surface

```
lmi upgrade [--version VERSION] [--config PATH]
```

A new self-contained package `lmi/commands/upgrade/`, registered by one line in
`commands/__init__.py`. `cli.py` is not edited.

**No positional target.** `lmi install` takes one (`claude`) because it could
plausibly install other things; `lmi upgrade` has exactly one meaning, since
claude's upgrade path is `lmi install claude`. A target slot left empty in
anticipation would be a worse guess than adding one later.

- **no `--version`** — the newest version the index offers.
- **`--version 0.1.0`** — exactly that version, downgrades included. This is the
  way back from a bad upgrade, and the reason `--version` exists at all.
- **target equals the running version** — say so, exit 0, change nothing.
- **`--config PATH`** — identical to `lmi install`'s flag, including the rule
  that an explicit path which does not exist is an error and never falls
  through to the next candidate.

---

## 3. Which installation is this?

Worked out before anything else happens, and before the user is asked anything,
because a wrong answer here is silent: pip reports success, the command still
runs, and it is either the old code or a second copy nothing on `PATH` reaches.

Checked in this order:

1. **An editable checkout** — `importlib.metadata`'s `direct_url.json` reports
   `dir_info.editable`. **Refused, exit 2.** Installing a released wheel over a
   developer's working tree looks like a successful upgrade and replaces
   uncommitted work with a build from the index. Checked first because a dev
   checkout is usually *also* inside a virtual environment, so rule 3 would
   otherwise claim it.
2. **pipx** — `pipx_metadata.json` at `sys.prefix`. **Refused, exit 2**, naming
   `pipx upgrade lmi`. Upgrading behind pipx leaves its metadata describing a
   version that is no longer installed.
3. **A virtual environment** — `sys.prefix != sys.base_prefix`. This is what
   `install-linux.sh` and `install-macos.sh` produce:
   `~/.local/share/lmi/venv`, with `~/.local/bin/lmi` symlinked into it. pip is
   `<prefix>/bin/python -m pip`, falling back to
   `python3 -m pip --python <prefix>/bin/python` when that venv has no pip of
   its own — the `--without-pip` case that Debian and Ubuntu force, handled
   exactly as `install-linux.sh` already handles it.
4. **A user-site install** — `lmi.__file__` under
   `site.getusersitepackages()`. This is what `install-windows.ps1` produces.
   pip is `sys.executable -m pip install --user`.
5. **Anything else** — a system-wide `site-packages`, something unpacked by
   hand. **Refused, exit 2**, naming what was found. Guessing `--user` here
   writes a second copy that the `PATH` entry never reaches, and reports
   success for it.

The symlink is never touched. Replacing the package inside the venv leaves
`<venv>/bin/lmi` at the same path, so the link stays valid; `PATH` is not this
command's business.

---

## 4. Replacing the code that is running

**One pip command, aimed at the installation in place.** No staging directory,
no second venv, no detached helper.

```
<pip> install --index-url <index> [--cert <cafile>] --no-deps [--user] lmi==<version>
```

The requirement is **pinned** — `lmi==<version>` — whenever a target version is
known, which is every case except one: `--version` was not given *and* the
probe in §7 step 2 could not answer. There, and only there, it is `--upgrade
lmi` and pip resolves the newest itself. Pinning by default is what makes the
verification in §8 an equality check rather than a hope.

A list argv through `subprocess.run`, never `shell=True` — the index URL comes
from a config file and must not reach a shell. `check=False`, so a non-zero exit
returns rather than raising. Output is **inherited**, not captured, so pip's own
progress and errors reach the user as they happen, exactly as `npm._run` does.

Two alternatives were considered and rejected.

**Blue/green** — install into `<venv>.new`, verify it, flip the symlink — is
genuinely safer on Unix: nothing under the running process is touched and
rollback is a symlink flip. It does not exist on Windows, where there is no
symlink and no venv, so Windows would fall back to the in-place path anyway and
the command would carry two mechanisms for one job. It also re-creates a venv on
every upgrade, on machines where creating the first one was already a fight.

**A detached helper** that upgrades after `lmi upgrade` exits dodges
self-replacement completely, and exits 0 before it knows whether the upgrade
worked. A command that reports success without knowing is the failure mode
`CLAUDE.md` §3 exists to prevent.

Two hazards come with the in-place choice, and both are handled rather than
hoped away.

**This process is editing its own files.** Already-imported modules stay in
memory; a module imported *after* pip runs would come from the new version, in
the same process as old modules already loaded. So `upgrade` imports everything
it needs before invoking pip, and does nothing after pip returns but run one
subprocess and print. This is a rule about the module, not an accident of how it
is written today, and belongs in a comment there.

**On Windows, pip has to displace the `lmi.exe` that is currently executing.**
pip stashes files by renaming them rather than overwriting, and Windows permits
renaming a running image on the same volume, so this is expected to work — but
"expected" here is the same class as every other Windows item in this project,
and only a real Windows run settles it. §8 says what happens when it does not,
and §9 puts it on the README's outstanding list rather than claiming it works.

---

## 5. Configuration

A new top-level section beside `claude`, in the same `lmi.json`:

```json
{
  "lmi": {
    "index": "https://artifactory.example.com/api/pypi/pypi-virtual/simple/",
    "cafile": "/etc/ssl/certs/corp-ca.pem"
  },
  "claude": { }
}
```

| Key | Required | Meaning |
|---|---|---|
| `index` | **yes** | The Python package index to install from — pip's `--index-url`. |
| `cafile` | no | A CA certificate file — pip's `--cert`. Validated at config time, not at pip time. |

**`--index-url`, not `--extra-index-url`.** It replaces the default index rather
than adding to it, so an air-gapped machine cannot silently resolve `lmi` from
public PyPI. `cafile` is checked for existence when the config is read, for the
reason `claude.cafile` is: a typo in a certificate path succeeds at
configuration time and surfaces much later as an unrelated TLS error.

**There is deliberately no TLS-off fallback.** `lmi install` has one because
`npm config set strict-ssl false` was the only way to make an existing npm setup
work, and it prints the loudest warning in the codebase. Nothing forces a new
one here: without a `cafile`, pip uses its own CA bundle, and a site whose index
has a private CA sets `cafile`.

**`--no-deps` is always passed.** `lmi` declares no dependencies and
`tests/test_packaging.py` fails if that ever stops being true, so the flag
changes nothing about a correct install — and it means a wrong or tampered
package on the index cannot pull anything else onto the machine.

---

## 6. Promoting config discovery and prompts into `core/`

`CLAUDE.md` §2 says `core/` is for code with no command flavour, and that
something command-specific is promoted when a second command needs it — "then,
not in advance". Two things reach that condition here.

**Config discovery.** Finding the file across `--config`, `$LMI_CONFIG`,
`./config/lmi.json` and `~/.lmi/config.json`; refusing a file left at the
pre-move `./lmi.json`; the tilde expansion that survives `RuntimeError`; the
`fs.classify` path checks that survive `ENAMETOOLONG`; BOM-aware decoding; JSON
parsing. None of that is about npm. It moves to `core/config.py`. Each command
keeps its own section validation and its own `EXAMPLE`, and the "no config file
found" error takes the calling command's example so an operator still gets
something to paste.

Every behaviour in `CLAUDE.md` §3 item 21 and in the `--config`-does-not-fall-
through rule moves with it unchanged, and the tests that pin them move with it
too.

**Prompts.** `install/prompts.py` is a yes/no question, a text question, a
secret question and the guard that turns `EOFError` into exit 2 rather than a
hang, plus Ctrl-C into "cancelled — nothing was changed". `upgrade` wants the
first of those and both halves of the guard, verbatim. Duplicating a guard is
how one copy of it comes to be missing. `prompts.py` moves to `core/prompts.py`;
its `NO_TERMINAL` text names the calling command rather than hard-coding
`lmi install`.

`examples/lmi.json` gains the `lmi` section and becomes the union of what both
commands document. `tests/test_docs.py` currently pins one `EXAMPLE` against the
whole file; it changes to pin each command's `EXAMPLE` against its own section,
so the two cannot drift and neither one has to know about the other.

**The `~/.lmi/config.json` consequence.** The README says the clone is
disposable once an install script has run. That stays true, but only if the
config lives at `~/.lmi/config.json` — `./config/lmi.json` goes away with the
clone. `lmi upgrade` on a machine with neither gets the existing "no config file
found" error, which lists where it looked and prints a minimal file. That is a
documentation change, not a code one, and §9 records it.

---

## 7. The flow

The same two-part shape as `install/runner.py`: **ask everything, change
nothing; then change things.** A user who abandons the command at the prompt, or
answers no, leaves the machine exactly as they found it.

1. **Read the config and work out the shape** (§3, §5). Both can fail before
   anything has happened.
2. **Work out the target version.**
   - With `--version`, it is already known. If it equals the running version,
     say so and exit 0 — without a network call.
   - Without `--version`, ask the index: `pip index versions lmi --index-url …`.
     That is a read with no side effects. If it answers with the running
     version: "already up to date", exit 0, nothing changed. If it answers with
     something newer, the question in step 3 names both versions.
   - **If that probe fails for any reason it is not an error.** An older pip
     without the subcommand, changed output, the experimental-command warning —
     any of them, and the question is asked naming the index but not the target
     version, and pip resolves the newest itself. A diagnostic must never block
     the thing it was diagnosing.
3. **Ask.** The running version, the target (when known), the index, and the
   installation about to be replaced. No `--yes`, matching `lmi install`; no
   terminal is exit 2 rather than a wait, matching it again. Answering no is
   exit 0 — the user answered rather than erred.
4. **From here the machine changes.** One pip command (§4).
5. **Verify** (§8).
6. **Report** what landed. Mirroring the installer's own final check, warn if
   `shutil.which("lmi")` resolves to something other than the file just
   upgraded — another `lmi` earlier on `PATH` means the upgrade was real and
   invisible.

---

## 8. Verification, and never trusting our own version string

After pip returns 0, `upgrade` runs the **installed console script** as a
subprocess — `<venv>/bin/lmi --version`, or `lmi.exe` in the user Scripts
directory, located with the same `sysconfig` probe `install-windows.ps1` uses
rather than by guessing `%APPDATA%\Python\PythonXX\Scripts` — and checks that it
answers with the expected version.

**It must never use `lmi.__version__`.** This process imported that before pip
ran, so it reports the old version no matter what is now on disk. A command that
reads its own in-memory version and announces an upgrade would be the
stale-wheel bug rebuilt deliberately: success reported, old code installed,
nothing on screen to suggest otherwise.

Without `--version` the expected value is whatever the probe in §7 step 2 found;
if the probe failed, there is no expectation to check, and verification asserts
only that the installed command runs and reports a version — which still catches
a broken install, just not a stale one. Where a version *is* expected and does
not match, that is exit 3.

---

## 9. Exit codes

| Code | Meaning |
|---|---|
| 0 | upgraded; or already up to date; or the user answered no |
| 1 | pip failed |
| 3 | pip reported success, but the installed command does not run or reports the wrong version |
| 4 | a bug in lmi |
| 2 | no config file, an invalid config file, an installation shape that cannot be upgraded, or no terminal |

3 is separate from 1 for the reason `lmi install` separates them: by the time
verification runs, the machine has already changed, so "the upgrade failed"
would be the wrong sentence. 4 keeps the meaning it has in both existing
commands.

An unsupported installation shape is **2, not a new code**: `lmi install`
already reports a missing npm — an environmental precondition the user can fix —
as a usage error, and a provisioning script should not have to learn a third
meaning.

The exit-1 message follows `npm.INSTALL_FAILED`'s two-hypothesis shape, since
pip's own output is immediately above it:

- the index, if pip reported a network error or a 404 — check `lmi.index` in the
  config file, and that the index really carries `lmi`; lmi does not populate
  it;
- **on Windows**, the `lmi.exe` being replaced is the one currently running,
  with the exact `python -m pip install --user --upgrade --index-url … lmi`
  line to run from a shell where no `lmi` is live.

The Windows clause is printed **on every Windows failure, without inspecting
pip's text**. Pattern-matching an error message to decide whether to offer help
is a guess that goes stale with the next pip release; an extra clause on a
platform where it is plausible costs nothing.

---

## 10. Testing

A `fake_pip` fixture in the spirit of `fake_npm`. pip is not resolved through
`PATH` — it is `<interpreter> -m pip` — so the seam is the interpreter: the
module resolves it through one function, and tests point that at a recording
fake which logs argv and answers `--version`. The suite's rule that no test may
reach a real `claude` gains its sibling: **no test may reach a real pip or a
real index.**

Four cases are **MANDATORY** in this project's sense, one per silent failure
this design creates:

1. **An editable checkout is refused and pip is never invoked.** The failure it
   pins: a developer's working tree replaced by a wheel, reported as success.
2. **A pipx installation is refused and pip is never invoked.** The failure:
   pipx's metadata left describing a version that is gone.
3. **pip exits 0 while the installed command still reports the old version →
   exit 3, and success is not reported.** The failure: the stale-wheel bug,
   reached through a different door.
4. **Answering no runs no pip and changes nothing, and exits 0.** The same
   guarantee as `CLAUDE.md` §3 item 16.

Also covered: the argv carries `--index-url`, `--cert`, `--no-deps` and
`lmi==<version>`; `--user` appears for the user-site shape and never for the
venv shape; the `--without-pip` venv falls back to
`python3 -m pip --python <venv>/bin/python`; a config file with no `lmi` section
is exit 2 and prints the example; no terminal is exit 2 and not a hang; a
failing pip is exit 1 and reports no success; `--version` equal to the running
version makes no pip call at all.

The tests that currently pin config discovery and the prompt guard move with
those modules into the `core/` suite unchanged, so §6 cannot quietly lose one.

---

## 11. Documentation

- **README**: an `lmi upgrade` section — what it does, the config keys, the
  question it asks, its exit-code table — plus the `lmi` section in the config
  key table and in `examples/lmi.json`, and the `~/.lmi/config.json` caveat on
  "the clone is disposable" (§6).
- **README, "Still to verify"**: whether pip can displace a running `lmi.exe` on
  Windows (§4). This design cannot settle it from Linux, and the list exists for
  exactly this.
- **README, "Known limitations"**: upgrading while an `lmi schedule` loop is
  running replaces files underneath it. Its imported modules stay in memory, but
  one it has not yet imported would come from the new version. The locks are per
  state file in arbitrary directories, so there is nothing to enumerate and no
  honest way to detect it. Upgrade between runs, not during one.
- **`CLAUDE.md` §3**: the new silent failures — a self-reported version (§8), a
  guessed installation shape (§3) — and §2 gains the note that config discovery
  and prompts now live in `core/` because a second command needed them.

---

## 12. Decisions

1. **The source is an internal PyPI index named in `lmi.json`**, mirroring how
   `lmi install claude` names its npm registry. §5.
2. **In-place pip, not blue/green and not a detached helper.** §4.
3. **Two installation shapes are supported; everything else is refused, not
   guessed at.** §3.
4. **The command asks before it changes anything, and has no `--yes`** — the
   contract `lmi install` set. §7.
5. **Success is confirmed by running the installed command**, never by reading
   our own `__version__`. §8.
6. **The version probe is best-effort**; its failure degrades the question, not
   the command. §7.
7. **`--index-url` and `--no-deps` always; no TLS-off fallback.** §5.
8. **Config discovery and prompts move to `core/`**, because a second command
   now needs them. §6.
9. **The Windows running-`.exe` question is recorded as outstanding**, not
   assumed. §4, §11.

**Open questions:** none.
