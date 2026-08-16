"""What goes into ~/.claude/settings.json.

Content only - template.py owns reading the operator's file, and jsonfile.py
owns backing up and writing. Nothing here touches the filesystem except path().

The document installed is the template, verbatim, with the two values lmi
learns at run time written into it: the auth token the user typed, and the Git
Bash path on Windows. It is not merged with whatever was there before - the
previous file is backed up with a timestamp and replaced, so a site's settings
are the file the operator wrote rather than that file plus an unknown residue
of every earlier install.
"""

import copy

from . import gitbash
from ...core.claude import settings_path

# Verified against the Claude Code 2.1.222 settings schema, which declares
# extraKnownMarketplaces as record(name, {source}) and whose own writer defaults
# to "userSettings" scope - so this file, not managed settings, is the right
# place. Any other spelling writes cleanly and is ignored.
#
# Nothing here writes this key any more; the operator writes it in the template.
# The constant stays because that makes the exact spelling the operator needs
# *more* important, not less, and tests/test_docs.py pins the README against it.
MARKETPLACES_KEY = "extraKnownMarketplaces"
TOKEN_KEY = "ANTHROPIC_AUTH_TOKEN"
ENV_KEY = "env"


def path():
    """~/.claude/settings.json. Defined in core.claude - see the note there."""
    return settings_path()


def compose(template, token, bash_path):
    """The document to install: `template` with the run-time values in it.

    A deep copy, because the template belongs to the frozen Config and a frozen
    dataclass does not freeze the dicts inside it - composing in place would let
    one caller's edit reach back into the parsed file.

    `token` is always a real token: the prompt refuses a blank answer, which is
    what stops the template's placeholder being installed verbatim. `bash_path`
    is None everywhere but Windows, and the key is then absent rather than
    empty - Claude Code reads an empty value and fails to start a shell, where
    an absent one it falls back from.
    """
    doc = copy.deepcopy(template)
    env = doc.get(ENV_KEY)
    if not isinstance(env, dict):
        # A template whose env is not an object never reaches here - template.py
        # refuses it - so this only creates the block for a template that has
        # none, which is a legitimate shape for a site that sets nothing else.
        env = {}
        doc[ENV_KEY] = env
    env[TOKEN_KEY] = token
    if bash_path:
        env[gitbash.VAR] = bash_path
    return doc


def token_of(doc):
    """The auth token in a settings document, or None if there is not one.

    The inverse of what compose writes, and the only reader of an installed
    settings.json. `doc` may be a file a user hand-edited rather than the
    validated template, so every shape has to be survivable: a non-object env,
    a non-string value and a blank string are each "no token", never a value.

    A blank one in particular must not come back as "": the caller offers to
    keep whatever this returns, and keeping "" would write an empty token into
    a document that then looks configured and fails every call.
    """
    env = doc.get(ENV_KEY)
    if not isinstance(env, dict):
        return None
    value = env.get(TOKEN_KEY)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


# Four leading plus four trailing characters is more than half of a 15-character
# secret. Below this length nothing is shown: a hint that reconstructs the token
# is not a hint, and the whole reason this is masked is that the prompt's answer
# is not echoed either.
MASK_FLOOR = 16
MASK_EDGE = 4
HIDDEN = "****"


def mask(token):
    """A hint at which token is on the machine, safe to print.

    Enough to recognise a token, never enough to use one. It exists because
    "keep the existing one" is otherwise a decision made blind: a machine
    re-pointed at a different gateway keeps a stale credential, and the 401
    that follows points at the gateway rather than at the answer given here.
    """
    if len(token) < MASK_FLOOR:
        return HIDDEN
    return "%s...%s" % (token[:MASK_EDGE], token[-MASK_EDGE:])
