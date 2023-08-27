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

  version='3.9'
  interpreter_path="$(command -v "python${version}")"
  if [[ -z "${interpreter_path}" ]]; then
    echo "pants: Failed to find a Python ${version} interpreter" 1>&2 && return 1
  fi
  # Check if the Python version is installed via Pyenv but not activated.
  if [[ "$("${interpreter_path}" --version 2>&1 > /dev/null)" == "pyenv: python${version}"* ]]; then
    echo "pants: The Python ${version} interpreter at ${interpreter_path} is an inactive pyenv interpreter" 1>&2 && return 1
  fi
  echo "${interpreter_path}"
  return 0
}

function is_macos_arm() {
  [[ $(uname -sm) == "Darwin arm64" ]]
}

function is_macos_big_sur() {
  [[ $(uname) == "Darwin" && $(sw_vers -productVersion) = 11\.* ]]
}
