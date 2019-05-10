# shellcheck disable=SC2034
CACHE_ROOT=${XDG_CACHE_HOME:-$HOME/.cache}/pants

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
  elapsed_secs=$(( now - elapsed_start_time ))
  echo $elapsed_secs | awk '{printf "%02d:%02d\n",int($1/60), int($1%60)}'
}

function banner() {
  echo -e "${COLOR_BLUE}[=== $(elapsed) $* ===]${COLOR_RESET}"
}

function travis_fold() {
  local action=$1
  local slug=$2
  # Use the line clear terminal escape code to prevent the travis_fold lines from
  # showing up if e.g. a user is running the calling script.
  echo -en "travis_fold:${action}:${slug}\r${CLEAR_LINE}"
}

function start_travis_section() {
  local slug="$1"
  travis_fold start "${slug}"
  /bin/echo -n "${slug}" > "${TRAVIS_FOLD_STATE}"
  shift
  local section="$*"
  banner "${section}"
}

function end_travis_section() {
  travis_fold end "$(cat ${TRAVIS_FOLD_STATE})"
  rm -f "${TRAVIS_FOLD_STATE}"
}

function fingerprint_data() {
  git hash-object -t blob --stdin
}

function git_merge_base() {
  # This prints the tracking branch if set and otherwise falls back to local "master".
  git rev-parse --symbolic-full-name --abbrev-ref HEAD@\{upstream\} 2>/dev/null || echo 'master'

}
