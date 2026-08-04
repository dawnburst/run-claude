#!/usr/bin/env bash
# Install the `lmi` CLI on Linux (including WSL) so that typing `lmi` works.
#
# Run it from inside a clone of this repository:
#
#     ./scripts/install-linux.sh
#
# What it does, and nothing more:
#   1. checks for Python 3.9 or newer
#   2. creates a virtual environment in the clone (.venv)
#   3. installs this package into that environment
#   4. symlinks the environment's `lmi` launcher into a directory on your PATH
#   5. verifies the result, and tells you exactly what to fix if PATH is wrong
#
# It never uses sudo, never writes outside the clone and the link directory, and
# is safe to run again - re-running repairs a broken install rather than
# duplicating it.
#
# `set -e` is right here, unlike in the runner itself: a half-finished install
# is worse than a stopped one.
set -euo pipefail

LINK_DIR="$HOME/.local/bin"
EDITABLE=0
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
  --link-dir DIR   where to put the `lmi` launcher (default: ~/.local/bin)
  --editable       install in editable mode, so `lmi` tracks this checkout
  --uninstall      remove the launcher and the virtual environment
  -h, --help       show this help

Run it from inside a clone of the repository. It needs no sudo.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --link-dir) [ $# -ge 2 ] || die "--link-dir needs a directory"
                    LINK_DIR="$2"; shift 2 ;;
        --editable) EDITABLE=1; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
done

# --- locate the clone we live in -------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VENV="$REPO/.venv"
LAUNCHER="$VENV/bin/lmi"
LINK="$LINK_DIR/lmi"

[ -f "$REPO/pyproject.toml" ] || die \
    "$REPO does not look like the repository (no pyproject.toml).
    Run this script from inside a clone, as ./scripts/install-linux.sh"

# --- uninstall -------------------------------------------------------------
if [ "$UNINSTALL" -eq 1 ]; then
    step "Removing the launcher"
    if [ -L "$LINK" ] || [ -f "$LINK" ]; then
        rm -f "$LINK"; ok "removed $LINK"
    else
        ok "nothing at $LINK"
    fi
    step "Removing the virtual environment"
    if [ -d "$VENV" ]; then
        rm -rf "$VENV"; ok "removed $VENV"
    else
        ok "nothing at $VENV"
    fi
    printf '\n%sUninstalled.%s The clone itself is untouched; delete %s to remove it too.\n' \
        "$B" "$Z" "$REPO"
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

# --- 2. virtual environment ------------------------------------------------
# Reuse a working one; rebuild anything broken. A venv whose python has gone
# missing is the usual leftover of an interrupted run.
step "Preparing the virtual environment"
if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "" 2>/dev/null; then
    ok "reusing $VENV"
else
    [ -e "$VENV" ] && { warn "existing $VENV is not usable, rebuilding it"; rm -rf "$VENV"; }
    if python3 -m venv "$VENV" >/dev/null 2>&1; then
        ok "created $VENV with python3 -m venv"
    elif command -v virtualenv >/dev/null 2>&1 && virtualenv -q "$VENV" >/dev/null 2>&1; then
        ok "created $VENV with virtualenv"
    else
        # Debian and Ubuntu ship ensurepip separately, so `python3 -m venv`
        # fails out of the box. Say exactly how to fix it rather than leaving
        # the user with pip's message about an externally managed environment.
        rm -rf "$VENV"
        die "could not create a virtual environment.

    Debian and Ubuntu ship the venv module's bootstrap separately. Install it:

        sudo apt install python3-venv        # or python${PY_VER}-venv

    or install virtualenv, which needs no root:

        python3 -m pip install --user virtualenv

    then run this script again."
    fi
fi

# --- 3. install ------------------------------------------------------------
step "Installing lmi into the virtual environment"
PIP_ARGS=(install --quiet --upgrade)
[ "$EDITABLE" -eq 1 ] && PIP_ARGS+=(--editable)
"$VENV/bin/python" -m pip "${PIP_ARGS[@]}" "$REPO" \
    || die "pip failed. Re-run without --quiet to see why:
    $VENV/bin/python -m pip install $REPO"
[ -x "$LAUNCHER" ] || die \
    "pip reported success but $LAUNCHER is missing. Check that pyproject.toml
    still declares the lmi console script."
ok "installed$([ "$EDITABLE" -eq 1 ] && printf ' (editable)')"

# --- 4. link onto PATH -----------------------------------------------------
step "Putting lmi on your PATH"
mkdir -p "$LINK_DIR"
if [ -e "$LINK" ] && [ ! -L "$LINK" ]; then
    die "$LINK exists and is not a symlink. Move it aside and re-run,
    or choose another directory with --link-dir."
fi
ln -sfn "$LAUNCHER" "$LINK"
ok "linked $LINK -> $LAUNCHER"

# --- 5. verify -------------------------------------------------------------
step "Verifying"
VERSION="$("$LINK" --version 2>&1)" || die "$LINK did not run: $VERSION"
ok "$VERSION"

ON_PATH=0
case ":${PATH}:" in *":$LINK_DIR:"*) ON_PATH=1 ;; esac

printf '\n%sInstalled.%s\n' "$B" "$Z"
if [ "$ON_PATH" -eq 1 ]; then
    RESOLVED="$(command -v lmi 2>/dev/null || true)"
    if [ "$RESOLVED" = "$LINK" ]; then
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
printf '\n  Uninstall with: %s./scripts/install-linux.sh --uninstall%s\n' "$B" "$Z"
