"""Arguments, config-file discovery and validation for `lmi install`.

Validation lives with the command, not in cli.py, so cli.py stays pure
parse-and-dispatch as commands accumulate.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from ...core import fs
from ...core.errors import EXIT_USAGE, LmiError
from ...core.text import decode_with_bom

# What this command installs. Deliberately not a config key: a command whose
# target is configurable is a different command.
PACKAGE = "@anthropic-ai/claude-code"

CONFIG_ENV_VAR = "LMI_CONFIG"
CWD_CONFIG_NAME = "lmi.json"
HOME_CONFIG = "~/.lmi/config.json"

# The 256K context profile, shipped as a default so a machine whose config
# omits `env` still gets it. Values are STRINGS: Claude Code types settings.json
# `env` as a map of string to string, and a JSON number there writes cleanly,
# parses cleanly and does nothing.
DEFAULT_ENV = {
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "204800",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000",
}

EXAMPLE = """{
  "claude": {
    "registry": "https://artifactory.example.com/api/npm/npm-virtual/",
    "cafile": "/etc/ssl/certs/corp-ca.pem",
    "marketplaces": {
      "corp-tools": {
        "source": {"source": "git", "url": "https://git.example.com/m.git"}
      }
    }
  }
}"""


def add_arguments(parser):
    parser.add_argument(
        "target", choices=["claude"], metavar="TARGET",
        help="what to install. Only 'claude' is supported",
    )
    parser.add_argument(
        "--config", dest="config", metavar="PATH",
        help="config file. Default: $%s, ./%s, %s"
             % (CONFIG_ENV_VAR, CWD_CONFIG_NAME, HOME_CONFIG),
    )


@dataclass(frozen=True)
class Config:
    registry: str
    cafile: Optional[Path]
    marketplaces: Dict
    env: Dict
    source: Path


def build_config(args):
    """Find, read and validate the config file. Never returns a partial Config."""
    path = _find(getattr(args, "config", None))
    section = _section(_load(path), path)
    return Config(
        registry=_registry(section, path),
        cafile=_cafile(section, path),
        marketplaces=_object(section, "marketplaces", path),
        env=_env(section, path),
        source=path,
    )


# --- discovery ------------------------------------------------------------

def _find(explicit):
    if explicit is not None:
        path = _expand(explicit)
        # An explicit --config that does not exist must NOT fall through to the
        # next candidate. A named file that quietly resolves to a different one
        # is how a machine gets provisioned against the wrong registry.
        if _kind(path) != fs.FILE:
            raise LmiError(
                "the config file given with --config does not exist: %s" % path,
                EXIT_USAGE,
            )
        return path

    candidates = []
    from_env = os.environ.get(CONFIG_ENV_VAR)
    if from_env:
        candidates.append(_expand(from_env))
    candidates.append(Path.cwd() / CWD_CONFIG_NAME)
    candidates.append(_expand(HOME_CONFIG))

    for candidate in candidates:
        if _kind(candidate) == fs.FILE:
            return candidate
    raise LmiError(_nothing_found(candidates), EXIT_USAGE)


def _nothing_found(candidates):
    return (
        "no config file found. `lmi install` needs one to know which registry "
        "to install from.\n"
        "    Looked in, in order:\n%s\n"
        "    Create one, or pass --config PATH. A minimal file:\n\n%s"
        % ("\n".join("      " + str(c) for c in candidates),
           "\n".join("      " + line for line in EXAMPLE.splitlines()))
    )


def _expand(raw):
    """Path(raw).expanduser().absolute(), without the one way it explodes.

    expanduser() raises RuntimeError for a "~someuser" whose home it cannot look
    up - a typo in --config "~claude/lmi.json" is enough - and unguarded that
    reaches the CLI as a traceback and exit 1.
    """
    try:
        return Path(raw).expanduser().absolute()
    except RuntimeError as exc:
        raise LmiError(
            "the config file path cannot be expanded: %s (%s)" % (raw, exc),
            EXIT_USAGE,
        )


def _kind(path):
    """fs.classify, but an unanswerable path is a usage error.

    Path.is_file() raises ENAMETOOLONG rather than returning False, so an
    over-long --config used to crash with a traceback and exit 1.
    """
    kind, reason = fs.classify(path)
    if kind == fs.UNKNOWN:
        raise LmiError(
            "the config file path cannot be used: %s (%s)" % (path, reason),
            EXIT_USAGE,
        )
    return kind


# --- reading and validation ----------------------------------------------

def _load(path):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LmiError(
            "the config file cannot be read: %s (%s)" % (path, exc), EXIT_USAGE
        )
    # Through the BOM decoder because Notepad and PowerShell's Set-Content both
    # write a UTF-8 BOM, and json.loads rejects one with a bare "Expecting value".
    try:
        text = decode_with_bom(raw)
    except UnicodeDecodeError as exc:
        raise LmiError(
            "the config file is not UTF-8: %s (%s)" % (path, exc), EXIT_USAGE
        )
    try:
        return json.loads(text)
    except ValueError as exc:
        raise LmiError(
            "the config file is not valid JSON: %s (%s)" % (path, exc), EXIT_USAGE
        )


def _section(doc, path):
    if not isinstance(doc, dict):
        raise LmiError(
            "the config file must contain a JSON object: %s" % path, EXIT_USAGE
        )
    section = doc.get("claude")
    if section is None:
        raise LmiError(
            'the config file has no "claude" section: %s\n'
            "    Expected:\n\n%s"
            % (path, "\n".join("      " + l for l in EXAMPLE.splitlines())),
            EXIT_USAGE,
        )
    if not isinstance(section, dict):
        raise LmiError(
            'the "claude" section must be a JSON object: %s' % path, EXIT_USAGE
        )
    return section


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
    resolved = _expand(value)
    # Checked here rather than at npm time: `npm config set cafile /typo`
    # succeeds, and the mistake surfaces much later as an unrelated TLS error.
    if _kind(resolved) != fs.FILE:
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
