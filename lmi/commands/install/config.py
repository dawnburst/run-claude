"""Arguments, config-file discovery and validation for `lmi install`.

Validation lives with the command, not in cli.py, so cli.py stays pure
parse-and-dispatch as commands accumulate. Where the file *is* lives in
lmi/core/config.py, because `lmi upgrade` reads the same file - see
CLAUDE.md section 2 on promoting into core/.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

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

# The 256K context profile, shipped as a default so a machine whose config
# omits `env` still gets it. Values are STRINGS: Claude Code types settings.json
# `env` as a map of string to string, and a JSON number there writes cleanly,
# parses cleanly and does nothing.
DEFAULT_ENV = {
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "204800",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000",
}

# Printed when no config file is found, so it is what a first-time operator
# pastes into their first lmi.json - with the command having just failed, and
# nothing else on screen to copy from. It must therefore document EVERY key,
# `env` included: leaving out the key the 256K profile rests on teaches the
# operator the profile is not configurable. examples/lmi.json is the same
# document with real-looking URLs, and tests/test_docs.py pins the two key sets
# equal so they cannot drift apart again.
EXAMPLE = """{
  "claude": {
    "registry": "https://artifactory.example.com/api/npm/npm-virtual/",
    "cafile": "/etc/ssl/certs/corp-ca.pem",
    "marketplaces": {
      "corp-tools": {
        "source": {"source": "git", "url": "https://git.example.com/m.git"}
      }
    },
    "env": {
      "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000",
      "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "204800",
      "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"
    }
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
    marketplaces: Dict
    env: Dict
    source: Path


def build_config(args):
    """Find, read and validate the config file. Never returns a partial Config."""
    path = core_config.find(getattr(args, "config", None), PURPOSE, EXAMPLE)
    section = core_config.section(core_config.load(path), SECTION, path, EXAMPLE)
    return Config(
        registry=_registry(section, path),
        cafile=_cafile(section, path),
        marketplaces=_object(section, "marketplaces", path),
        env=_env(section, path),
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


def _object(section, key, path):
    value = section.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise LmiError(
            '"claude.%s" must be a JSON object: %s' % (key, path), EXIT_USAGE
        )
    return value


def _env(section, path):
    """The 256K defaults, overridden and extended by the config file."""
    merged = dict(DEFAULT_ENV)          # a copy: DEFAULT_ENV is module state
    for key, value in _object(section, "env", path).items():
        if not isinstance(value, str):
            raise LmiError(
                '"claude.env.%s" must be a string, not %s: %s\n'
                "    Claude Code types settings.json env as string-to-string; a "
                "number is silently ignored."
                % (key, type(value).__name__, path),
                EXIT_USAGE,
            )
        merged[key] = value
    return merged
