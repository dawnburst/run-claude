"""The `lmi install claude` flow.

Order matters twice over.

First: every question is asked BEFORE anything is modified. A user who
abandons the command at a prompt, or answers "no" to the repair question,
leaves the machine exactly as they found it.

Second: npm runs before any Claude configuration file is touched. If the
install fails there is no claude to configure, and a machine carrying the site's
settings, its marketplaces and a skipped onboarding but no binary looks
provisioned and is not.
"""

import shutil

from . import (claude_json, defaults, gitbash, npm, prompts, sdk, settings,
               statusline)
from .config import build_config
from .exit_codes import EXIT_CONFIG_WRITE, EXIT_INTERNAL
from ..schedule import backend
from ...core import jsonfile
from ...core.errors import EXIT_OK, EXIT_USAGE, LmiError

# A mistyped or half-pasted token is the common case, so the question is put
# again rather than refused outright. Bounded because an unbounded retry is only
# safe for as long as prompts.secret turns a missing terminal into EOFError.
TOKEN_ATTEMPTS = 3

NO_TOKEN = (
    "no auth token was given, so there is nothing to install.\n"
    "    The settings template is installed whole, and the ANTHROPIC_AUTH_TOKEN\n"
    "    in it is a placeholder - writing it through would leave a settings file\n"
    "    that looks configured and fails every call.\n"
    "    Nothing was changed. Run this again with the token to hand."
)

TLS_WARNING = (
    "[WARN] certificate verification is now OFF for every npm install by this\n"
    "       user, not just Claude Code. Anyone who can answer as the registry\n"
    "       host can serve a package whose install scripts run.\n"
    "       Set \"cafile\" to your internal CA and drop \"strict-ssl\" to close\n"
    "       this. \"strict-ssl\": true puts it back on a machine an older lmi\n"
    "       turned it off on."
)

NO_CLAUDE_ON_PATH = (
    "[WARN] npm reported success but `claude` is not on PATH in this shell.\n"
    "       That is normal the first time npm's global bin directory is used:\n"
    "       this process cannot see a PATH change made a moment ago.\n"
    "       Open a new terminal and run `claude`. If it is still missing, add\n"
    "       the `bin` subdirectory of `npm prefix -g` to your PATH."
)

GIT_BASH_MISSING = (
    "[WARN] no Git Bash was found, so %s was not set.\n"
    "       Claude Code needs it to run shell commands on Windows. Install Git\n"
    "       for Windows, or set the variable by hand, and it will pick it up."
)

# The two halves of a statusline are the template's "statusLine" block and the
# script it runs, and they are written by hand in two different files. Either
# one alone is a statusline that does not appear, with nothing on screen to say
# why - so each is said out loud. Neither is an error: only the operator knows
# what their command actually runs.
STATUSLINE_MISSING = (
    '[WARN] the settings template declares a "%s", but no %s was\n'
    "       found beside it, so none was installed. If that block runs the\n"
    "       script this would have written, Claude Code will show nothing.\n"
    "       Expected it at: %s"
)

STATUSLINE_UNUSED = (
    "[WARN] a %s was found beside the settings template, which declares no\n"
    '       "%s" - so it was installed, but nothing will run it.\n'
    "       Installed:        %s\n"
    "       Add the block to: %s"
)

NO_STATUSLINE = (
    "No %s beside the settings template, so no statusline was installed."
)

STATUSLINE_WHAT = "Claude Code statusline script"

# --- the SDK backend ------------------------------------------------------
#
# Every one of these is printed on a path that still exits 0. A degradation
# nobody is told about is indistinguishable from success, and the thing being
# degraded - which backend `lmi schedule` uses - is invisible in the result,
# because both backends exit 0 when they work.

SDK_QUESTION = (
    "Install the Claude Agent SDK, so `lmi schedule` can use the %s backend?\n"
    "  Declining is not a no-op: it sets this machine to the %s backend, which\n"
    "  drives the `claude` command instead and needs no Python package.\n"
    "  Install it"
)

SDK_DECLINED = (
    "The SDK will not be installed, so `lmi schedule` is being set to the %s\n"
    "backend. Change it later with: lmi config schedule --mode %s"
)

NO_INDEX = (
    'No "claude.index" in %s, so the Claude Agent SDK was not installed and\n'
    "`lmi schedule` is being set to the %s backend.\n"
    "    That is a configuration, not a failure - a site that only wants the\n"
    "    `%s` backend needs no PyPI mirror. To use the %s backend instead, add\n"
    "    the key and run this again:\n\n"
    '        "index": "https://artifactory.example.com/api/pypi/pypi-virtual/simple/"'
)

