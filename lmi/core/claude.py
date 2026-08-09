"""Where Claude Code keeps its files.

One definition, because two commands need it and neither should own it: if
`lmi install` and `lmi config` ever disagreed about where settings.json lives,
one of them would silently configure a file nothing reads.
"""

from pathlib import Path


def settings_path():
    """~/.claude/settings.json - the user-scope settings file."""
    return Path.home() / ".claude" / "settings.json"
