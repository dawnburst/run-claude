"""The once-a-day "a newer lmi exists" line, printed before any command runs.

The machines that most need upgrading are the ones nobody types `lmi upgrade`
on: a box running `lmi schedule` under cron or Task Scheduler, where the only
evidence anybody reads is a log file. So every command reports, at most once a
day, that the repository has a newer version tag - and suggests the command that
would install it.

**It suggests. It never acts.** A tool that replaces its own binary because it
noticed a tag is a tool that changes behaviour on a machine nobody touched,
which is the opposite of what an unattended runner is for.

Three properties, and all three are load-bearing:

  * **It never fails a command.** Every exception is swallowed, including ones
    `lmi upgrade` itself treats as fatal - an unparseable config file is exit 2
    there, by design, and must be silence here, or one bad config file makes the
    whole CLI unusable.
  * **It says nothing whenever it is unsure.** No repo, no git, a timeout, a tag
    nobody can order, a running version that does not parse. A notice that cries
    wolf teaches an operator to ignore it, and then the real one, months later,
    is ignored too.
  * **It touches the network at most once a day.** This is the only network call
    on `lmi schedule`'s startup path, so the cache and the timeout are not
    optimisations - a slow git host would otherwise delay an unattended run's
    first iteration on every invocation.

It lives in this package, and `cli.py` calls it in one line. That is the first
time cli.py has imported a command, and it is the narrower of two evils: the
notice needs the package name, the repo URL, the `lmi` config section and the
version comparison, all four of which are defined here - and a second spelling
of any of them is a notice suggesting an upgrade to something `lmi upgrade`
would not install. cli.py still learns nothing about the command registry.
"""

from datetime import datetime
from pathlib import Path

from . import repo
from .config import SECTION
from ... import __version__
from ...core import config as core_config
from ...core import jsonfile

# The version this process is running - the same value `lmi upgrade` calls
# RUNNING, read at import for the same reason.
RUNNING = __version__

# The command this notice must never appear for: it is about to say the same
# thing with more detail, and having asked for it is not a reason to be told.
QUIET_FOR = ("upgrade",)

CACHE_NAME = "version-check.json"

# How long an answer stays good. A day, because a release is not an event a
# machine needs to hear about within the hour, and because the alternative -
# asking on every invocation - puts a network round trip in front of every
# `lmi schedule` start.
MAX_AGE_HOURS = 24

STAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"

MESSAGE = "[lmi] a newer lmi is available: %s (running %s). Run: lmi upgrade"


def maybe_say(command, timeout=repo.TIMEOUT, out=print):
    """Print the notice if there is one to print. Never raises, whatever happens.

    `command` is the subcommand about to run, so `lmi upgrade` can be excluded.
    `out` is a parameter only so the tests can watch it; the default is the
    whole requirement, exactly as `lmi upgrade`'s own `say` is a bare print.
    """
    try:
        latest = _latest(command, timeout)
    except Exception:                       # noqa: BLE001 - see the docstring
        # Deliberately bare, and deliberately silent. This function is a
        # diagnostic on the startup path of every command; a diagnostic that can
        # break what it diagnoses is worse than none - item 24's rule, and item
        # 62 is that it applies here with the whole CLI at stake rather than one
        # command's question.
        return
    if latest is None:
        return
    out(MESSAGE % (latest, RUNNING))


def cache_path():
    """Where the answer is remembered: beside the config folder's own files."""
    return Path(core_config.expand("~/.lmi")) / CACHE_NAME


def _latest(command, timeout):
    """The newer version to report, or None. Every uncertainty is None."""
    if command in QUIET_FOR:
        return None
    url, enabled = _configured()
    if url is None or not enabled:
        return None
    latest = _cached(url)
    if latest is None:
        tag = repo.newest_tag(url, timeout=timeout)
        if tag is None:
            # Not remembered as "nothing", deliberately: a failed lookup is not
            # an answer, and caching it would mean a machine that was briefly
            # offline saying nothing for a day.
            return None
        latest = repo.version_string(tag.name)
        _remember(url, latest)
    if not repo.is_newer(latest, RUNNING):
        return None
    return latest


def _configured():
    """(repo URL or None, is the check enabled?) - from the discovered config.

    Read here rather than through upgrade/config.build_config, which raises for
    a file this function must merely shrug at: `find` turns "no config file"
    into a usage error naming everywhere it looked, which is right for a command
    the operator ran on purpose and wrong for a line printed before every other
    one. Same for a section that is missing or a value that is malformed.

    The KEY NAMES are the ones upgrade/config.py defines, though, and that is
    the point of living in this package: a second spelling of "repo" here would
    be a notice watching a URL the upgrade never installs from.
    """
    path, _ = core_config.find_optional(None)
    if path is None:
        return None, True
    section = core_config.load(path).get(SECTION)
    if not isinstance(section, dict):
        return None, True
    url = section.get("repo")
    if not isinstance(url, str) or not url.strip():
        return None, True
    enabled = section.get("version_check", True)
    if not isinstance(enabled, bool):
        # upgrade/config._version_check refuses this with exit 2, which is right
        # for a command that was asked to install something. Here the operator
        # is running some other command entirely, so the malformed value is
        # treated as the safe reading - no notice - and they will hear about it
        # the next time they run `lmi upgrade`.
        return None, False
    return url.strip(), enabled


def _cached(url):
    """The remembered answer if it is still good, else None.

    Keyed by URL so that re-pointing `lmi.repo` invalidates it: reporting the
    old remote's tags against the new one's configuration is the kind of wrong
    that looks exactly like right.
    """
    path = cache_path()
    try:
        doc = jsonfile.read(path, "lmi version check", 3)
    except Exception:                       # noqa: BLE001 - a miss, not a fault
        return None
    if not isinstance(doc, dict) or doc.get("repo") != url:
        return None
    latest = doc.get("latest")
    if not isinstance(latest, str):
        return None
    try:
        checked = datetime.strptime(str(doc.get("checked")), STAMP_FORMAT)
    except (TypeError, ValueError):
        return None
    age = datetime.now() - checked
    if age.total_seconds() < 0 or age.total_seconds() > MAX_AGE_HOURS * 3600:
        # A negative age means the clock moved backwards, or the file came from
        # elsewhere; either way it is not an answer about now.
        return None
    return latest


def _remember(url, latest):
    """Write the answer. A failure means asking again tomorrow, not an error.

    Through core/jsonfile.write, so this inherits the atomic replace and the
    0600 birth mode rather than a hand-rolled open - the file sits in ~/.lmi
    beside documents that do carry credentials, and one writer for all of them
    is how that stays true.
    """
    doc = {
        "repo": url,
        "latest": latest,
        "checked": datetime.now().strftime(STAMP_FORMAT),
    }
    try:
        jsonfile.write(cache_path(), doc, "lmi version check", 3)
    except Exception:                       # noqa: BLE001 - see the docstring
        pass
