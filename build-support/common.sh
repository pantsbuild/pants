# NB: shellcheck complains this is unused, but it's used by callers. See https://github.com/koalaman/shellcheck/wiki/SC2034.
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
  git hash-object --stdin
}

function git_merge_base() {
  # This prints the tracking branch if set and otherwise falls back to local "master".
  git rev-parse --symbolic-full-name --abbrev-ref HEAD@\{upstream\} 2>/dev/null || echo 'master'
}

function safe_curl() {
  real_curl="$(command -v curl)"
  set +e
  "${real_curl}" --fail -SL "$@"
  exit_code=$?
  set -e
  if [[ "${exit_code}" -ne 0 ]]; then
    echo >&2 "Curl failed with args: $*"
    exit 1
  fi
}

function root_dir() {
  cd "$(dirname "${BASH_SOURCE[0]}")" && cd "$(git rev-parse --show-toplevel)" && pwd
}

function requirement() {
  package="$1"
  grep "^${package}[^A-Za-z0-9]" "$(root_dir)/3rdparty/python/requirements.txt" || \
    die "Could not find requirement for ${package}"
}

# URL from which pex release binaries can be downloaded.
: "${PEX_DOWNLOAD_PREFIX:="https://github.com/pantsbuild/pex/releases/download"}"

function run_pex() {
  (
    PEX_VERSION="$(requirement pex | sed -e "s|pex==||")"
    PEX_DIR="$(root_dir)/build-support/pex/${PEX_VERSION}"
    if ! [ -x "${PEX_DIR}/pex" ]; then
      pex_url="${PEX_DOWNLOAD_PREFIX}/v${PEX_VERSION}/pex"
      log "Downloading pex==${PEX_VERSION} from ${pex_url}..."

      pexdir="$(mktemp -d -t download_pex.XXXXX)"
      trap 'rm -rf "${pexdir}"' EXIT

      safe_curl -s "${pex_url}" > "${pexdir}/pex" && \
      chmod +x "${pexdir}/pex" && \
      rm -rf "${PEX_DIR}" && \
      mkdir -p "$(dirname "${PEX_DIR}")" && \
      mv "${pexdir}" "${PEX_DIR}"
    fi

    "${PEX_DIR}/pex" "$@"
  )
}


: "${VIRTUALENV_VERSION:="20.0.26"}"

function run_virtualenv() {
  (
    VIRTUALENV_DIR="$(root_dir)/build-support/virtualenv/${VIRTUALENV_VERSION}"
    if ! [ -x "${VIRTUALENV_DIR}/virtualenv.pex" ]; then
      log "Building PEX for virtualenv==${VIRTUALENV_VERSION}..."
      pexdir="$(mktemp -d -t virtualenv_pex.XXXXX)"
      trap 'rm -rf "${pexdir}"' EXIT

      run_pex \
        --python="${PY}" \
        "virtualenv==${VIRTUALENV_VERSION}" \
        -c virtualenv \
        -o "${pexdir}/virtualenv.pex" && \
      rm -rf "${VIRTUALENV_DIR}" && \
      mkdir -p "$(dirname "${VIRTUALENV_DIR}")" && \
      mv "${pexdir}" "${VIRTUALENV_DIR}"
    fi

    "${VIRTUALENV_DIR}/virtualenv.pex" --python "${PY}" "$@"
  )
}
