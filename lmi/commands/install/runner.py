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

from . import claude_json, gitbash, npm, prompts, settings, statusline
from .config import build_config
from .exit_codes import EXIT_CONFIG_WRITE, EXIT_INTERNAL
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
    "       Set \"cafile\" in the config file to your internal CA to close this."
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
    say("Config:   %s" % cfg.source)
    say("Settings: %s" % cfg.settings_source)

    npm_exe = npm.find()
    say("npm:      %s" % npm_exe)

    # --- ask everything, change nothing ---------------------------------
    if not _agreed_to_proceed():
        say("Nothing was changed.")
        return EXIT_OK

    token = _ask_for_token()
    bash_path = _resolve_git_bash()

    # --- from here on the machine changes -------------------------------
    _configure_npm(cfg, npm_exe)
    npm.install(npm_exe, say)

    if bash_path:
        gitbash.persist(bash_path, say)

    stamp = jsonfile.timestamp()
    backups = []
    _write_statusline(cfg, stamp, backups)
    _write_settings(cfg, token, bash_path, settings.path(), stamp, backups)
    _write_onboarding_flag(stamp, backups)

    _report(backups)
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


# --- changes --------------------------------------------------------------

def _configure_npm(cfg, npm_exe):
    if cfg.cafile:
        say("Trusting the CA in %s" % cfg.cafile)
        npm.config_set(npm_exe, "cafile", str(cfg.cafile), say)
    else:
        npm.config_set(npm_exe, "strict-ssl", "false", say)
        say(TLS_WARNING)
    npm.config_set(npm_exe, "registry", cfg.registry, say)


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

def _report(backups):
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


def say(message=""):
    """Console output.

    Deliberately not core.log.Logger: this command writes no log file, and a
    Logger needs a path. `print` is the whole requirement.
    """
    print(message)
