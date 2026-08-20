# lmi — design (`lmi upgrade` from the repo, and a daily availability notice)

**Date:** 2026-08-20
**Status:** designed.

`lmi upgrade` installs a released wheel from a package index. That is right for
a site that mirrors lmi into Artifactory, and useless for one whose lmi lives in
a git repository and nowhere else — there is no index to publish to, so the only
way to move a machine forward is to clone, build and install by hand.

And nothing tells an operator that a newer lmi exists at all. `lmi upgrade` says
so, once you run it; the machines that most need upgrading are the ones running
`lmi schedule` under a scheduler, where nobody types `lmi upgrade` speculatively.

Two halves, one config section:

1. **`lmi upgrade` can install from the repo** — one pip invocation that clones,
   builds and installs a tag.
2. **Every command reports, at most once a day, that a newer version exists** —
   and suggests `lmi upgrade`. It never runs it.

---

## 1. Goal and non-goals

**Goal.** `lmi.repo` in the config file names a git URL. `lmi upgrade` then
installs the newest **version tag** from it, and every other lmi command prints
one line when the repo has a tag newer than the running version.

**Non-goals.**

- **No auto-upgrade, ever.** The notice suggests a command; it does not run one.
  A tool that replaces its own binary because it noticed a tag is a tool that
  changes behaviour on a machine nobody touched, which is the opposite of what
  an unattended runner is for.
- **No clone, no build toolchain, no wheel handling of lmi's own.** `pip install
  "lmi @ git+<url>@<tag>"` does all three in one command that already has
  everything this command needs — the `--user` flag, `--no-deps`, the
  installation-shape refusals, the subprocess verification. Hand-rolling
  `git clone` + `python -m build` + install-the-wheel is three new failure modes
  for the same result.
- **No new command.** `lmi upgrade` gains a source; the notice belongs to no
  command at all.
- **No branch tracking, no commit comparison.** The newest *version tag*, and
  nothing else, because a version number is the only thing that can be compared
  with the version that is running. §4 says what that costs.
- **No index-vs-repo migration.** Both sources stay. A site that mirrors lmi
  keeps working, unchanged and unasked.
- **No new runtime dependency, no network library.** `git` is invoked as a
  subprocess when it is present; `subprocess`, `json` and `re` are stdlib. Python
  3.9 floor unchanged.

---

## 2. Configuration

The `lmi` section, which `lmi upgrade` already owns:

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

| Key | Meaning |
|---|---|
| `index` | As today. **No longer mandatory** — but one of `index` and `repo` must be present, or the command exits 2 naming both. |
| `repo` | A git URL pip can install from. Its presence is what makes the repo the source, and what enables the notice. |
| `cafile` | As today, and now passed on repo installs too — see §3's build-isolation rule. |
| `version_check` | `false` turns the notice off for this machine. Absent means on. `null` is exit 2, the `_MISSING` sentinel rule in its sixth home. |

**`repo` wins when both are configured**, and `--source index` overrides it for
one run. Not because the repo is better, but because a rule an operator can
state beats a precedence they have to discover — and the header names the source
either way (§5), since "Upgraded 0.2.1 → 0.3.0" looks identical whichever one
ran.

`lmi.repo` is **never inferred**. A machine with no `repo` key behaves exactly as
it does today, notice included: nothing to check, so nothing is said. The
packaged `install/default-config/lmi.json` will carry the public repo URL, which
is item 48's precedent rather than an exception to item 38 — a value written in
a file the operator can read, print and edit, not a default reached for in code
when a key is missing.

---

## 3. Installing from the repo

```
pip install --user --no-deps --upgrade  \
    --index-url <index> [--cert <cafile>]  \
    "lmi @ git+https://…/run-claude.git@v0.3.0"
```

`--version 0.2.0` installs `@v0.2.0`, so going back to a known-good version
keeps meaning what it means today. The `v` prefix is added when the tag carries
one and the argument does not — §4 owns that spelling, in one place.

**The index arguments are passed on a repo install too, and that is the
load-bearing part of this section.** pip builds a source tree in an isolated
environment which it populates *from an index* — so `pip install git+https://…`
on an air-gapped machine clones successfully and then fails fetching
`setuptools`, at a point that reads like a build error rather than a network
one. Passing the site's own `--index-url` puts the build dependencies where
every other package on that machine comes from. Without it this feature works
only where there is internet, which is the one environment lmi was not written
for.

