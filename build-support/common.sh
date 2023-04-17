# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# shellcheck shell=bash

COLOR_BLUE="\x1b[34m"
COLOR_RED="\x1b[31m"
COLOR_GREEN="\x1b[32m"
COLOR_RESET="\x1b[0m"

function log() {
  echo -e "$@" 1>&2
}

function die() {
  (($# > 0)) && log "\n${COLOR_RED}$*${COLOR_RESET}"
  exit 1
}

function green() {
  (($# > 0)) && log "\n${COLOR_GREEN}$*${COLOR_RESET}"
}

# Initialization for elapsed()
: "${elapsed_start_time:=$(date +'%s')}"
export elapsed_start_time

function elapsed() {
  now=$(date '+%s')
  elapsed_secs=$((now - elapsed_start_time))
  echo $elapsed_secs | awk '{printf "%02d:%02d\n",int($1/60), int($1%60)}'
}

function banner() {
  echo -e "${COLOR_BLUE}[=== $(elapsed) $* ===]${COLOR_RESET}"
}

function fingerprint_data() {
  git hash-object --stdin
}

function git_merge_base() {
  # This prints the tracking branch if set and otherwise falls back to the commit before HEAD.
  # We fall back to the commit before HEAD to attempt to account for situations without a tracking
  # branch, which might include `main` builds, but can also include branch-PR builds, where
  # Travis checks out a specially crafted Github `+refs/pull/11516/merge` branch.
  git rev-parse --symbolic-full-name --abbrev-ref HEAD@\{upstream\} 2> /dev/null || git rev-parse HEAD^
}

function determine_python() {
  if [[ -n "${PY:-}" ]]; then
    which "${PY}" && return 0
  fi

  local candidate_versions
  if is_macos_arm; then
    candidate_versions=('3.9')
  else
    candidate_versions=('3.7' '3.8' '3.9')
  fi

  for version in "${candidate_versions[@]}"; do
    local interpreter_path
    interpreter_path="$(command -v "python${version}")"
    if [[ -z "${interpreter_path}" ]]; then
      continue
    fi
    # Check if the Python version is installed via Pyenv but not activated.
    if [[ "$("${interpreter_path}" --version 2>&1 > /dev/null)" == "pyenv: python${version}"* ]]; then
      continue
    fi
    # Sometimes the 'python3.Y' binary is a symlink to a suffixed version: 'python3.Ym'.
    # We use 'realpath' to get the most precise version (the suffixed version or the real file),
    # or pex can fail to find the interpreter in the venv and then fail to reexecute.
    # See: https://github.com/pantsbuild/pex/issues/2119
    interpreter_path="$(realpath "${interpreter_path}")"
    echo "${interpreter_path}" && return 0
  done
  echo "pants: failed to find suitable Python interpreter, looking for: ${candidate_versions[*]}" >&2
  return 1
}

function is_macos_arm() {
  [[ $(uname -sm) == "Darwin arm64" ]]
}

function is_macos_big_sur() {
  [[ $(uname) == "Darwin" && $(sw_vers -productVersion) = 11\.* ]]
}
