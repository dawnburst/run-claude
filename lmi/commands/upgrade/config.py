"""Arguments and the `lmi` config section for `lmi upgrade`.

Where the config file is, and how it is decoded and parsed, is
lmi/core/config.py's job. What the "lmi" section means is this module's.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ...core import config as core_config
from ...core import fs
from ...core.errors import EXIT_USAGE, LmiError

# What this command upgrades. Deliberately not a config key: a command whose
# target is configurable is a different command.
PACKAGE = "lmi"

SECTION = "lmi"
PURPOSE = "`lmi upgrade` needs one to know where to install lmi from."

# The two places a new lmi can come from. `repo` is a git URL pip clones and
# builds; `index` is a Python package index carrying a released wheel.
SOURCE_REPO = "repo"
SOURCE_INDEX = "index"
SOURCES = (SOURCE_REPO, SOURCE_INDEX)

# Absent is not null. An absent "version_check" means the default; a
# "version_check": null is a value the operator wrote and is refused. This is
# the same rule as template._validate, fragment._validate, backend.of_document
# and backend.session_of_document, in its sixth home - and here reading null as
# "the default" would turn the notice back ON for a machine that meant to
# silence it.
_MISSING = object()

NO_SOURCE = (
    'the "lmi" section names neither "index" nor "repo": %s\n'
    "    `lmi upgrade` installs from one of the two, and needs to be told\n"
    "    which:\n"
    "\n"
    '      "index": a Python package index carrying a released lmi wheel\n'
    '      "repo":  a git URL, which pip clones and builds\n'
    "\n"
    "    With both, the repo wins and `--source index` overrides it for one\n"
    "    run. Neither is guessed: an lmi installed from somewhere the operator\n"
    "    did not name is worse than one that refused to install."
)

MISSING_FOR_SOURCE = (
    '--source %s needs "lmi.%s" in the config file, and it is not there: %s'
)

# Printed when no config file is found, so it is what a first-time operator
# pastes - with the command having just failed and nothing else on screen to
# copy from. Every key this command supports appears here. examples/lmi.json is
# the same section with real-looking URLs, and tests/test_docs.py pins the two
# key sets equal so they cannot drift apart.
EXAMPLE = """{
  "lmi": {
    "index": "https://artifactory.example.com/api/pypi/pypi-virtual/simple/",
    "repo": "https://github.com/dawnburst/run-claude.git",
    "cafile": "/etc/ssl/certs/corp-ca.pem",
    "version_check": true
  }
}"""


def add_arguments(parser):
    parser.add_argument(
        "--version", dest="version", metavar="VERSION",
        help="the version to install, e.g. 0.2.0. Default: the newest the "
             "source offers. Use it to go back to a known-good version",
    )
    parser.add_argument(
        "--source", dest="source", choices=list(SOURCES), default=None,
        help="where to install from, when the config file names both. "
             "Default: the repo",
    )
    core_config.add_argument(parser)


@dataclass(frozen=True)
class Config:
    # Both optional, one required - see _source_kind. `index` is read even when
    # the repo wins, because a repo install needs it for pip's build
    # dependencies (item 60).
    index: Optional[str]
    cafile: Optional[Path]
    source: Path
    repo: Optional[str] = None
    source_kind: str = SOURCE_INDEX
    version_check: bool = True


def build_config(args):
    """Find, read and validate the config file. Never returns a partial Config."""
    path = core_config.find(getattr(args, "config", None), PURPOSE, EXAMPLE)
    section = core_config.section(core_config.load(path), SECTION, path, EXAMPLE)
    index = _index(section, path)
    repo = _repo(section, path)
    return Config(
        index=index,
        cafile=_cafile(section, path),
        source=path,
        repo=repo,
        source_kind=_source_kind(getattr(args, "source", None), index, repo, path),
        version_check=_version_check(section, path),
    )


def _source_kind(asked, index, repo, path):
    """Which of the two sources this run installs from.

    The repo wins when both are configured. Not because it is better, but
    because a rule an operator can state beats a precedence they have to
    discover - and `--source` overrides it for one run, out loud, with the
    header naming whichever ran (item 63): both sources end in the same
    "Upgraded 0.2.1 -> 0.3.0", so nothing else in the output distinguishes a
    machine upgraded from the site's audited mirror from one upgraded off a git
    tag.

    An explicit --source whose key is missing is exit 2 rather than a silent
    fall back to the other one, for the reason every other refusal in this
    package exists: installing from somewhere the operator did not ask for is
    the failure, not the inconvenience.
    """
    if asked == SOURCE_REPO:
        if repo is None:
            raise LmiError(
                MISSING_FOR_SOURCE % (SOURCE_REPO, "repo", path), EXIT_USAGE
            )
        return SOURCE_REPO
    if asked == SOURCE_INDEX:
        if index is None:
            raise LmiError(
                MISSING_FOR_SOURCE % (SOURCE_INDEX, "index", path), EXIT_USAGE
            )
        return SOURCE_INDEX
    if repo is not None:
        return SOURCE_REPO
    if index is not None:
        return SOURCE_INDEX
    raise LmiError(NO_SOURCE % path, EXIT_USAGE)


def _index(section, path):
    """The index URL, or None when the key is absent.

    Absent is no longer an error on its own: a site whose lmi lives in git has
    no index to name. Present-but-wrong still is - _source_kind is what refuses
    a config that names neither.
    """
    value = section.get("index", _MISSING)
    if value is _MISSING:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LmiError(
            '"lmi.index" must be a non-empty string - the Python package index '
            "URL to install from: %s" % path,
            EXIT_USAGE,
        )
    return value.strip()


def _repo(section, path):
    """The git URL, or None. Never inferred, for item 38's reason.

    lmi does not guess a repository any more than it guesses an index. What
    ships in install/default-config/lmi.json is a value written in a file the
    operator can read and edit (item 48), not a default reached for here when
    the key is missing.
    """
    value = section.get("repo", _MISSING)
    if value is _MISSING:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LmiError(
            '"lmi.repo" must be a non-empty string - a git URL pip can install '
            "from: %s" % path,
            EXIT_USAGE,
        )
    return value.strip()


def _version_check(section, path):
    """Whether every command may report that a newer lmi exists. Default: yes."""
    value = section.get("version_check", _MISSING)
    if value is _MISSING:
        return True
    if isinstance(value, bool):
        return value
    raise LmiError(
        '"lmi.version_check" must be true or false: %s\n'
        "    Got: %r\n"
        "    false silences the once-a-day check on this machine, which is what"
        "\n    an air-gapped site whose git host is unreachable by design wants."
        % (path, value),
        EXIT_USAGE,
    )


def _cafile(section, path):
    value = section.get("cafile")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LmiError('"lmi.cafile" must be a string: %s' % path, EXIT_USAGE)
    resolved = core_config.expand(value)
    # Checked here rather than at pip time: a wrong --cert surfaces much later
    # as an unrelated TLS error, on the far side of a question the user has
    # already answered yes to.
    if core_config.kind(resolved) != fs.FILE:
        raise LmiError(
            '"lmi.cafile" does not exist: %s (from %s)' % (resolved, path),
            EXIT_USAGE,
        )
    return resolved
