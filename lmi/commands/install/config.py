"""Arguments, config-file discovery and validation for `lmi install`.

Validation lives with the command, not in cli.py, so cli.py stays pure
parse-and-dispatch as commands accumulate. Where the file *is* lives in
lmi/core/config.py, because `lmi upgrade` reads the same file - see
CLAUDE.md section 2 on promoting into core/.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from . import statusline, template
from ...core import config as core_config
from ...core import fs
from ...core.errors import EXIT_USAGE, LmiError

# What this command installs. Deliberately not a config key: a command whose
# target is configurable is a different command.
PACKAGE = "@anthropic-ai/claude-code"

SECTION = "claude"
PURPOSE = "`lmi install` needs one to know which registry to install from."

# Re-exported so this module stays the one place install's own tests and
# tests/test_docs.py have to know about.
CONFIG_ENV_VAR = core_config.CONFIG_ENV_VAR
CWD_CONFIG_NAME = core_config.CWD_CONFIG_NAME
CWD_CONFIG_DIR = core_config.CWD_CONFIG_DIR
CWD_CONFIG = core_config.CWD_CONFIG
HOME_CONFIG = core_config.HOME_CONFIG

# Printed when no config file is found, so it is what a first-time operator
# pastes into their first lmi.json - with the command having just failed, and
# nothing else on screen to copy from. It must therefore document EVERY key.
# examples/lmi.json is the same document with real-looking URLs, and
# tests/test_docs.py pins the two key sets equal so they cannot drift apart.
#
# It is two keys, not four: `marketplaces` and `env` used to live here and be
# copied into settings.json, which is two spellings for one thing. What goes
# into settings.json is now the settings.json template beside this file - see
# template.py.
EXAMPLE = """{
  "claude": {
    "registry": "https://artifactory.example.com/api/npm/npm-virtual/",
    "cafile": "/etc/ssl/certs/corp-ca.pem"
  }
}"""


def add_arguments(parser):
    parser.add_argument(
        "target", choices=["claude"], metavar="TARGET",
        help="what to install. Only 'claude' is supported",
    )
    core_config.add_argument(parser)


@dataclass(frozen=True)
class Config:
    registry: str
    cafile: Optional[Path]
    settings: Dict                  # the settings.json template, parsed
    settings_source: Path           # where it was read from
    statusline: Optional[Path]      # the statusline.js beside it, if any
    source: Path                    # the lmi.json


def build_config(args):
    """Find, read and validate the config file. Never returns a partial Config.

    The template is loaded here rather than in the runner so that promise still
    holds, and so a template error surfaces before npm has installed anything.
    The statusline script is resolved here for the second reason only: it is
    optional, so there is nothing to refuse, but a path that cannot even be
    classified should still stop the command before npm changes the machine.
    """
    path = core_config.find(getattr(args, "config", None), PURPOSE, EXAMPLE)
    section = core_config.section(core_config.load(path), SECTION, path, EXAMPLE)
    settings, settings_source = template.load(path)
    return Config(
        registry=_registry(section, path),
        cafile=_cafile(section, path),
        settings=settings,
        settings_source=settings_source,
        statusline=statusline.find(path),
        source=path,
    )


def _registry(section, path):
    value = section.get("registry")
    if not isinstance(value, str) or not value.strip():
        raise LmiError(
            '"claude.registry" must be a non-empty string - the npm registry '
            "URL to install from: %s" % path,
            EXIT_USAGE,
        )
    return value.strip()


def _cafile(section, path):
    value = section.get("cafile")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LmiError('"claude.cafile" must be a string: %s' % path, EXIT_USAGE)
    resolved = core_config.expand(value)
    # Checked here rather than at npm time: `npm config set cafile /typo`
    # succeeds, and the mistake surfaces much later as an unrelated TLS error.
    if core_config.kind(resolved) != fs.FILE:
        raise LmiError(
            '"claude.cafile" does not exist: %s (from %s)' % (resolved, path),
            EXIT_USAGE,
        )
    return resolved
