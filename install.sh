#!/usr/bin/env bash
#
# Bootstrap installer for autodidact (release mode).
#
# Downloads a release tarball from GitHub, extracts it to ~/.claude/autodidact/,
# and delegates to the bundled install.py --release to register hooks, create
# skill/agent/command symlinks, and initialize the learning database.
#
# Usage:
#   bash install.sh                  # install the latest release
#   bash install.sh v0.1.0           # install a specific tag (positional)
#   bash install.sh --version v0.1.0 # install a specific tag
#   bash install.sh --update         # re-fetch latest and reinstall (preserves state)
#   bash install.sh --uninstall      # remove symlinks/hooks (preserves learning.db)
#   bash install.sh --help           # show this help
#
# One-liner:
#   curl -fsSL https://github.com/Jason-Adam/autodidact/releases/latest/download/install.sh | bash

set -euo pipefail

REPO="Jason-Adam/autodidact"
CLAUDE_DIR="${HOME}/.claude"
INSTALL_DIR="${CLAUDE_DIR}/autodidact"

# Code directories shipped in the tarball. On --update these are removed before
# re-extracting so files deleted in a newer release do not linger as stale code.
# User state (learning.db, interviews/, routing-overrides.json, .venv, .installed)
# is never in this list, so it is preserved across updates.
CODE_DIRS=(src hooks skills agents commands templates)

VERSION="latest"
ACTION="install"

usage() {
  cat <<'EOF'
autodidact installer

Usage:
  install.sh                    Install the latest release
  install.sh <tag>              Install a specific tag (e.g. v0.1.0)
  install.sh --version <tag>    Install a specific tag
  install.sh --update           Re-fetch the latest release and reinstall
  install.sh --uninstall        Remove symlinks/hooks (preserves learning.db)
  install.sh --help             Show this help

Prerequisites: uv, curl, tar (git not required).
EOF
}

err() {
  echo "Error: $*" >&2
  exit 1
}

require() {
  command -v "$1" >/dev/null 2>&1 || err "$1 is required but was not found. $2"
}

# Resolve the "latest" release tag via the GitHub API.
resolve_latest() {
  local tag
  tag="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
    | grep '"tag_name":' \
    | head -n1 \
    | sed -E 's/.*"tag_name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')"
  [ -n "${tag}" ] || err "could not resolve the latest release tag from GitHub."
  printf '%s' "${tag}"
}

do_uninstall() {
  [ -f "${INSTALL_DIR}/install.py" ] || err "no autodidact install found at ${INSTALL_DIR}."
  exec python3 "${INSTALL_DIR}/install.py" --uninstall
}

do_install() {
  require curl "Install it from your package manager."
  require tar "Install it from your package manager."
  require uv "Install it from https://docs.astral.sh/uv/getting-started/installation/"

  local tag="${VERSION}"
  if [ "${tag}" = "latest" ]; then
    tag="$(resolve_latest)"
  fi

  local asset="autodidact-${tag}.tar.gz"
  local url="https://github.com/${REPO}/releases/download/${tag}/${asset}"

  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "${tmp}"' EXIT

  echo "Downloading ${asset} ..."
  curl -fsSL "${url}" -o "${tmp}/${asset}" \
    || err "download failed: ${url}"

  # On update, clear stale code dirs (user state is untouched).
  if [ "${ACTION}" = "update" ]; then
    echo "Clearing stale code directories for update ..."
    local d
    for d in "${CODE_DIRS[@]}"; do
      rm -rf "${INSTALL_DIR:?}/${d}"
    done
  fi

  echo "Extracting to ${INSTALL_DIR} ..."
  mkdir -p "${INSTALL_DIR}"
  tar xzf "${tmp}/${asset}" -C "${INSTALL_DIR}" --strip-components=1

  echo "Running install.py --release ..."
  exec uv run --project "${INSTALL_DIR}" python3 "${INSTALL_DIR}/install.py" --release
}

while [ $# -gt 0 ]; do
  case "$1" in
    --version)
      [ $# -ge 2 ] || err "--version requires a tag argument (e.g. --version v0.1.0)."
      VERSION="$2"
      shift 2
      ;;
    --version=*)
      VERSION="${1#*=}"
      shift
      ;;
    --update)
      ACTION="update"
      shift
      ;;
    --uninstall)
      ACTION="uninstall"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      err "unknown option: $1 (try --help)"
      ;;
    *)
      VERSION="$1"
      shift
      ;;
  esac
done

case "${ACTION}" in
  uninstall) do_uninstall ;;
  *) do_install ;;
esac