SDK_FAILED = (
    "[WARN] the Claude Agent SDK was not installed, so `lmi schedule` is being\n"
    "       set to the %s backend. Everything else on this machine is\n"
    "       configured and working - this is one of two backends being\n"
    "       unavailable, not a failed install.\n"
    "       Package: %s\n"
    "       Index:   %s\n"
    "       lmi does not populate that index, and cannot tell you when it will\n"
    "       carry the package. Once it does:\n\n"
    "           lmi config schedule --mode %s"
)

SDK_NOT_IMPORTABLE = (
    "[WARN] pip reported success, but %s still cannot be imported by the\n"
    "       interpreter that will run `lmi schedule`:\n"
    "           %s\n"
    "       That is the case pip's exit code cannot see, which is why it is\n"
    "       not what this command trusts."
)

MODE_REPORT = "`lmi schedule` backend: %s (written to %s)"

MODE_REPORT_CLI = (
    "`lmi schedule` backend: %s (written to %s)\n"
    "  The SDK is not available on this machine; the %s backend drives the\n"
    "  `claude` command that was just installed. Switch with:\n"
    "      lmi config schedule --mode %s"
)


def run(args):
    try:
        return _run(args)
    except LmiError:
        # A usage or npm or config-file error, already carrying its exit code
        # and a message cli.main will print. Not ours to reinterpret.
        raise
    except Exception as exc:                    # noqa: BLE001 - deliberate
        raise LmiError(
            "unexpected failure in lmi install: %s: %s"
            % (type(exc).__name__, exc),
            EXIT_INTERNAL,
        )


def _run(args):
    cfg = build_config(args)
    say("Config:   %s" % _describe(cfg.source))
    say("Settings: %s" % cfg.settings_source)

    npm_exe = npm.find()
    say("npm:      %s" % npm_exe)

    # --- ask everything, change nothing ---------------------------------
    if not _agreed_to_proceed():
        say("Nothing was changed.")
        return EXIT_OK

    token = _ask_for_token()
    wants_sdk = _agreed_to_install_sdk(cfg)
    bash_path = _resolve_git_bash()

    # --- from here on the machine changes -------------------------------
    _configure_npm(cfg, npm_exe)
    npm.install(npm_exe, say)

    # After npm and before any Claude config file, extending the order that
    # already holds between those two. An SDK installed onto a machine with no
    # `claude` binary is the same "looks provisioned, is not": the SDK drives
    # Claude Code, it does not replace it. A failing npm therefore reaches
    # neither pip nor a config file.
    mode = _install_sdk(cfg, wants_sdk)

    if bash_path:
        gitbash.persist(bash_path, say)

    stamp = jsonfile.timestamp()
    backups = []
    _write_statusline(cfg, stamp, backups)
    _write_settings(cfg, token, bash_path, settings.path(), stamp, backups)
    _write_onboarding_flag(stamp, backups)
    # Last, after every Claude config write has SUCCEEDED. The schedule.mode
    # key then only ever appears on a machine that got all the way through.
    # A failure earlier leaves lmi.json untouched, which means the default -
    # `sdk` - on a machine where pip may never have run; that is `lmi
    # schedule`'s loud exit 2, not a silent wrong backend, and it is the right
    # side to fail on.
    mode_source = defaults.adopt(cfg.source, say)
    _write_mode(mode_source, mode)

    _report(backups, mode_source, mode)
    return EXIT_OK


# --- questions ------------------------------------------------------------

def _agreed_to_proceed():
    """True unless an install already exists and the user declines to repair."""
    existing = shutil.which("claude")
    if existing is None:
        return True
    say("Claude Code is already installed at %s" % existing)
    return prompts.confirm("Repair the installation?", default=False)


def _ask_for_token():
    """The token to write. Never blank, never None.

    A blank answer used to mean "keep whatever is in the file" or "sign in
    later". Neither survives installing the template whole: there is nothing
    left to keep, and the only document a blank could produce is one carrying
    the template's ANTHROPIC_AUTH_TOKEN placeholder verbatim - which reads as
    configured and fails every call.
    """
    for remaining in range(TOKEN_ATTEMPTS - 1, -1, -1):
        answer = prompts.secret("Claude Code auth token")
        if answer:
            return answer
        if remaining:
            say("The token cannot be blank. %d attempt%s left."
                % (remaining, "" if remaining == 1 else "s"))
    raise LmiError(NO_TOKEN, EXIT_USAGE)


