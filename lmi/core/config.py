"""Finding, reading and parsing an lmi config file.

Promoted out of lmi/commands/install/config.py when `lmi upgrade` became the
second command to need it - which is the condition CLAUDE.md section 2 names
for moving something into core/: "then, not in advance".

What lives here has no command flavour: where the file is, how it is decoded,
how it is parsed, and the two refusals that must never quietly become
fall-throughs - an explicit --config that does not exist, and a file left at
the pre-move ./lmi.json. What a section *means* stays with the command that
owns it.
"""

import json
import os
from pathlib import Path

from . import fs
from .errors import EXIT_USAGE, LmiError
from .text import decode_with_bom

CONFIG_ENV_VAR = "LMI_CONFIG"
CWD_CONFIG_NAME = "lmi.json"
# The working-directory default lives in ./config/, not loose in the directory
# itself, so a checkout has one obvious place for it. Kept as two names because
# find() has to look for the pre-move path as well - see _refuse_legacy.
CWD_CONFIG_DIR = "config"
CWD_CONFIG = "%s/%s" % (CWD_CONFIG_DIR, CWD_CONFIG_NAME)
HOME_CONFIG = "~/.lmi/config.json"

HELP = "config file. Default: $%s, ./%s, %s" % (CONFIG_ENV_VAR, CWD_CONFIG,
                                                HOME_CONFIG)


def add_argument(parser):
    """The --config flag. One definition, so two commands cannot describe the
    same search order differently."""
    parser.add_argument("--config", dest="config", metavar="PATH", help=HELP)


# --- discovery ------------------------------------------------------------

def find(explicit, purpose, example, fallback=None):
    """The config file to read, or a usage error naming everywhere looked.

    `purpose` is one sentence saying what the calling command needs it for, and
    `example` a minimal file to paste; both appear only when nothing is found,
    where they are all the operator has to go on.

    `fallback` is a last candidate after every other, for a command that ships
    a default of its own - `lmi install claude` and the config folder packaged
    inside the wheel. It is deliberately a parameter here rather than a
    candidate in find_optional: `lmi schedule` and `lmi config schedule` search
    through that function, and a packaged file appearing there would be a
    `schedule.mode` written into site-packages, which is item 39's silent
    failure. A command that passes nothing keeps exactly the old behaviour.
    """
    path, candidates = find_optional(explicit)
    if path is not None:
        return path
    if fallback is not None:
        candidates = candidates + [fallback]
        if kind(fallback) == fs.FILE:
            return fallback
    raise LmiError(_nothing_found(candidates, purpose, example), EXIT_USAGE)


def find_optional(explicit):
    """(the config file or None, every candidate looked at, in order).

    The same search as find(), for the callers to which "there is no config
    file" is an answer rather than an error - `lmi schedule`, where it means
    the default backend, and `lmi config schedule`, which reports where a write
    would land. Both refusals stay refusals even here: an explicit --config
    that does not exist, and a file left at the pre-move ./lmi.json. Those are
    not absences, they are a named file that would silently resolve to a
    different one, which is how a machine gets provisioned against the wrong
    source.

    find() is defined in terms of this so the search order has one definition.
    Do not give the two functions candidate lists of their own.
    """
    if explicit is not None:
        path = expand(explicit)
        # An explicit --config that does not exist must NOT fall through to the
        # next candidate. A named file that quietly resolves to a different one
        # is how a machine gets provisioned against the wrong registry.
        if kind(path) != fs.FILE:
            raise LmiError(
                "the config file given with --config does not exist: %s" % path,
                EXIT_USAGE,
            )
        return path, [path]

    candidates = []
    from_env = os.environ.get(CONFIG_ENV_VAR)
    if from_env:
        candidates.append(expand(from_env))
    in_cwd = Path.cwd() / CWD_CONFIG_DIR / CWD_CONFIG_NAME
    candidates.append(in_cwd)
    candidates.append(expand(HOME_CONFIG))

    for candidate in candidates:
        if kind(candidate) == fs.FILE:
            return candidate, candidates
        # Checked at the point in the order the old path used to occupy, so an
        # explicit --config or $LMI_CONFIG still wins and never sees this.
        if candidate == in_cwd:
            _refuse_legacy(Path.cwd() / CWD_CONFIG_NAME, in_cwd)
    return None, candidates


def _refuse_legacy(legacy, expected):
    """The working-directory default moved into ./config/. Say so; do not skip.

    Passing over a file at the old path is not harmless. The next candidate is
    ~/.lmi/config.json - a different registry, quite possibly a different site -
    and installing from it while an lmi.json sits in plain view in the working
    directory is exactly the wrong-registry provisioning that the --config rule
    above exists to prevent, reached from the other direction. It is also the
    silent kind: the run reports success and the machine is provisioned against
    the wrong source.
    """
    if kind(legacy) != fs.FILE:
        return
    raise LmiError(
        "the working-directory config file has moved into %s/, so %s is no "
        "longer read.\n"
        "    Move it:\n\n"
        "        mkdir -p %s && mv %s %s\n\n"
        "    or keep it where it is by naming it: --config %s"
        % (CWD_CONFIG_DIR, legacy, expected.parent, legacy, expected, legacy),
        EXIT_USAGE,
    )


def _nothing_found(candidates, purpose, example):
    return (
        "no config file found. %s\n"
        "    Looked in, in order:\n%s\n"
        "    Create one, or pass --config PATH. A minimal file:\n\n%s"
        % (purpose,
           "\n".join("      " + str(c) for c in candidates),
           "\n".join("      " + line for line in example.splitlines()))
    )


def expand(raw):
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


def kind(path):
    """fs.classify, but an unanswerable path is a usage error.

    Path.is_file() raises ENAMETOOLONG rather than returning False, so an
    over-long --config used to crash with a traceback and exit 1.
    """
    verdict, reason = fs.classify(path)
    if verdict == fs.UNKNOWN:
        raise LmiError(
            "the config file path cannot be used: %s (%s)" % (path, reason),
            EXIT_USAGE,
        )
    return verdict


# --- reading and parsing --------------------------------------------------

def load(path):
    """The whole document, as a dict-or-whatever-it-is. No section knowledge."""
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


def section(doc, name, path, example):
    """One named top-level object out of a loaded document."""
    if not isinstance(doc, dict):
        raise LmiError(
            "the config file must contain a JSON object: %s" % path, EXIT_USAGE
        )
    found = doc.get(name)
    if found is None:
        raise LmiError(
            'the config file has no "%s" section: %s\n'
            "    Expected:\n\n%s"
            % (name, path,
               "\n".join("      " + l for l in example.splitlines())),
            EXIT_USAGE,
        )
    if not isinstance(found, dict):
        raise LmiError(
            'the "%s" section must be a JSON object: %s' % (name, path),
            EXIT_USAGE,
        )
    return found
