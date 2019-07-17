# Functions used in building zinc native-images.
# TODO: This will be made automatic in pants via https://github.com/pantsbuild/pants/pull/6893.

export NATIVE_IMAGE_BUILD_CACHE_DIR="${HOME}/.cache/pants/native-image-build-script-cache"

function is_osx {
  [[ "$(uname)" == 'Darwin' ]]
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

function normalize_path {
  realpath "$@" \
    || readlink -f "$@"
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

  normalize_path "$outdir"
}

function extract_tgz {
  local outdir="$1"
  local url="$2"

  if [[ ! -d "$outdir" ]]; then
    curl -L "$url" \
      | tar zxvf -
  fi >&2

  normalize_path "$outdir"
}

function merge_jars {
  tr '\n' ':' | sed -Ee 's#:$##g'
}
