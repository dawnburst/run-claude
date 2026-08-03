"""One line to the console and to the log file.

Format matches run-claude.bat: plain lines, no per-line timestamps, and the
same [WARN] / [ERROR] / [QUOTA] tags, so existing logs stay comparable.
"""


class Logger:
    def __init__(self, path):
        self.path = path

    def line(self, msg=""):
        print(msg)
        with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(msg + "\n")

    def warn(self, msg):
        self.line("[WARN] " + msg)

    def error(self, msg):
        self.line("[ERROR] " + msg)

    def quota(self, msg):
        self.line("[QUOTA] " + msg)
