"""The repo as a source of versions: its newest tag, and how versions order.

Two separable things, both here because both are "what does the remote say the
newest lmi is", and a second spelling of either would let the notice suggest a
version the upgrade would not install.

**Every uncertainty here answers None or False, never an exception.** No git on
the machine, no network, a timeout, a tag nobody can order, a running version
that does not parse - all of them mean "say nothing". That is not politeness: a
notice that cries wolf teaches an operator to ignore it, and then the one that
matters months later is ignored too. The asymmetry runs the opposite way from
[QUOTA], where under-reporting was the danger.
"""

import re
import subprocess
from typing import NamedTuple, Optional

# How long the lookup may take. This is the only network call on `lmi
# schedule`'s startup path, so it is bounded rather than merely intended to be
# quick: an unreachable git host must not delay an unattended run's first
# iteration. Item 62.
TIMEOUT = 3

# A version tag, and nothing else. `v` optional, digits and dots only, anchored
# at both ends - so `v1.0-rc1`, `0.3.0rc1`, `nightly` and `v1.2.x` do not match
# and are therefore ignored rather than ordered. There is no ordering for them
# that is not a guess, and a guess is what item 61 forbids.
_VERSION_RE = re.compile(r"^[vV]?(\d+(?:\.\d+)*)$")

# `git ls-remote --tags` prints "<sha>\trefs/tags/<name>" per line, plus a
# "<name>^{}" dereference line for every annotated tag. The `^{}` form fails
# _VERSION_RE on its own, so it needs no special case - but a change to either
# pattern must keep that true, because a dereference line read as a tag name
# would be a tag nobody can install.
_REF_RE = re.compile(r"^\S+\s+refs/tags/(.+?)\s*$")


class Tag(NamedTuple):
    """One tag, as both the name to install and the version to compare."""

    name: str
    version: tuple


def parse_version(text):
    """`"v0.10.0"` -> `(0, 10, 0)`. None for anything not a plain version."""
    if not isinstance(text, str):
        return None
    match = _VERSION_RE.match(text.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def version_string(text):
    """`"v0.3.0"` -> `"0.3.0"`. None when there is no version in it.

    What a TAG NAME means as a version, which is not the same string - and
    conflating the two is item 22's trap in a new place: `verify.confirm`
    compares what it was told to expect against what the installed console
    script reports, and a tag name there fails a perfectly good upgrade with
    "expected v0.3.0, got 0.3.0".

    Derived from parse_version rather than by stripping a character, so there is
    one definition of what a version is in this module. A tag whose name and
    whose pyproject version genuinely disagree - `v0.3` against `0.3.0` - still
    fails verification, and should: that is the tag lying about what it carries,
    and the message shows both.
    """
    version = parse_version(text)
    if version is None:
        return None
    return ".".join(str(part) for part in version)


def is_newer(candidate, running):
    """Is `candidate` a later version than `running`? False if either is unclear.

    Tuples, never strings. `"0.10.0" > "0.9.0"` is False as a string, which
    would tell a machine running 0.9.0 that it is current for every release from
    0.10.0 onward - and look like nothing at all. Item 61.

    A shorter version is not newer than its own prefix: 0.2 and 0.2.0 are one
    release written two ways, and tuple comparison already says so.
    """
    left, right = parse_version(candidate), parse_version(running)
    if left is None or right is None:
        return False
    return _pad(left, right) > _pad(right, left)


def _pad(value, other):
    """`value` extended with zeros to `other`'s length, so (0, 2) == (0, 2, 0)."""
    return value + (0,) * (len(other) - len(value))


def newest_tag(url, timeout=TIMEOUT):
    """The highest version tag the remote offers, or None. Never raises.

    Read-only and remote-only: `ls-remote` clones nothing, writes nothing and
    does not care what directory it runs in, which is what makes it safe to do
    on the startup path of every command.
    """
    lines = _ls_remote(url, timeout)
    if lines is None:
        return None
    best = None
    for line in lines:
        match = _REF_RE.match(line)
        if match is None:
            continue
        name = match.group(1)
        version = parse_version(name)
        if version is None:
            continue
        if best is None or version > best.version:
            best = Tag(name=name, version=version)
    return best


def _ls_remote(url, timeout):
    """The remote's ref lines, or None for every possible failure.

    `git` is not a dependency of lmi - it is a thing this one lookup uses if the
    machine has it - so its absence is an answer rather than an error. Same for
    a non-zero exit, a timeout, and anything else subprocess can raise on a
    locked-down box.
    """
    try:
        done = subprocess.run(
            ["git", "ls-remote", "--tags", url],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        # OSError covers "no git on PATH"; SubprocessError covers the timeout,
        # whose expiry also kills the child - a lookup that outlived the caller
        # would hold a pipe open on an unattended run for as long as the host
        # cared to stall.
        return None
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", "replace").splitlines()
