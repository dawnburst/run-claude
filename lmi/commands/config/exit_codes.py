"""Exit codes specific to `lmi config`.

0 and 2 are global and live in lmi.core.errors. 3 and 4 keep the meanings they
have in `lmi install`, so a script does not have to learn a per-command
vocabulary.

There is deliberately no 1. In the other commands 1 means "the external thing
we shelled out to failed"; this command invokes nothing, so a 1 here would have
no meaning to give.
"""

EXIT_CONFIG_WRITE = 3
EXIT_INTERNAL = 4
