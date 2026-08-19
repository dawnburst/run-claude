#!/usr/bin/env bash
# Install the `lmi` CLI on Linux (including WSL) so that typing `lmi` works.
#
#     ./scripts/install-linux.sh                 # from a clone
#     ./install-linux.sh --wheel lmi-0.1.0-py3-none-any.whl
#
# It installs the wheel - one file, `lmi-<version>-py3-none-any.whl`, the same
# file on every operating system - into a small virtual environment of its own,
# then symlinks the `lmi` command pip generates onto your PATH.
#
# Why a virtual environment rather than `pip install --user`: Debian, Ubuntu and
# most current distributions mark the system Python "externally managed" (PEP
# 668), so pip refuses to install into it and tells you to use a virtual
# environment or pipx. Verified on Ubuntu 24.04. A venv of our own sidesteps that
# without --break-system-packages, which is the flag whose whole purpose is to
# risk your distribution's Python.
#
# The venv is at ~/.local/share/lmi/venv and holds nothing but lmi, so the clone
# is disposable once this has run.
#
# `set -e` is right here, unlike in the runner itself: a half-finished install is
# worse than a stopped one.
set -euo pipefail

VENV_DIR="$HOME/.local/share/lmi/venv"
LINK_DIR="$HOME/.local/bin"
WHEEL=""
UNINSTALL=0
MIN_PY="3.9"

# --- how we talk to the user ----------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; Z=$'\033[0m'
else
    B=""; G=""; Y=""; R=""; Z=""
fi
step() { printf '%s==>%s %s\n' "$B" "$Z" "$1"; }
ok()   { printf '    %sok%s %s\n' "$G" "$Z" "$1"; }
warn() { printf '    %swarning%s %s\n' "$Y" "$Z" "$1"; }
die()  { printf '\n%serror%s %s\n' "$R" "$Z" "$1" >&2; exit 1; }

usage() {
    cat <<'EOF'
Install the lmi CLI on Linux or WSL.

    ./scripts/install-linux.sh [options]

Options:
  --wheel PATH     the wheel to install. Default: the newest lmi-*.whl beside
                   this script or in dist/, else built from the checkout.
  --link-dir DIR   where to put the `lmi` command (default: ~/.local/bin)
  --venv-dir DIR   where to keep lmi's virtual environment
                   (default: ~/.local/share/lmi/venv)
  --uninstall      remove the command and the virtual environment
  -h, --help       show this help

Needs no sudo. Re-run it to upgrade.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --wheel)     [ $# -ge 2 ] || die "--wheel needs a path"
                     WHEEL="$2"; shift 2 ;;
        --link-dir)  [ $# -ge 2 ] || die "--link-dir needs a directory"
                     LINK_DIR="$2"; shift 2 ;;
        --venv-dir)  [ $# -ge 2 ] || die "--venv-dir needs a directory"
                     VENV_DIR="$2"; shift 2 ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help)   usage; exit 0 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TARGET="$LINK_DIR/lmi"

