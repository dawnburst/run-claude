"""Exit codes specific to `lmi install`.

0 and 2 are global and live in lmi.core.errors. Everything else is this
command's own.

4 deliberately keeps the meaning it has in `lmi schedule`. The architecture
lets each command own its codes, but a provisioning script should not have to
learn a per-command definition of "a bug in lmi", so this one matches instead
of exercising that freedom.

3 is separate from 1 on purpose: by the time a Claude config file is written,
npm has already succeeded, so the outcome is a working `claude` with unwritten
settings. Folding it into 1 would report that the install failed.
"""

EXIT_NPM_FAILED = 1
EXIT_CONFIG_WRITE = 3
EXIT_INTERNAL = 4
