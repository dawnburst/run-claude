"""Building and running one pip command.

Promoted out of lmi/commands/upgrade/pip.py when `lmi install claude` became
the second command that needs to run pip - the condition CLAUDE.md section 2
names for moving something into core/: then, not in advance.

Only what has no command flavour moved. How to spell `<interpreter> -m pip`,
how to point it at an index, and how to run it are the same questions whatever
is being installed. What is being installed, whether a failure is fatal, and
what to say when it is are each their own command's, and stayed there - which
is why `latest()` and the self-upgrade reasoning are still in `upgrade/pip.py`.

Every invocation is a list argv through subprocess.run, with the shell never
invoked: the index URL comes from a config file and must never reach a shell.
Output is inherited rather than captured, so pip's own progress and errors
reach the user as they happen, and check=False so a non-zero exit returns
instead of raising.

Note this module is named `pip` and lives inside a package, so `import pip`
elsewhere still finds the real one; nothing here imports pip as a library.
"""

import subprocess


def prefix(interpreter):
    """`<interpreter> -m pip`, as an argv fragment.

    pip is never found through PATH, in either command that runs it. A `pip`
    on PATH belongs to whichever interpreter happens to be first there, which
    is not necessarily the one that will import what it installs: `lmi` from
    the bootstrap scripts lives in its own virtual environment, so an install
    into a different interpreter exits 0 and leaves the package unimportable
    from the one that needs it. The interpreter IS the seam, which is also why
    the `fake_pip` fixture fakes an interpreter rather than a pip.
    """
    return [str(interpreter), "-m", "pip"]


def index_argv(index, cafile):
    """`--index-url`, plus `--cert` when a CA file is configured.

    pip's option is --cert. npm's is cafile; they are not interchangeable, and
    passing one where the other belongs fails much later as an unrelated TLS
    error.
    """
    argv = ["--index-url", index]
    if cafile:
        argv += ["--cert", str(cafile)]
    return argv


def run(argv, say):
    """Echo the command, run it, and return its exit code.

    Returns rather than raises, always. What a non-zero exit means differs
    between the callers - fatal for `lmi upgrade`, a degraded but successful
    install for `lmi install claude` - and core/ has no business deciding
    that.
    """
    say("  $ " + " ".join(argv))
    return subprocess.run(argv).returncode
