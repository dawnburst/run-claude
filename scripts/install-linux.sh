#!/usr/bin/env bash
# Install the `lmi` CLI on Linux (including WSL) so that typing `lmi` works.
#
# Run it from inside a clone of this repository:
#
#     ./scripts/install-linux.sh
#
# By default it builds a single self-contained executable with the standard
# library's zipapp module and copies it onto your PATH. That needs **no pip, no
# setuptools, no wheel, no virtual environment and no network**, which is why it
# is the default: `pip install .` fetches setuptools>=61 for build isolation, so
# it fails outright on an air-gapped machine, and `python3 -m venv` fails on
# Debian and Ubuntu because they ship ensurepip separately.
#
# The installed file is the whole program, about 43 KB. Once it is in place the
# clone is disposable - unlike a virtual-environment install, whose launcher
# points back at the clone forever.
#
# Pass --venv if you want the traditional pip install instead; that is the right
# choice when you intend to edit the source, since --editable needs it.
#
# `set -e` is right here, unlike in the runner itself: a half-finished install
# is worse than a stopped one.
set -euo pipefail

LINK_DIR="$HOME/.local/bin"
MODE="zipapp"
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
  --zipapp         build a single self-contained executable (default).
                   Needs only the standard library - no pip, no network.
  --venv           install into a virtual environment with pip instead.
                   Needs pip, and network unless setuptools and wheel are
                   already present locally.
  --editable       install in editable mode so `lmi` tracks this checkout.
                   Implies --venv.
  --link-dir DIR   where to put the `lmi` command (default: ~/.local/bin)
  --uninstall      remove the installed command, and .venv if there is one
  -h, --help       show this help

Run it from inside a clone of the repository. It needs no sudo.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --zipapp) MODE="zipapp"; shift ;;
        --venv) MODE="venv"; shift ;;
        --editable) EDITABLE=1; MODE="venv"; shift ;;
        --link-dir) [ $# -ge 2 ] || die "--link-dir needs a directory"
                    LINK_DIR="$2"; shift 2 ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
done

# --- locate the clone we live in -------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VENV="$REPO/.venv"
TARGET="$LINK_DIR/lmi"

[ -f "$REPO/pyproject.toml" ] || die \
    "$REPO does not look like the repository (no pyproject.toml).
    Run this script from inside a clone, as ./scripts/install-linux.sh"
[ -d "$REPO/lmi" ] || die "$REPO has no lmi/ package directory."

# Is the thing at $TARGET something we installed? Only ever remove our own.
# Either a symlink into this clone's venv, or a zipapp holding lmi/cli.py.
ours() {
    [ -e "$1" ] || return 1
    if [ -L "$1" ]; then
        case "$(readlink -f "$1" 2>/dev/null || true)" in "$REPO"/*) return 0 ;; esac
        return 1
    fi
    python3 - "$1" <<'EOF' 2>/dev/null
import sys, zipfile
try:
    with zipfile.ZipFile(sys.argv[1]) as z:
        sys.exit(0 if "lmi/cli.py" in z.namelist() else 1)
except Exception:
    sys.exit(1)
EOF
}

# --- uninstall -------------------------------------------------------------
if [ "$UNINSTALL" -eq 1 ]; then
    step "Removing the lmi command"
    if [ ! -e "$TARGET" ]; then
        ok "nothing at $TARGET"
    elif ours "$TARGET"; then
        rm -f "$TARGET"; ok "removed $TARGET"
    else
        die "$TARGET was not installed by this script - leaving it alone.
    Remove it yourself if you are sure, or use --link-dir."
    fi
    step "Removing the virtual environment, if there is one"
    if [ -d "$VENV" ]; then rm -rf "$VENV"; ok "removed $VENV"; else ok "none"; fi
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

# --- 2. build or install ---------------------------------------------------
if [ "$MODE" = "zipapp" ]; then
    step "Building a self-contained executable"
    WORK="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '$WORK'" EXIT
    # The staged source and the built file must not share a directory: the
    # package is itself named lmi/, so writing the output as $WORK/lmi would
    # collide with the directory being packed.
    STAGE="$WORK/stage"
    BUILT="$WORK/lmi"
    mkdir -p "$STAGE"
    cp -r "$REPO/lmi" "$STAGE/"
    find "$STAGE" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    # /usr/bin/env python3 rather than a fixed path, so the file keeps working
    # if python3 moves. On Windows this line is ignored, which is why the
    # Windows installers add a .cmd shim instead.
    python3 -m zipapp "$STAGE" -m "lmi.cli:main" -p "/usr/bin/env python3" \
        -o "$BUILT" || die "zipapp failed to build the executable."
    chmod +x "$BUILT"
    BUILT_VER="$("$BUILT" --version 2>&1)" \
        || die "the built executable does not run: $BUILT_VER"
    ok "built $(du -h "$BUILT" | cut -f1) - $BUILT_VER"

    step "Installing it onto your PATH"
    mkdir -p "$LINK_DIR"
    if [ -e "$TARGET" ] && ! ours "$TARGET"; then
        die "$TARGET already exists and was not installed by this script.
    Move it aside and re-run, or choose another directory with --link-dir."
    fi
    # Write beside the target then move, so an interrupted copy cannot leave a
    # half-written executable in place of a working one.
    cp "$BUILT" "$TARGET.new" && chmod +x "$TARGET.new" && mv -f "$TARGET.new" "$TARGET"
    ok "installed $TARGET"
    ok "the clone is no longer needed - this file is the whole program"
else
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
            rm -rf "$VENV"
            die "could not create a virtual environment.

    Debian and Ubuntu ship the venv module's bootstrap separately. Install it:

        sudo apt install python3-venv        # or python${PY_VER}-venv

    or install virtualenv, which needs no root:

        python3 -m pip install --user virtualenv

    Or drop --venv and use the default zipapp mode, which needs none of this."
        fi
    fi

    step "Installing lmi into it"
    PIP_ARGS=(install --quiet --upgrade)
    [ "$EDITABLE" -eq 1 ] && PIP_ARGS+=(--editable)
    "$VENV/bin/python" -m pip "${PIP_ARGS[@]}" "$REPO" || die \
        "pip failed. If this machine has no network, that is expected: pip
    fetches setuptools to build the package. Use the default zipapp mode
    instead, which needs nothing:

        ./scripts/install-linux.sh"
    [ -x "$VENV/bin/lmi" ] || die \
        "pip reported success but $VENV/bin/lmi is missing."
    ok "installed$([ "$EDITABLE" -eq 1 ] && printf ' (editable)')"

    step "Linking it onto your PATH"
    mkdir -p "$LINK_DIR"
    if [ -e "$TARGET" ] && ! ours "$TARGET"; then
        die "$TARGET already exists and was not installed by this script.
    Move it aside and re-run, or choose another directory with --link-dir."
    fi
    ln -sfn "$VENV/bin/lmi" "$TARGET"
    ok "linked $TARGET -> $VENV/bin/lmi"
    warn "this mode needs the clone to stay where it is"
fi

# --- 3. verify -------------------------------------------------------------
step "Verifying"
VERSION="$("$TARGET" --version 2>&1)" || die "$TARGET did not run: $VERSION"
ok "$VERSION"

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
printf '\n  Re-run this script to upgrade. Uninstall with %s--uninstall%s.\n' "$B" "$Z"
