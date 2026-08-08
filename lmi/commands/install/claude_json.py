"""What goes into ~/.claude.json.

Content only - jsonfile.py owns reading, backing up and writing.
"""

from pathlib import Path

# Lowercase "b". Verified in the Claude Code 2.1.222 key list and in a live
# ~/.claude.json. "hasCompletedOnBoarding" - the natural way to write it, and
# the way the requirement was written - parses cleanly, writes cleanly and does
# nothing at all: the onboarding flow this command promised to skip still runs.
ONBOARDING_KEY = "hasCompletedOnboarding"


def path():
    return Path.home() / ".claude.json"


def needs_update(doc):
    """True unless onboarding is already marked complete.

    `is not True` rather than a falsiness check: a key present but False must be
    corrected, because the requirement is that onboarding is skipped and a False
    left in place does not achieve it. Already True means the file is not
    rewritten at all - no backup and no timestamp churn on a 63 KB document for
    a no-op.
    """
    return doc.get(ONBOARDING_KEY) is not True


def mark_complete(doc):
    doc[ONBOARDING_KEY] = True
    return doc
