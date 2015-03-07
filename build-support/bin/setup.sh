#!/usr/bin/env bash

REPO_ROOT="$(git rev-parse --show-toplevel)"

source "${REPO_ROOT}/build-support/common.sh"

PRE_COMMIT_DEST="${GIT_DIR:-${REPO_ROOT}/.git}/hooks/pre-commit"
PRE_COMMIT_SRC="${REPO_ROOT}/build-support/bin/pre-commit.sh"

function install_pre_commit_hook() {
  rm -f "${PRE_COMMIT_DEST}" && \
  ln "${PRE_COMMIT_SRC}" "${PRE_COMMIT_DEST}" && \
  echo "Pre-commit checks installed from ${PRE_COMMIT_SRC} to ${PRE_COMMIT_DEST}";
  cd - &> /dev/null
}

if [[ ! -e "${PRE_COMMIT_DEST}" ]]
then
  install_pre_commit_hook
else
  existing_hook_sig="$(cat "${PRE_COMMIT_DEST}" | fingerprint_data)"
  canonical_hook_sig="$(cat "${PRE_COMMIT_SRC}" | fingerprint_data)"
  if [[ "${existing_hook_sig}" != "${canonical_hook_sig}" ]]
  then
    read -p "A pre-commit script already exists, replace with ${PRE_COMMIT_SRC}? [Yn]" ok
    if [[ "${ok:-Y}" =~ ^[yY]([eE][sS])?$ ]]
    then
      install_pre_commit_hook
    else
      echo "Pre-commit checks not installed"
      exit 1
    fi
  else
    echo "Pre-commit checks up to date."
  fi
fi
exit 0