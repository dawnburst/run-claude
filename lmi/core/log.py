"""One line to the console and to the log file.

Plain lines, no per-line timestamps, and the [WARN] / [ERROR] / [QUOTA] tags
that an unattended run's log is searched for afterwards.

Nothing here may raise. An append failure must degrade to console output and
leave the run intact: the first version let the PermissionError out of
Logger.line, which reached the runner's error handler, which called log.error,
which raised the same error again - a two-level traceback and exit 1,
indistinguishable from a failed claude call. A broken log must degrade, not
decide the exit code.
"""

import sys


class Logger:
    def __init__(self, path):
        self.path = path
        self.file_broken = False

    def line(self, msg=""):
        self._to_console(msg)
        if self.file_broken:
            return
        try:
            with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(msg + "\n")
        except Exception as exc:
            # Warn once, then stay quiet: one warning per line would bury the
            # run's real output.
            self.file_broken = True
            self._to_console(
                "[WARN] the log file %s cannot be written (%s) - continuing "
                "with console output only" % (self.path, exc),
                stream=sys.stderr,
            )

    def warn(self, msg):
        self.line("[WARN] " + msg)

    def error(self, msg):
        self.line("[ERROR] " + msg)

    # No quota() here on purpose. [WARN] and [ERROR] are tags any command
    # could want; a claude usage limit means nothing to `lmi install`. A
    # command that needs its own tag writes it inline, the way runner.py does
    # with [QUOTA] - shared code should not learn one command's vocabulary.

    @staticmethod
    def _to_console(msg, stream=None):
        stream = stream or sys.stdout
        try:
            print(msg, file=stream)
        except Exception:
            # A console codepage that cannot represent the text (cp862 and a
            # Hebrew path, say) must not kill the run either.
            try:
                encoding = getattr(stream, "encoding", None) or "ascii"
                print(
                    msg.encode(encoding, "replace").decode(encoding, "replace"),
                    file=stream,
                )
            except Exception:
                pass
