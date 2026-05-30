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

# Resolve the "latest" release tag via the GitHub API. Parse with python3
# (already a hard prerequisite) rather than grep/sed, which can silently pick
# the wrong field if the JSON is compacted or reordered.
resolve_latest() {
  local tag
  tag="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])' 2>/dev/null)"
  [ -n "${tag}" ] || err "could not resolve the latest release tag from GitHub."
  printf '%s' "${tag}"
}

# Verify a downloaded asset against the release's sha256sums.txt.
verify_checksum() {
  local dir="$1" file="$2"
  local sums="${dir}/sha256sums.txt"
  [ -f "${sums}" ] || err "checksum file missing; cannot verify ${file}."

  local expected
  expected="$(awk -v f="${file}" '$2 == f {print $1}' "${sums}" | head -n1)"
  [ -n "${expected}" ] || err "no checksum entry for ${file} in sha256sums.txt."

  local actual
  if command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "${dir}/${file}" | awk '{print $1}')"
  elif command -v shasum >/dev/null 2>&1; then
    actual="$(shasum -a 256 "${dir}/${file}" | awk '{print $1}')"
  else
    err "neither sha256sum nor shasum found; cannot verify download integrity."
  fi

  [ "${expected}" = "${actual}" ] \
    || err "checksum mismatch for ${file} (expected ${expected}, got ${actual})."
  echo "Checksum verified: ${file}"
}

do_uninstall() {
  [ -f "${INSTALL_DIR}/install.py" ] || err "no autodidact install found at ${INSTALL_DIR}."
  exec python3 "${INSTALL_DIR}/install.py" --uninstall
}

do_install() {
  require curl "Install it from your package manager."
  require tar "Install it from your package manager."
  require python3 "Install it from https://www.python.org/downloads/"
  require uv "Install it from https://docs.astral.sh/uv/getting-started/installation/"

  local tag="${VERSION}"
  if [ "${tag}" = "latest" ]; then
    tag="$(resolve_latest)"
  fi

  local asset="autodidact-${tag}.tar.gz"
  local base="https://github.com/${REPO}/releases/download/${tag}"

  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "${tmp}"' EXIT

  echo "Downloading ${asset} ..."
  curl -fsSL "${base}/${asset}" -o "${tmp}/${asset}" \
    || err "download failed: ${base}/${asset}"
  curl -fsSL "${base}/sha256sums.txt" -o "${tmp}/sha256sums.txt" \
    || err "checksum download failed: ${base}/sha256sums.txt"

  verify_checksum "${tmp}" "${asset}"

  # Reject absolute paths or parent-dir traversal before extracting, so a
  # tampered tarball cannot write outside INSTALL_DIR (portable across GNU/BSD
  # tar, which lack a common --no-absolute-names flag).
  if tar tzf "${tmp}/${asset}" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
    err "refusing to extract: tarball contains absolute or parent-traversal paths."
  fi

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

  # exec replaces this process, so the EXIT trap will not fire — clean up now.
  rm -rf "${tmp}"
  trap - EXIT

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