def _agreed_to_install_sdk(cfg):
    """Ask, in the ask-everything block, before the machine changes.

    Deliberately unlike the repair question, where declining changes nothing at
    all: there, nothing had been asked for. Here a decision was made, and the
    decision is about which backend this machine uses - so declining WRITES
    `cli`. Leaving the mode unset instead would leave the default pointing at
    a backend the operator has just declined to install, and `lmi schedule`
    would exit 2 on a machine this command reported as provisioned.

    Not asked at all when there is no index to install from: there is nothing
    to consent to, and the outcome is already decided. That line is printed
    later, beside the rest of the SDK reporting.
    """
    if not cfg.index:
        return False
    return prompts.confirm(
        SDK_QUESTION % (backend.SDK, backend.CLI), default=True
    )


def _resolve_git_bash():
    """The Git Bash path to record, or None. Always None off Windows."""
    if not gitbash.on_windows():
        return None
    found = gitbash.find()
    if found:
        say("Git Bash: %s" % found)
        return found
    say("Git Bash was not found in any of the usual places.")
    answer = prompts.text("Full path to bash.exe (blank to skip)")
    if gitbash.is_valid(answer):
        return answer
    if answer:
        say("That is not a bash or sh executable, or it does not exist.")
    say(GIT_BASH_MISSING % gitbash.VAR)
    return None


def _describe(source):
    """The config path as the user is shown it, before anything is changed.

    The packaged folder is annotated, because it is the one candidate nobody
    put there. A run that reaches it by accident - a mistyped working directory,
    a checkout that was never given a config - installs from a different
    registry than the operator believes, and unannotated the line would read
    exactly like a run that found the site's own file. Printed before the first
    npm command, which is what keeps a last-resort default from being silent.
    """
    if defaults.is_packaged(source):
        return "%s (packaged default)" % source
    return str(source)


# --- changes --------------------------------------------------------------

def _configure_npm(cfg, npm_exe):
    """npm's TLS settings, then the registry.

    Nothing here is inferred. A config that sets neither key leaves the
    machine's npm TLS exactly as it was: `strict-ssl false` is global,
    permanent and covers every later `npm install` by that user, which is too
    much to switch off because a config file happened to omit an unrelated key.
    See config._strict_ssl.
    """
    if cfg.cafile:
        say("Trusting the CA in %s" % cfg.cafile)
        npm.config_set(npm_exe, "cafile", str(cfg.cafile), say)
    if cfg.strict_ssl is not None:
        npm.config_set(
            npm_exe, "strict-ssl", "true" if cfg.strict_ssl else "false", say
        )
        if not cfg.strict_ssl:
            say(TLS_WARNING)
    npm.config_set(npm_exe, "registry", cfg.registry, say)


def _install_sdk(cfg, wants_sdk):
    """Install the SDK if asked to, and return the mode this machine gets.

    A failing pip must NOT fail the install, and that inverts npm.install's
    rule on purpose: npm failing means there is no Claude Code at all, whereas
    pip failing means one of two supported backends is unavailable and the
    other one - the one that drives the binary npm just installed - works
    fine. So: warn, write `cli`, carry on, exit 0.

    What it must never be is quiet. Every path out of here says which backend
    the machine ended up with and why, because a degradation nobody is told
    about is indistinguishable from success, and nothing afterwards reveals it:
    both backends exit 0 when they work.
    """
    if not cfg.index:
        say(NO_INDEX % (cfg.source, backend.CLI, backend.CLI, backend.SDK))
        return backend.CLI
    if not wants_sdk:
        say(SDK_DECLINED % (backend.CLI, backend.CLI))
        return backend.CLI

    code = sdk.install(cfg, say)
    # The exit code is not the check, and is not treated as one. It is only
    # used to tell the two failure stories apart in the output - see
    # SDK_NOT_IMPORTABLE, which is the case pip's rc cannot see at all.
    if sdk.importable():
        return backend.SDK
    if code == 0:
        say(SDK_NOT_IMPORTABLE % (sdk.MODULE, sdk.DISTRIBUTION))
    say(SDK_FAILED % (backend.CLI, sdk.DISTRIBUTION, cfg.index, backend.SDK))
    return backend.CLI


def _write_mode(source, mode):
    """Record the backend in the lmi.json this command read.

    Through backend.write, which is the ONLY writer of this key - `lmi config
    schedule` comes through the same function. Two implementations would be two
    chances to get the merge or the atomic write wrong in only one of them.

    The file is the one discovery resolved, so it exists and is the one
    `lmi schedule` will read back: there is no shadowing case here, unlike
    `lmi config schedule`, which may have to create a file from nothing.

    `source` rather than cfg.source because of the one case where those differ:
    a run that fell through to the packaged config folder writes to the copy
    defaults.adopt has just made in ~/.lmi, never into site-packages, which
    `lmi schedule` does not read and the next upgrade replaces.
    """
    backend.write(source, mode, EXIT_CONFIG_WRITE)


