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
PURPOSE = "`lmi upgrade` needs one to know which package index to install from."

# Printed when no config file is found, so it is what a first-time operator
# pastes - with the command having just failed and nothing else on screen to
# copy from. Every key this command supports appears here. examples/lmi.json is
# the same section with real-looking URLs, and tests/test_docs.py pins the two
# key sets equal so they cannot drift apart.
EXAMPLE = """{
  "lmi": {
    "index": "https://artifactory.example.com/api/pypi/pypi-virtual/simple/",
    "cafile": "/etc/ssl/certs/corp-ca.pem"
  }
}"""


def add_arguments(parser):
    parser.add_argument(
        "--version", dest="version", metavar="VERSION",
        help="the version to install, e.g. 0.2.0. Default: the newest the "
             "index offers. Use it to go back to a known-good version",
    )
    core_config.add_argument(parser)


@dataclass(frozen=True)
class Config:
    index: str
    cafile: Optional[Path]
    source: Path


def build_config(args):
    """Find, read and validate the config file. Never returns a partial Config."""
    path = core_config.find(getattr(args, "config", None), PURPOSE, EXAMPLE)
    section = core_config.section(core_config.load(path), SECTION, path, EXAMPLE)
    return Config(
        index=_index(section, path),
        cafile=_cafile(section, path),
        source=path,
    )


def _index(section, path):
    value = section.get("index")
    if not isinstance(value, str) or not value.strip():
        raise LmiError(
            '"lmi.index" must be a non-empty string - the Python package index '
            "URL to install from: %s" % path,
            EXIT_USAGE,
        )
    return value.strip()


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
