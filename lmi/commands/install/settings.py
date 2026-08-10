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