def _write_statusline(cfg, stamp, backups):
    """Install the statusline script beside the template, if there is one.

    Before the settings write, not after, so ~/.claude never holds a
    settings.json naming a script that is not there yet. It also means a
    failed copy stops the command with the machine's previous settings still
    in place, rather than after they have been replaced.

    The existing script is backed up like every other file this command
    overwrites: it may be one the operator wrote by hand, and it is replaced
    whole.
    """
    declared = statusline.declares(cfg.settings)
    if cfg.statusline is None:
        if declared:
            say(STATUSLINE_MISSING % (
                statusline.SETTINGS_KEY, statusline.NAME,
                cfg.settings_source.parent / statusline.NAME,
            ))
        else:
            say(NO_STATUSLINE % statusline.NAME)
        return
    dest = statusline.path()
    _back_up(dest, stamp, STATUSLINE_WHAT, backups)
    statusline.install(cfg.statusline, dest, STATUSLINE_WHAT, EXIT_CONFIG_WRITE)
    say("Wrote %s (from %s)" % (dest, cfg.statusline))
    if not declared:
        say(STATUSLINE_UNUSED % (
            statusline.NAME, statusline.SETTINGS_KEY, dest, cfg.settings_source,
        ))


def _write_settings(cfg, token, bash_path, path, stamp, backups):
    """Install the template over ~/.claude/settings.json.

    The file is replaced, not merged into, so the backup taken first is the only
    surviving copy of what the machine had. It must stay before the write and
    must stay fatal - jsonfile.backup refuses to go on when the copy fails, and
    downgrading that to a warning would make a failed copy unrecoverable rather
    than merely noisy.

    Nothing reads the existing file. That is deliberate: parsing it was only
    ever needed to merge into it, and a settings.json a user hand-edited into
    invalid JSON would otherwise block an install that is about to replace it
    anyway.
    """
    _back_up(path, stamp, "Claude Code settings", backups)
    doc = settings.compose(cfg.settings, token, bash_path)
    # 0600 unconditionally: the token is mandatory, so the file always holds a
    # credential. On Windows os.chmod only toggles the read-only bit and grants
    # no protection - lmi does not claim otherwise there.
    jsonfile.write(path, doc, "Claude Code settings", EXIT_CONFIG_WRITE, mode=0o600)
    say("Wrote %s (from %s)" % (path, cfg.settings_source))


def _write_onboarding_flag(stamp, backups):
    path = claude_json.path()
    doc = jsonfile.read(path, "Claude Code state", EXIT_CONFIG_WRITE)
    if not claude_json.needs_update(doc):
        say("Onboarding is already marked complete.")
        return
    _back_up(path, stamp, "Claude Code state", backups)
    jsonfile.write(
        path, claude_json.mark_complete(doc), "Claude Code state", EXIT_CONFIG_WRITE
    )
    say("Marked onboarding complete in %s" % path)


def _back_up(path, stamp, what, backups):
    made = jsonfile.backup(path, stamp, what, EXIT_CONFIG_WRITE)
    if made:
        backups.append(made)


# --- reporting ------------------------------------------------------------

def _report(backups, mode_source, mode):
    """What happened, once. `mode_source` is where the backend was actually
    written, which is not cfg.source on the one path where those differ - a run
    that fell through to the packaged folder wrote to the ~/.lmi copy adopt just
    made. Naming the packaged file here would send an operator to edit a file
    inside site-packages that the next upgrade replaces."""
    say("")
    if backups:
        say("Your previous configuration was saved:")
        for path in backups:
            say("  %s" % path)
        say("These are never deleted; remove them yourself when you are happy.")
    found = shutil.which("claude")
    if found:
        say("Claude Code is installed: %s" % found)
    else:
        say(NO_CLAUDE_ON_PATH)
    # This is where an operator looks to see what happened, so the backend is
    # stated here as well as at the moment it was decided - by the time the
    # command ends, the line that decided it has scrolled past a pip install.
    if mode == backend.SDK:
        say(MODE_REPORT % (mode, mode_source))
    else:
        say(MODE_REPORT_CLI % (mode, mode_source, mode, backend.SDK))


def say(message=""):
    """Console output.

    Deliberately not core.log.Logger: this command writes no log file, and a
    Logger needs a path. `print` is the whole requirement.
    """
    print(message)
