#!/usr/bin/env bash

set -euo pipefail

# Set up the development environment.
# Currently this just installs local git hooks.

REPO_ROOT="$(git rev-parse --show-toplevel)"

HOOK_DIR="${GIT_DIR:-${REPO_ROOT}/.git}/hooks"
HOOK_SRC_DIR="${REPO_ROOT}/build-support/githooks"
HOOK_NAMES="$(ls "${HOOK_SRC_DIR}")"

# shellcheck source=build-support/common.sh
source "${REPO_ROOT}/build-support/common.sh"
PY="$(determine_python)"

RELPATH_PREFIX="$(
  cat << EOF | ${PY}
import os

print(os.path.relpath("${HOOK_SRC_DIR}", "${HOOK_DIR}"))
EOF
)"

function install_hook() {
  HOOK=$1
  RELPATH="${RELPATH_PREFIX}/${HOOK}"
  (
    cd "${HOOK_DIR}" &&
      rm -f "${HOOK}" &&
      ln -s "${RELPATH}" "${HOOK}" &&
      echo "${HOOK} hook linked to $(pwd)/${HOOK}"
  )
}

function ensure_hook() {
  HOOK=$1
  HOOK_SRC="${REPO_ROOT}/build-support/githooks/${HOOK}"
  HOOK_DST="${HOOK_DIR}/${HOOK}"

  if [[ ! -e "${HOOK_DST}" ]]; then
    install_hook "${HOOK}"
  else
    if cmp --quiet "${HOOK_SRC}" "${HOOK_DST}"; then
      echo "${HOOK} hook up to date."
    else
      read -rp "A ${HOOK} hook already exists, replace with ${HOOK_SRC}? [Yn]" ok
      if [[ "${ok:-Y}" =~ ^[yY]([eE][sS])?$ ]]; then
        install_hook "${HOOK}"
      else
        echo "${HOOK} hook not installed"
        exit 1
      fi
    fi
  fi
}

# Make sure users of recent git don't have their history polluted
# by formatting changes.
git config --local blame.ignoreRevsFile .git-blame-ignore-revs

for HOOK in ${HOOK_NAMES}; do
  ensure_hook "${HOOK}"
done
