"""What goes into ~/.claude/settings.json.

Content only - jsonfile.py owns reading, backing up and writing. Nothing here
touches the filesystem except path().
"""

from ...core.claude import settings_path

# Verified against the Claude Code 2.1.222 settings schema, which declares
# extraKnownMarketplaces as record(name, {source}) and whose own writer defaults
# to "userSettings" scope - so this file, not managed settings, is the right
# place. Any other spelling writes cleanly and is ignored.
MARKETPLACES_KEY = "extraKnownMarketplaces"
TOKEN_KEY = "ANTHROPIC_AUTH_TOKEN"
ENV_KEY = "env"


def path():
    """~/.claude/settings.json. Defined in core.claude - see the note there."""
    return settings_path()


def merge(doc, env, marketplaces):
    """Merge `env` and `marketplaces` into `doc` and return it.

    Merged one level down, not at the document root, so an env key lmi does not
    manage and a marketplace under another name both survive. A key lmi does
    manage is overwritten, so re-running after editing the config converges on
    the config instead of accumulating stale entries.
    """
    if env:
        doc[ENV_KEY] = _merged(doc.get(ENV_KEY), env)
    if marketplaces:
        doc[MARKETPLACES_KEY] = _merged(doc.get(MARKETPLACES_KEY), marketplaces)
    return doc


def token_of(doc):
    """The auth token already configured, or None.

    Used only to tell the user a token exists - never to print one.
    """
    env = doc.get(ENV_KEY)
    if not isinstance(env, dict):
        return None
    return env.get(TOKEN_KEY) or None


def _merged(current, additions):
    # A value of the wrong type is replaced rather than merged into: dict.update
    # on a list raises, and the file is Claude Code's to validate, not ours.
    if not isinstance(current, dict):
        current = {}
    else:
        current = dict(current)
    current.update(additions)
    return current
