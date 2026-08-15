"""Arguments, config-file discovery and validation for `lmi install`.

Validation lives with the command, not in cli.py, so cli.py stays pure
parse-and-dispatch as commands accumulate. Where the file *is* lives in
lmi/core/config.py, because `lmi upgrade` reads the same file - see
CLAUDE.md section 2 on promoting into core/.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from . import defaults, statusline, template
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
    "index": "https://artifactory.example.com/api/pypi/pypi-virtual/simple/",
    "cafile": "/etc/ssl/certs/corp-ca.pem",
    "strict-ssl": true
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
    index: Optional[str]            # the PyPI index for the SDK, if any
    cafile: Optional[Path]
    strict_ssl: Optional[bool]      # None = leave npm's TLS setting alone
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
    path = core_config.find(getattr(args, "config", None), PURPOSE, EXAMPLE,
                            fallback=defaults.CONFIG)
    section = core_config.section(core_config.load(path), SECTION, path, EXAMPLE)
    settings, settings_source = template.load(path)
    cafile = _cafile(section, path)
    return Config(
        registry=_registry(section, path),
        index=_index(section, path),
        cafile=cafile,
        strict_ssl=_strict_ssl(section, path, cafile),
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


def _index(section, path):
    """The Python package index the SDK is installed from, or None.

    Optional, and its absence is an ANSWER rather than an omission: it means
    the SDK install is not attempted at all and the machine is provisioned into
    `cli` mode. A site that only wants the CLI backend should not have to
    configure a PyPI mirror it will never use.

    What an absent value must NEVER mean is public PyPI. On an air-gapped
    machine reaching for pypi.org is a timeout; on a machine with egress it
    installs an unvetted package from a different source than every other
    package here, and exits 0 - which is the whole reason this command exists,
    defeated silently. Do not add a default.

    A present-but-empty value is still an error: writing "index": "" is
    somebody trying to configure something, not declining to.
    """
    value = section.get("index")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LmiError(
            '"claude.index" must be a non-empty string - the Python package '
            "index URL to install the Claude Agent SDK from. Remove the key "
            "entirely to skip the SDK and use the `cli` backend: %s" % path,
            EXIT_USAGE,
        )
    return value.strip()


def _strict_ssl(section, path, cafile):
    """None to leave npm's TLS setting alone, or the boolean to write.

    Absent means absent: `npm config set strict-ssl` is not run at all, and
    whatever the machine has stays. It used to be inferred - no `cafile` was
    read as "verification cannot work here, turn it off" - which is true of an
    internal Artifactory behind a private CA and false of every registry with a
    certificate the machine already trusts. The setting is global and permanent,
    covering every `npm install` that user runs afterwards for every package, so
    inferring it from the absence of an unrelated key was too much to take on a
    guess; with a packaged default to fall through to it would have become what
    a bare `pip install lmi` did to a machine. A site that needs it off says so,
    and `true` is how a machine an older lmi turned it off on is put back.
    """
    key = "strict-ssl"
    _refuse_misspelt_strict_ssl(section, path)
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise LmiError(
            '"claude.%s" must be true or false, not %s: %s'
            % (key, type(value).__name__, path),
            EXIT_USAGE,
        )
    # Both is contradictory rather than belt-and-braces: strict-ssl false turns
    # verification off wholesale, so the CA that cafile names is never consulted
    # and that key silently does nothing.
    if value is False and cafile is not None:
        raise LmiError(
            '"claude.cafile" and "claude.strict-ssl": false contradict each '
            "other: %s\n"
            "    strict-ssl false turns verification off entirely, so the CA in "
            "cafile is never used.\n"
            "    Keep cafile to verify against your own CA, or drop it and keep "
            "strict-ssl false to verify nothing." % path,
            EXIT_USAGE,
        )
    return value


def _refuse_misspelt_strict_ssl(section, path):
    """The key is npm's own spelling, and a near miss would be silent.

    Unknown keys pass unexamined by design, which is right for a file that has
    to survive a newer lmi. It is wrong for this one: `strict_ssl` and
    `strictSsl` are what a reader of the Python attribute or of most JSON
    reaches for, and ignoring one leaves TLS verification in whatever state the
    machine was in while the config file says, in plain sight, that it was
    configured either way.
    """
    for wrong in ("strict_ssl", "strictSsl", "strictSSL"):
        if wrong in section:
            raise LmiError(
                'the config file spells the key "%s"; it is "strict-ssl", the '
                "name npm itself uses: %s" % (wrong, path),
                EXIT_USAGE,
            )


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
