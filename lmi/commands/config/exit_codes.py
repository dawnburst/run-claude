"""Exit codes specific to `lmi config`.

0 and 2 are global and live in lmi.core.errors. 3 and 4 keep the meanings they
have in `lmi install`, so a script does not have to learn a per-command
vocabulary.

There is deliberately no 1. In the other commands 1 means "the external thing
we shelled out to failed"; this command invokes nothing, so a 1 here would have
no meaning to give. That is still true with a second subcommand: `lmi config
schedule` writes a config file and shells out to nothing either.

Both subcommands share these two, and neither adds one. 3 means the same thing
for both - a document this command was asked to change could not be read or
written - whether that document is ~/.claude/settings.json or the lmi.json the
mode goes into. A per-subcommand code would make a caller learn which verb it
ran to know what the number meant.

A mode value that is not one of the valid names is NOT here: it is the global
2, like every other bad value a user typed.
"""

EXIT_CONFIG_WRITE = 3
EXIT_INTERNAL = 4
