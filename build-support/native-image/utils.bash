# Functions used in building zinc native-images.
# TODO: This will be made automatic in pants via https://github.com/pantsbuild/pants/pull/6893.

export NATIVE_IMAGE_BUILD_CACHE_DIR="${NATIVE_IMAGE_BUILD_CACHE_DIR:-${HOME}/.cache/pants/native-image-build-script-cache}"

function is_osx {
  [[ "$(uname)" == 'Darwin' ]]
}

function die {
  echo >&2 "$@"
  exit 1
}

function ensure_has_executable {
  local cmd="$1"
  if ! hash "$cmd"; then
    die "${cmd} was not found." "${@:2}"
  fi
}

function with_pushd {
  pushd "$1" >&2
  "${@:2}"; rc="$?"
  popd >&2
  return "$rc"
}

function do_within_cache_dir {
  with_pushd "$NATIVE_IMAGE_BUILD_CACHE_DIR" "$@"
}

function pushd_into_command_line {
  while read -r into_dir; do
    with_pushd "$into_dir" "$@" || return "$?"
  done
}

function command_line_with_side_effect {
  while read -r arg; do
    >&2 "$1" "$arg" "${@:2}" || return "$?"
    echo "$arg"
  done
}

function pushd_into_command_line_with_side_effect {
  command_line_with_side_effect with_pushd "$@"
}

function normalize_path_no_validation {
  if hash realpath 2>/dev/null; then
    realpath "$@"
  else
    readlink -f "$@"
  fi
}

function normalize_path_check_file {
  local path="$1"
  local result="$(normalize_path_no_validation "$path")"
  if [[ -f "$result" ]]; then
    echo "$result"
  else
    die "file was expected: $path" "${@:2}"
  fi
}

function normalize_path_check_dir {
  local path="$1"
  local result="$(normalize_path_no_validation "$path")"
  if [[ -d "$result" ]]; then
    echo "$result"
  else
    die "directory was expected: $path" "${@:2}"
  fi
}

function clone_repo_somewhat_idempotently {
  local outdir="$1"
  local url="$2"
  local branch="${3:-}"

  if [[ ! -d "$outdir" ]]; then
    git clone "$url" "$outdir" || return "$?"
    if [[ -n "$branch" ]]; then
      pushd "$outdir"
      git checkout "$branch" || return "$?"
      popd
    fi
  fi >&2

  normalize_path_check_dir "$outdir"
}

function extract_tgz {
  local outdir="$1"
  local url="$2"

  if [[ ! -d "$outdir" ]]; then
    curl -L "$url" \
      | tar zxvf -
  fi >&2

  normalize_path_check_dir "$outdir"
}

function merge_jars {
  tr '\n' ':' | sed -Ee 's#:$##g'
}
