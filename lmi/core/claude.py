"""Where Claude Code keeps its files.

One definition, because two commands need it and neither should own it: if
`lmi install` and `lmi config` ever disagreed about where settings.json lives,
one of them would silently configure a file nothing reads.
"""

from pathlib import Path


def config_dir():
    """~/.claude - the folder Claude Code reads its user-scope files from."""
    return Path.home() / ".claude"


def settings_path():
    """~/.claude/settings.json - the user-scope settings file."""
    return config_dir() / "settings.json"
