REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../../.. && pwd -P)"

# Defines:
# + CACHE_ROOT: The pants cache directory, ie: ~/.cache/pants.
# Exposes:
# + die: Exit in a failure state and optionally log an error message to the console.
# + fingerprint_data: Fingerprints the data on stdin.
source ${REPO_ROOT}/build-support/common.sh

KERNEL=$(uname -s | tr '[:upper:]' '[:lower:]')
case "${KERNEL}" in
  linux)
    readonly LIB_EXTENSION=so
    ;;
  darwin)
    readonly LIB_EXTENSION=dylib
    ;;
  *)
    die "Unknown kernel ${KERNEL}, cannot bootstrap pants native code!"
    ;;
esac

readonly NATIVE_ROOT="${REPO_ROOT}/src/rust/engine"
readonly NATIVE_ENGINE_BINARY="native_engine.so"
readonly NATIVE_ENGINE_RESOURCE="${REPO_ROOT}/src/python/pants/engine/${NATIVE_ENGINE_BINARY}"

# N.B. Set $MODE to "debug" for faster builds.
readonly MODE="${MODE:-release}"
case "$MODE" in
  debug) MODE_FLAG="" ;;
  *) MODE_FLAG="--release" ;;
esac

readonly NATIVE_ENGINE_CACHE_DIR=${CACHE_ROOT}/bin/native-engine

function calculate_current_hash() {
  # Cached and unstaged files, with ignored files excluded.
  # NB: We fork a subshell because one or both of `ls-files`/`hash-object` are
  # sensitive to the CWD, and the `--work-tree` option doesn't seem to resolve that.
  (
   cd ${REPO_ROOT}
   (echo "${MODE_FLAG}"
    echo "${RUST_TOOLCHAIN}"
    uname
    git ls-files -c -o --exclude-standard \
     "${NATIVE_ROOT}" \
     "${REPO_ROOT}/rust-toolchain" \
     "${REPO_ROOT}/src/python/pants/engine/native.py" \
     "${REPO_ROOT}/build-support/bin/native" \
     "${REPO_ROOT}/3rdparty/python/requirements.txt" \
   | grep -v -E -e "/BUILD$" -e "/[^/]*\.md$" \
   | git hash-object -t blob --stdin-paths) | fingerprint_data
  )
}

function _build_native_code() {
  # Builds the native code, and echos the path of the built binary.

  (
    cd "${REPO_ROOT}"
    ./pants-bootstrap.pex \
      --pants-config-files="['pants.bootstrap.ini']" \
      bootstrap-native-engine \
      src/rust/engine:new-cargo
    # "${REPO_ROOT}/build-support/bin/native/cargo" build ${MODE_FLAG} \
    #   --manifest-path "${NATIVE_ROOT}/Cargo.toml" -p engine
  ) || die
  echo "${NATIVE_ROOT}/target/${MODE}/libengine.${LIB_EXTENSION}"
}

function bootstrap_native_code() {
  # Bootstraps the native code only if needed.
  local native_engine_version="$(calculate_current_hash)"
  local engine_version_hdr="engine_version: ${native_engine_version}"
  local target_binary="${NATIVE_ENGINE_CACHE_DIR}/${native_engine_version}/${NATIVE_ENGINE_BINARY}"
  local target_binary_metadata="${target_binary}.metadata"
  if [[ ! -f "${target_binary}" || ! -f "${target_binary_metadata}" ]]
  then
    local -r native_binary="$(_build_native_code)"

    # If bootstrapping the native engine fails, don't attempt to run pants
    # afterwards.
    if ! [ -f "${native_binary}" ]
    then
      die "Failed to build native engine."
    fi

    # Pick up Cargo.lock changes if any caused by the `cargo build`.
    native_engine_version="$(calculate_current_hash)"
    engine_version_hdr="engine_version: ${native_engine_version}"
    target_binary="${NATIVE_ENGINE_CACHE_DIR}/${native_engine_version}/${NATIVE_ENGINE_BINARY}"
    target_binary_metadata="${target_binary}.metadata"

    mkdir -p "$(dirname ${target_binary})"
    cp "${native_binary}" "${target_binary}"

    local -r metadata_file=$(mktemp -t pants.native_engine.metadata.XXXXXX)
    echo "${engine_version_hdr}" > "${metadata_file}"
    echo "repo_version: $(git describe --dirty)" >> "${metadata_file}"
    mv "${metadata_file}" "${target_binary_metadata}"
  fi

  # Establishes the native engine wheel resource only if needed.
  # NB: The header manipulation code here must be coordinated with header stripping code in
  #     the Native.binary method in src/python/pants/engine/native.py.
  if [[
    ! -f "${NATIVE_ENGINE_RESOURCE}" ||
    "$(head -1 "${NATIVE_ENGINE_RESOURCE}" | tr '\0' '\n' 2>/dev/null)" != "${engine_version_hdr}"
  ]]
  then
    cat "${target_binary_metadata}" "${target_binary}" > "${NATIVE_ENGINE_RESOURCE}"
  fi
}
