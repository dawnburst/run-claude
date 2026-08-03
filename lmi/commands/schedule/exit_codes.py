"""Exit codes specific to `lmi schedule`.

0 and 2 are global and live in lmi.core.errors. Everything else is this
command's own, so another command can define its own 1 and 3 freely.
"""

EXIT_CALL_FAILED = 1
EXIT_LOCKED = 3
EXIT_INTERNAL = 4
