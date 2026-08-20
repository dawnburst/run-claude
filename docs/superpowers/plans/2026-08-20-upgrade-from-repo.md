# `lmi upgrade` from the repo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development) to implement this plan task-by-task.

**Goal:** `lmi upgrade` installs the newest version tag from a git repo, and every command reports once a day that a newer one exists.

**Architecture:** One pip invocation (`lmi @ git+<url>@<tag>`) does clone, build and install, with the site's index passed for build dependencies. A new `upgrade/repo.py` owns the remote-tag lookup and version comparison; `upgrade/notice.py` owns the cached daily check and is called by one line in `cli.py`.

**Tech Stack:** Python 3.9, stdlib only (`subprocess`, `re`, `json`), `git` as an optional external binary, pytest with a new `fake_git` fixture.

**Spec:** `docs/superpowers/specs/2026-08-20-upgrade-from-repo-design.md`

## Global Constraints

- Python 3.9 floor, stdlib only; `dependencies = []` stays true; `--no-deps` stays on every install.
- Silence on every uncertainty in the lookup (spec §4, item 61). Never an error, never a guess.
- The notice never runs a command, never prompts, never fails one (item 62), and is bounded by `timeout=3` plus a 24-hour cache.
- `installation.detect`'s refusals and `verify.confirm`'s subprocess check are untouched (item 63).
- Suite after every task: `python3 -m pytest tests/ -q`. Baseline entering this work: **859 passed, 21 skipped** (879 / 1 with the SDK importable).
- No test may reach a real `git`, a real `pip` or a real network: `fake_git` and `fake_pip` replace `PATH` and the interpreter respectively.

---

### Task 1: `upgrade/repo.py` — the remote's newest tag, and version order

**Files:** create `lmi/commands/upgrade/repo.py`; create `tests/commands/upgrade/test_repo.py`; add `fake_git` to `tests/conftest.py`.

**Produces:** `repo.parse_version(text) -> Optional[tuple]`, `repo.is_newer(candidate, running) -> bool`, `repo.newest_tag(url, timeout=…) -> Optional[Tag]` where `Tag` is a NamedTuple `(name, version)`, `repo.TIMEOUT`.

Steps: write the tests (tuple order including `0.10.0` vs `0.9.0`; `v` prefix stripped; `rc`/`nightly` ignored; ls-remote parsed; failure, missing git and timeout each `None`) → run red → implement → green → commit.

### Task 2: `upgrade/config.py` — `repo`, `version_check`, and `index` becoming optional

**Files:** modify `lmi/commands/upgrade/config.py`; modify `tests/commands/upgrade/test_config.py`; modify `examples/lmi.json`.

**Produces:** `Config.repo`, `Config.version_check`, `Config.source_kind`; `--source repo|index`; `config.SOURCE_REPO` / `SOURCE_INDEX`; the "one of index and repo" refusal.

Steps: tests (repo alone is valid; index alone is valid; neither is exit 2 naming both; repo wins when both; `--source index` overrides; `version_check` false/absent/null) → red → implement → green → commit.

### Task 3: the install and what it prints

**Files:** modify `lmi/commands/upgrade/pip.py`, `lmi/commands/upgrade/runner.py`; modify `tests/commands/upgrade/test_runner.py`.

**Produces:** `pip.install` handling a repo target; `pip.requirement(cfg, version)`; the `Source:` and `Newest:` lines.

Steps: tests (**MANDATORY** — the `--index-url` is present on a repo install, item 60; the requirement string is `lmi @ git+<url>@v0.3.0`; `--no-deps` survives; `--version 0.2.0` becomes `@v0.2.0`; the `Source:` line names repo or index; `verify.confirm` still decides the outcome) → red → implement → green → commit.

### Task 4: `upgrade/notice.py` and the one line in `cli.py`

**Files:** create `lmi/commands/upgrade/notice.py`; modify `lmi/cli.py`; create `tests/commands/upgrade/test_notice.py`.

**Produces:** `notice.maybe_say(argv_command)`, `notice.CACHE_NAME`, `notice.MAX_AGE`.

Steps: tests (**MANDATORY** — the line appears when the tag is newer; nothing at all when: no config, no repo, `version_check: false`, git missing, git failing, git hanging, tag not newer, tag unparseable; nothing for `lmi upgrade` itself; a second command inside 24h runs no git; a broken cache file is a miss not an error; an unwritable cache is silent; the check never changes a command's exit code) → red → implement → green → commit.

### Task 5: the packaged default, the docs, and the counts

**Files:** modify `lmi/commands/install/default-config/lmi.json`, `README.md`, `docs/upgrade.md`, `docs/config.md`, `docs/status.md`, `CLAUDE.md`, `tests/test_docs.py`.

Steps: doc needles red → write `docs/upgrade.md`'s repo section and the notice section, `config.md`'s two new keys, the packaged `repo` URL, CLAUDE.md items 60–63 plus section 2's file list and the `fake_git` row in section 5's fixture table → re-measure both suite figures and write the measured numbers → green → commit.

## Self-Review

Spec coverage: §2 → Task 2; §3 → Task 3; §4 → Task 1; §5 → Task 3; §6 → Task 4; §7 → Task 5; §8 → every task. No placeholders. Names used in later tasks (`repo.newest_tag`, `Config.source_kind`, `pip.requirement`, `notice.maybe_say`) are all defined in the task that introduces them.