When no `index` is configured the arguments are simply absent and pip uses its
default, which is the right behaviour for the internet-connected case and the
only possible one for a config that named a repo and no index.

Everything else is unchanged and must stay so: `--no-deps` (lmi declares no
dependencies and `test_packaging.py` enforces it), the `--user` flag when the
installation is a `--user` one, `installation.detect`'s refusals for editable,
pipx and system installs — all of which run **before** pip — and
`verify.confirm`, which runs the installed console script in a subprocess and
compares versions.

**A tag is not evidence** (item 22, unchanged and now easier to get wrong): the
tag says what was asked for, the subprocess says what is installed. A tag whose
`pyproject.toml` disagrees with its own name would otherwise report a successful
upgrade to a version that is not there.

---

## 4. What "newest" means

`git ls-remote --tags <repo>`, whose output is one `<sha>\trefs/tags/<name>` per
line. Names matching `v?N(.N)*` are parsed into integer tuples; the largest
wins. Everything else — `nightly`, `v1.0-rc1`, `release_final` — is **ignored
rather than ordered**, because there is no ordering for it that is not a guess.

**Comparison is between integer tuples, never strings.** `"0.10.0" > "0.9.0"` is
false as a string, and a comparison that says a machine is up to date when it is
not is the failure this feature exists to remove.

**Every uncertainty resolves to silence.** No `repo` key, no config file, no
`git` on PATH, no network, a timeout, an exit code, no parseable tag, an
unparseable running version — all of them mean the notice says nothing and the
command carries on. The reason is not politeness: a notice that cries wolf
teaches operators to ignore it, and then the one that matters is ignored too. The
same asymmetry as `[QUOTA]`, in the other direction — there, under-reporting was
the danger; here, over-reporting is.

`--version` is compared the same way, so `lmi upgrade --version 0.9.0` on a
machine running `0.10.0` is told it would be a downgrade rather than being
silently treated as an upgrade.

---

## 5. What `lmi upgrade` prints

```
Config:  /home/op/.lmi/config.json
Running: lmi 0.2.1, installed in /home/op/.local (user site)
Source:  repo https://github.com/dawnburst/run-claude.git
Newest:  v0.3.0
```

`Source:` replaces the current unconditional `Index:` line and names which of
the two ran, for item 33's reason applied to a third switch: both sources end in
the same "Upgraded 0.2.1 → 0.3.0", so nothing else in the output distinguishes a
machine upgraded from the site's audited mirror from one upgraded off a git
branch. `Newest:` appears only when the lookup answered.

---

## 6. The notice

One line, before the command runs:

```
[lmi] a newer lmi is available: 0.3.0 (running 0.2.1). Run: lmi upgrade
```

**Before dispatch, not after.** A notice printed after a four-hour
`lmi schedule` run is a notice nobody reads, and printed before it lands in that
run's log beside the header an operator already looks at.

**Cached, so the network is touched at most once a day.** `~/.lmi/version-check.json`:

```json
{"checked": "2026-08-20T09:14:02", "repo": "https://…", "latest": "0.3.0"}
```

The cached answer is reused until it is 24 hours old, and it is keyed by the repo
URL so that changing `lmi.repo` invalidates it rather than reporting the old
remote's tags. A cache that cannot be read is a cache miss; a cache that cannot
be written is a lookup that happens again tomorrow. Neither is an error, and both
go through `core/jsonfile.py`, so the file inherits the atomic write and the 0600
birth mode rather than a hand-rolled `open`.

**Bounded and unfailing.** `subprocess.run(..., timeout=3)`, output discarded on
any non-zero exit, every exception caught. Invariant 3 is untouched: this is a
bounded subprocess, not a wait for a person — but it is also the only network
call on `lmi schedule`'s startup path, so the timeout is not optional and the
cache is what keeps it from being paid twice.

**Never when the command is `lmi upgrade`.** That command is about to say the
same thing with more detail, and having asked for it is not a reason to be told.

