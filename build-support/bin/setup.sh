#!/usr/bin/env bash

# Set up the development environment.
# Currently this just installs local git hooks.

REPO_ROOT="$(git rev-parse --show-toplevel)"

HOOK_DIR="${GIT_DIR:-${REPO_ROOT}/.git}/hooks"
PRE_COMMIT_DEST="${HOOK_DIR}/pre-commit"
PRE_COMMIT_SRC="${REPO_ROOT}/build-support/bin/pre-commit.sh"
PRE_COMMIT_RELSRC="$(cat << EOF | python2.7
import os

print(os.path.relpath("${PRE_COMMIT_SRC}", "${HOOK_DIR}"))
EOF
)"

function install_pre_commit_hook() {
  (
    cd "${HOOK_DIR}" && \
    rm -f pre-commit && \
    ln -s "${PRE_COMMIT_RELSRC}" pre-commit && \
    echo "Pre-commit checks linked from ${PRE_COMMIT_SRC} to $(pwd)/pre-commit";
  )
}

if [[ ! -e "${PRE_COMMIT_DEST}" ]]
then
  install_pre_commit_hook
else
  if cmp --quiet "${PRE_COMMIT_SRC}" "${PRE_COMMIT_DEST}"
  then
    echo "Pre-commit checks up to date."
  else
    read -p "A pre-commit script already exists, replace with ${PRE_COMMIT_SRC}? [Yn]" ok
    if [[ "${ok:-Y}" =~ ^[yY]([eE][sS])?$ ]]
    then
      install_pre_commit_hook
    else
      echo "Pre-commit checks not installed"
      exit 1
    fi
  fi
fi
exit 0

