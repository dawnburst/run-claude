"""Errors and the exit codes that are global to every lmi command.

Only 0 and 2 are global. A command's own codes live in that command's
package - see lmi/commands/schedule/exit_codes.py - so two commands can
never disagree about what 2 means.
"""

EXIT_OK = 0
EXIT_USAGE = 2


class LmiError(Exception):
    """An error with a chosen exit code. cli.main turns this into a status."""

    def __init__(self, message, code=EXIT_USAGE):
        super().__init__(message)
        self.code = code
