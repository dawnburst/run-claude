"""Console output for `lmi config` and its subcommands.

One line of code in its own module for one reason: the subcommand registry
means runner.py imports the subcommands and the subcommands print, so `say`
cannot live in runner.py without a cycle. runner.py re-exports it, so the name
every existing caller and test knows still resolves there.

Deliberately not core.log.Logger: this command writes no log file, and a Logger
needs a path. `print` is the whole requirement.
"""


def say(message=""):
    print(message)