# Is the thing at $TARGET ours? Only ever remove or replace our own. Anything
# else is someone else's lmi and we refuse to touch it.
ours() {
    # The current shape: a symlink into our venv.
    if [ -L "$1" ]; then
        case "$(readlink "$1")" in "$VENV_DIR"/*) return 0 ;; esac
        return 1
    fi
    [ -f "$1" ] || return 1
    # Or the zipapp that the previous version of this installer left here, so
    # that upgrading from it replaces the file rather than stopping with "not
    # installed by this script". A zip stores its entry names uncompressed in
    # the central directory, so grep finds them without needing Python - which
    # matters because --uninstall must work even if Python has since gone.
    LC_ALL=C grep -aq 'lmi/cli\.py' "$1"
}

# --- uninstall -------------------------------------------------------------
if [ "$UNINSTALL" -eq 1 ]; then
    step "Removing the lmi command"
    if [ ! -e "$TARGET" ] && [ ! -L "$TARGET" ]; then
        ok "nothing at $TARGET"
    elif ours "$TARGET"; then
        rm -f "$TARGET"; ok "removed $TARGET"
    else
        die "$TARGET was not installed by this script - leaving it alone.
    Remove it yourself if you are sure, or use --link-dir."
    fi
    step "Removing the virtual environment"
    if [ -d "$VENV_DIR" ]; then rm -rf "$VENV_DIR"; ok "removed $VENV_DIR"; else ok "none"; fi
    printf '\n%sUninstalled.%s\n' "$B" "$Z"
    exit 0
fi

# --- 1. Python -------------------------------------------------------------
step "Checking Python"
command -v python3 >/dev/null 2>&1 || die \
    "python3 is not on PATH. Install Python $MIN_PY or newer and re-run."
PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 - "$MIN_PY" <<'EOF' || die "Python $PY_VER is too old; $MIN_PY or newer is required."
import sys
need = tuple(int(p) for p in sys.argv[1].split("."))
sys.exit(0 if sys.version_info[:2] >= need else 1)
EOF
ok "python3 is $PY_VER (need $MIN_PY or newer)"

# --- 2. the wheel ----------------------------------------------------------
# Newest first by modification time. Version-sorting the names would need
# either sort -V, which is not everywhere, or real parsing; mtime is enough
# because the only way two wheels are here is that one was just built.
newest_wheel() {
    [ -d "$1" ] || return 1
    ls -t "$1"/lmi-*.whl 2>/dev/null | head -1
}

step "Finding the wheel"
if [ -n "$WHEEL" ]; then
    [ -f "$WHEEL" ] || die "no such wheel: $WHEEL"
else
    # Beside the script first: that is the shape of a machine with no git,
    # where the script and the wheel were downloaded into the same folder.
    WHEEL="$(newest_wheel "$SCRIPT_DIR" || true)"
    [ -n "$WHEEL" ] || WHEEL="$(newest_wheel "$REPO/dist" || true)"
fi

if [ -z "$WHEEL" ]; then
    [ -f "$REPO/pyproject.toml" ] || die \
        "no wheel found, and no checkout to build one from.

    Either download lmi-<version>-py3-none-any.whl next to this script, or
    pass it explicitly:

        ./install-linux.sh --wheel /path/to/lmi-0.1.0-py3-none-any.whl"
    step "Building the wheel from $REPO"
    # Needs setuptools, which pip fetches unless it is already local - so this
    # is the one step that wants a network. An air-gapped machine should carry
    # the built wheel in instead; installing it needs nothing.
    #
    # Built into a scratch directory rather than straight into dist/, because a
    # failed build here does not look like one: see the fallback below, which
    # leaves an empty UNKNOWN-0.0.0-py3-none-any.whl behind. That must not be
    # left lying beside the real wheels, where `--wheel` and a later reader
    # would both have to know to ignore it.
    BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/lmi-build.XXXXXX")" \
        || die "could not create a temporary build directory."
    trap 'rm -rf "$BUILD_DIR"' EXIT INT TERM
    BUILD_LOG="$BUILD_DIR/build.log"

    # Quiet while it works; the log is printed only if we end up failing.
    BUILD_RC=0
    python3 -m pip wheel --no-deps --quiet --wheel-dir "$BUILD_DIR" "$REPO" \
        >"$BUILD_LOG" 2>&1 || BUILD_RC=$?

    # Exit 0 with no lmi-*.whl, and only that, is the signature worth retrying.
    # A non-zero pip is a genuine build failure - most often no network, which a
    # second pip cannot fix either - and retrying it would make an air-gapped
    # machine sit through a venv and two more index timeouts before failing with
    # the message it could have had straight away.
    if [ "$BUILD_RC" -eq 0 ] && [ -z "$(newest_wheel "$BUILD_DIR" || true)" ]; then
        # pip can exit 0 and still not have built lmi, whenever the
        # setuptools>=61 that pyproject.toml asks for
        # does not reach the build backend - a distro pip old enough to ignore
        # build-system.requires, or one whose build environment mis-resolves its
        # own paths (this is what the Command Line Tools pip does on macOS).
        # The build then falls back to the distro's setuptools, and anything
        # before 61 predates PEP 621 and so cannot read [project] at all: it
        # writes a 1.7KB UNKNOWN-0.0.0-py3-none-any.whl containing nothing but
        # metadata, and reports success.
        #
        # Do not "fix" this by relaxing the wheel glob to *.whl. That empty
        # wheel installs cleanly, provides no `lmi`, and would be caught three
        # steps later as a missing console script - if at all.
        #
        # A venv gets its own current pip, which has neither problem.
        warn "that pip could not build the wheel; retrying with a newer one"
        BOOT="$BUILD_DIR/venv"
        if python3 -m venv "$BOOT" >>"$BUILD_LOG" 2>&1; then
            # Best effort, and bounded: ensurepip's pip is as old as the
            # interpreter, so it usually does need upgrading, but an index that
            # accepts connections and then stalls must not hang the install.
            # Failure here is fine - the build below reports it better.
            "$BOOT/bin/python" -m pip install --quiet --upgrade \
                --timeout 15 --retries 1 pip >>"$BUILD_LOG" 2>&1 || true
            "$BOOT/bin/python" -m pip wheel --no-deps --quiet \
                --wheel-dir "$BUILD_DIR" "$REPO" >>"$BUILD_LOG" 2>&1 || true
        fi
    fi

    BUILT="$(newest_wheel "$BUILD_DIR" || true)"
    if [ -z "$BUILT" ]; then
        printf '\n' >&2
        tail -n 20 "$BUILD_LOG" >&2 || true
        die "could not build the wheel; the last of the build log is above.

    On a machine with no network that is expected: pip fetches setuptools to
    build. Carry the built wheel in and pass it with --wheel.
    A venv build also needs python3-venv:

        sudo apt install python3-venv"
    fi
    mkdir -p "$REPO/dist" && cp "$BUILT" "$REPO/dist/" \
        || die "built $(basename "$BUILT") but could not copy it into $REPO/dist."
    WHEEL="$REPO/dist/$(basename "$BUILT")"
fi
ok "$(basename "$WHEEL")"

# --- 3. the virtual environment -------------------------------------------
step "Preparing the virtual environment"
mkdir -p "$(dirname "$VENV_DIR")"
VENV_PY="$VENV_DIR/bin/python"
if [ -x "$VENV_PY" ] && "$VENV_PY" -c "" 2>/dev/null; then
    ok "reusing $VENV_DIR"
else
    [ -e "$VENV_DIR" ] && { warn "existing $VENV_DIR is not usable, rebuilding it"; rm -rf "$VENV_DIR"; }
    # Both streams are discarded, not just stderr: when ensurepip is missing,
    # venv prints its "install python3-venv" advice on STDOUT, which leaked
    # into a successful install and read like a failure.
    if python3 -m venv "$VENV_DIR" >/dev/null 2>&1; then
        ok "created $VENV_DIR"
    elif rm -rf "$VENV_DIR" && python3 -m venv --without-pip "$VENV_DIR" >/dev/null 2>&1; then
        # Debian and Ubuntu ship the venv module's bootstrap separately, so
        # plain `venv` fails there with "ensurepip is not available" - on a
        # machine that is otherwise perfectly able to install this wheel.
        # --without-pip needs no ensurepip, and the system pip can still
        # populate the venv from outside (see below). Verified on Ubuntu 24.04
        # with python3-venv absent.
        ok "created $VENV_DIR (it has no pip of its own; using the system pip)"
    else
        rm -rf "$VENV_DIR"
        die "could not create a virtual environment, even without pip.

    On Debian and Ubuntu this is one missing package:

        sudo apt install python3-venv        # or python${PY_VER}-venv

    Then re-run this script."
    fi
fi

step "Installing the wheel into it"
# The venv's own pip when it has one, otherwise the system pip aimed at the
# venv - which is what makes a --without-pip venv usable. `--python` must come
# before the subcommand, and needs pip 22.3 or newer.
if "$VENV_PY" -m pip --version >/dev/null 2>&1; then
    PIP=("$VENV_PY" -m pip install)
else
    PIP=(python3 -m pip --python "$VENV_PY" install)
fi
# --no-index: never reach for the network. Safe because lmi declares no
# dependencies, which tests/test_packaging.py exists to keep true.
# --force-reinstall: the version does not change on every source change, and
# without it pip treats reinstalling 0.1.0 over 0.1.0 as nothing to do - so an
# upgrade would silently keep the old code.
"${PIP[@]}" --quiet --no-index --force-reinstall "$WHEEL" || die \
    "pip failed to install $WHEEL

    If it reported an unknown option --python, the system pip is older than
    22.3. Install the venv package so the virtual environment gets its own pip:

        sudo apt install python3-venv        # or python${PY_VER}-venv"
[ -x "$VENV_DIR/bin/lmi" ] || die \
    "pip reported success but $VENV_DIR/bin/lmi is missing.
    That means the wheel has no console script - check [project.scripts]."
ok "installed"

# --- 4. onto the PATH ------------------------------------------------------
step "Linking it onto your PATH"
mkdir -p "$LINK_DIR"
if { [ -e "$TARGET" ] || [ -L "$TARGET" ]; } && ! ours "$TARGET"; then
    die "$TARGET already exists and was not installed by this script.
    Move it aside and re-run, or choose another directory with --link-dir."
fi
ln -sfn "$VENV_DIR/bin/lmi" "$TARGET"
ok "linked $TARGET -> $VENV_DIR/bin/lmi"

# --- 5. verify -------------------------------------------------------------
step "Verifying"
VERSION="$("$TARGET" --version 2>&1)" || die "$TARGET did not run: $VERSION"
ok "$VERSION"

# --- 6. the config folder --------------------------------------------------
# `lmi config init` copies the config folder inside the wheel to ~/.lmi. It
# keeps every file that is already there, so this is safe on every re-run and on
# a machine whose folder has been edited for a year.
#
# Warned, never fatal - hence `if`, which `set -e` leaves alone. An lmi that is
# installed, linked and verified is a successful install; dying here would
# report the whole thing as a failure over a folder the user can create with one
# command. That is the same choice `lmi install claude` makes about pip.
step "Filling ~/.lmi with lmi's own config folder"
if INIT_OUT="$("$TARGET" config init 2>&1)"; then
    printf '%s\n' "$INIT_OUT" | sed 's/^/    /'
else
    warn "lmi config init failed - run it yourself, it changes nothing else:"
    printf '%s\n' "$INIT_OUT" | sed 's/^/    /'
fi

ON_PATH=0
case ":${PATH}:" in *":$LINK_DIR:"*) ON_PATH=1 ;; esac

printf '\n%sInstalled.%s\n' "$B" "$Z"
if [ "$ON_PATH" -eq 1 ]; then
    RESOLVED="$(command -v lmi 2>/dev/null || true)"
    if [ "$RESOLVED" = "$TARGET" ]; then
        printf '  Run: %slmi --version%s\n' "$B" "$Z"
    elif [ -n "$RESOLVED" ]; then
        warn "another lmi comes first on your PATH: $RESOLVED"
        printf '    Remove it, or reorder PATH so %s wins.\n' "$LINK_DIR"
    else
        printf '  Open a new terminal, then run: %slmi --version%s\n' "$B" "$Z"
    fi
else
    warn "$LINK_DIR is not on your PATH, so the bare \`lmi\` will not resolve yet."
    printf '    Add it, then open a new terminal:\n\n'
    printf '        echo '\''export PATH="%s:$PATH"'\'' >> ~/.bashrc\n' "$LINK_DIR"
    printf '        source ~/.bashrc\n\n'
    printf '    Use ~/.zshrc instead if your shell is zsh (echo $SHELL tells you).\n'
fi
printf '\n  lmi needs the Claude Code CLI on PATH: %sclaude --version%s\n' "$B" "$Z"
printf '  If it is missing, install it and run %sclaude auth login%s once -\n' "$B" "$Z"
printf '  the sign-in is interactive and lmi cannot do it for you.\n'
printf '\n  %slmi install claude%s does both: it installs the Claude Code CLI and\n' "$B" "$Z"
printf '  sets up the Claude Agent SDK backend that %slmi schedule%s uses by\n' "$B" "$Z"
printf '  default. This script deliberately installs neither - it reads no\n'
printf '  config file, so it has no registry, no package index and no CA file.\n'
printf '\n  Re-run this script to upgrade. Uninstall with %s--uninstall%s.\n' "$B" "$Z"