**Suppressed by `"version_check": false`**, for a machine that would rather not
spend one failed lookup a day — which is exactly the air-gapped case, where the
git host is unreachable by design.

### Where it lives, and the precedent it sets

`lmi/commands/upgrade/notice.py`, called by one line in `lmi/cli.py`.

`cli.py` has never imported a command, and the rule that it must not learn about
one is real. This is the narrowest possible breach of it and the alternative is
worse. The notice has to know the package, the repo URL, the `lmi` config
section and how two versions compare — every one of which `commands/upgrade/`
already defines. A second spelling anywhere in that list is a notice that
suggests upgrading to something `lmi upgrade` would not install, and the operator
who follows the suggestion finds nothing wrong afterwards.

It is the same trade as three commands importing `schedule/backend.py`, and it
is bounded in the same way: `cli.py` learns nothing about the command
**registry**, gains no second import, and the call is one line with a bare
`except` around nothing but a diagnostic.

---

## 7. New must-not-regress items (CLAUDE.md section 3)

Appended as 60–63.

60. **The index arguments are passed on a repo install.** pip's build isolation
    resolves `setuptools` from an index, so a `git+` install with no
    `--index-url` clones successfully and then fails fetching build
    dependencies. **Not silent — but it reads as a build failure rather than a
    network one**, on the machines least able to fetch from PyPI, and the
    hypothesis it sends an operator chasing is the wrong one.
61. **Every uncertainty in the version lookup is silence.** No repo, no git, a
    timeout, an unparseable tag, an unparseable running version. **Silent in the
    corrosive direction:** a false "a newer lmi is available" is indistinguishable
    from a true one, and after the second false alarm the line is noise - so the
    real one, months later, is ignored too. Versions are compared as integer
    tuples, never as strings: `"0.10.0" > "0.9.0"` is false.
62. **The notice never becomes an action, and never fails a command.** It
    suggests `lmi upgrade`; it does not run it, does not prompt, and every
    failure inside it is swallowed. It is also the only network call on `lmi
    schedule`'s startup path, so the `timeout=3` and the 24-hour cache are both
    load-bearing: without them a slow git host delays the first iteration of an
    unattended run, which is invariant 3's spirit even though no keypress is
    involved.
63. **A tag is still not evidence of an upgrade.** Item 22, restated because a
    git source makes it easier to get wrong: the tag is what was asked for, and
    the only thing that says what is installed is `verify.confirm` running the
    installed console script in a subprocess. `--source` is named in the output
    for item 33's reason - both sources print the same "Upgraded X -> Y".

---

## 8. Testing

- **A `fake_git` fixture**, in the shape of `fake_npm`: an exclusive `PATH`, argv
  recorded per call, and `FAKE_GIT_TAGS` / `FAKE_GIT_RC` / `FAKE_GIT_HANG` so the
  three interesting answers — a tag list, a failure, a timeout — are all
  reachable without a network.
- **`fake_pip` already records every argv**, so the repo install is asserted
  there: the `lmi @ git+…@v0.3.0` requirement, the `--index-url` beside it, and
  `--no-deps` still present.
- **MANDATORY**, one per item above: the index argument on a repo install; the
  tuple comparison (`0.10.0` newer than `0.9.0`, and `0.9.0` not newer than
  `0.10.0`); each uncertainty producing no line and exit 0; the notice absent for
  `lmi upgrade` itself; a hanging git not delaying a second command (cache) and
  not failing the first (timeout); `verify.confirm` still deciding success.
- **`test_docs.py`** grows needles for `lmi.repo`, `version_check` and the
  packaged config folder carrying the repo URL — the last one because
  `install/default-config/lmi.json` is what a plain `pip install lmi` gets, and a
  key missing there is a feature that silently does not exist.
- Both suite figures re-measured and written down, the way section 4.1 requires.

---

## 9. Open questions

None. Two things are deliberately left for a real run and belong in
`docs/status.md` rather than here: whether the site's git host is reachable from
the machines that run `lmi schedule` at all, and whether a `git+` install
succeeds there once the build dependencies come from the site's own index — which
is §3's whole point and cannot be proven by a fake.
