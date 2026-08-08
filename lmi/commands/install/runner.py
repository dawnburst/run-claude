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

from . import claude_json, gitbash, jsonfile, npm, prompts, settings
from .config import build_config
from .exit_codes import EXIT_INTERNAL
from ...core.errors import EXIT_OK, LmiError

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
    say("Config: %s" % cfg.source)

    npm_exe = npm.find()
    say("npm:    %s" % npm_exe)

    # --- ask everything, change nothing ---------------------------------
    if not _agreed_to_proceed():
        say("Nothing was changed.")
        return EXIT_OK

    settings_path = settings.path()
    current = jsonfile.read(settings_path, "Claude Code settings")
    token = _ask_for_token(current)
    bash_path = _resolve_git_bash()

    # --- from here on the machine changes -------------------------------
    _configure_npm(cfg, npm_exe)
    npm.install(npm_exe, say)

    if bash_path:
        gitbash.persist(bash_path, say)

    stamp = jsonfile.timestamp()
    backups = []
    _write_settings(cfg, current, token, bash_path, settings_path, stamp, backups)
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


def _ask_for_token(current):
    """The token to write, or None to leave whatever is there."""
    if settings.token_of(current):
        say("An auth token is already configured.")
        answer = prompts.secret(
            "Claude Code auth token (blank to keep the existing one)"
        )
    else:
        answer = prompts.secret(
            "Claude Code auth token (blank to skip and sign in later)"
        )
    return answer or None


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


def _write_settings(cfg, current, token, bash_path, path, stamp, backups):
    env = dict(cfg.env)
    if token:
        env[settings.TOKEN_KEY] = token
    if bash_path:
        env[gitbash.VAR] = bash_path

    _back_up(path, stamp, "Claude Code settings", backups)
    merged = settings.merge(current, env, cfg.marketplaces)
    # 0600 whenever the file ends up holding a credential. On Windows os.chmod
    # only toggles the read-only bit and grants no protection - lmi does not
    # claim otherwise there.
    mode = 0o600 if settings.token_of(merged) else None
    jsonfile.write(path, merged, "Claude Code settings", mode=mode)
    say("Wrote %s" % path)


def _write_onboarding_flag(stamp, backups):
    path = claude_json.path()
    doc = jsonfile.read(path, "Claude Code state")
    if not claude_json.needs_update(doc):
        say("Onboarding is already marked complete.")
        return
    _back_up(path, stamp, "Claude Code state", backups)
    jsonfile.write(path, claude_json.mark_complete(doc), "Claude Code state")
    say("Marked onboarding complete in %s" % path)


def _back_up(path, stamp, what, backups):
    made = jsonfile.backup(path, stamp, what)
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
