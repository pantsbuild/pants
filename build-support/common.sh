#!/usr/bin/env bash

TRAVIS_FOLD_STATE="/tmp/.travis_fold_current"
CLEAR_LINE="\x1b[K"
COLOR_BLUE="\x1b[34m"
COLOR_RED="\x1b[31m"
COLOR_GREEN="\x1b[32m"
COLOR_RESET="\x1b[0m"


function log() {
  echo -e "$@" 1>&2
}

function die() {
  (($# > 0)) && log "\n${COLOR_RED}$@${COLOR_RESET}"
  exit 1
}

function green() {
  (($# > 0)) && log "\n${COLOR_GREEN}$@${COLOR_RESET}"
}

# Initialization for elapsed()
if [ -z "$elapsed_start_time" ] ; then
  export elapsed_start_time=$(date +'%s')
fi

function elapsed() {
  now=$(date '+%s')
  elapsed_secs=$(($now - $elapsed_start_time))
  echo $elapsed_secs | awk '{printf "%02d:%02d\n",int($1/60), int($1%60)}'
}

function banner() {
  echo -e "${COLOR_BLUE}[=== $(elapsed) $@ ===]${COLOR_RESET}"
}

function travis_fold() {
  local action=$1
  local slug=$2
  # Use the line clear terminal escape code to prevent the travis_fold lines from
  # showing up if e.g. a user is running the calling script.
  echo -en "travis_fold:${action}:${slug}\r${CLEAR_LINE}"
}

function start_travis_section() {
  local slug=$1
  travis_fold start "${slug}"
  /bin/echo -n "${slug}" > "${TRAVIS_FOLD_STATE}"
  shift
  local section="$@"
  banner "${section}"
}

function end_travis_section() {
  travis_fold end "$(cat ${TRAVIS_FOLD_STATE})"
  rm -f "${TRAVIS_FOLD_STATE}"
}

function fingerprint_data() {
  openssl sha1 | cut -d' ' -f2
}

function ensure_file_exists() {
  if [ ! -s "${1}" ]; then
    die "ERROR: ${1} does not exist!"
  fi
}

# Prevent bootstrapping failure due to unrecognized flag:
# https://github.com/pantsbuild/pants/issues/78
function set_archflags() {
  GCC_VERSION=`gcc -v 2>&1`
  if [ $? -ne 0 ]; then
    die "ERROR: unable to execute 'gcc'. Please verify that your compiler is installed, in your\n" \
        "      \$PATH and functional.\n\n" \
        "      Hint: on Mac OS X, you may need to accept the XCode EULA: 'sudo xcodebuild -license accept'."
  fi
  if [[ "$GCC_VERSION" == *503.0.38* ]]; then
    # Required for clang version 503.0.38
    export set ARCHFLAGS=-Wno-error=unused-command-line-argument-hard-error-in-future
  fi
}
set_archflags
