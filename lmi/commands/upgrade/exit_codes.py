"""Exit codes specific to `lmi upgrade`.

0 and 2 are global and live in lmi.core.errors. Everything else is this
command's own.

4 deliberately keeps the meaning it has in `lmi schedule` and `lmi install`:
a provisioning script should not have to learn a per-command definition of "a
bug in lmi".

3 is separate from 1 on purpose. By the time verification runs, pip has already
succeeded and the machine has changed, so reporting "the upgrade failed" would
be the wrong sentence - what happened is that it changed and cannot be
confirmed.

An installation shape that cannot be upgraded is NOT here: it is the global 2,
matching `lmi install` reporting a missing npm the same way. An environmental
precondition the user can fix is a usage error.
"""

EXIT_PIP_FAILED = 1
EXIT_VERIFY_FAILED = 3
EXIT_INTERNAL = 4
