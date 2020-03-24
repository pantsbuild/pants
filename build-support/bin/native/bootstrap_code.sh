REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../../.. && pwd -P)"
# Defines:
# + CACHE_ROOT: The pants cache directory, ie: ~/.cache/pants.
# Exposes:
# + die: Exit in a failure state and optionally log an error message to the console.
# shellcheck source=build-support/common.sh
source "${REPO_ROOT}/build-support/common.sh"

# Defines:
# + NATIVE_ROOT: The Rust code directory, ie: src/rust/engine.
# + MODE: Whether to run in debug or release mode.
# + MODE_FLAG: The string to pass to Cargo to determine if we're in debug or release mode.
# Exposes:
# + calculate_current_hash: Generate a stable hash to determine if we need to rebuild the engine.
# shellcheck source=build-support/bin/native/calculate_engine_hash.sh
source "${REPO_ROOT}/build-support/bin/native/calculate_engine_hash.sh"

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

readonly NATIVE_ENGINE_BINARY="native_engine.so"
readonly NATIVE_ENGINE_RESOURCE="${REPO_ROOT}/src/python/pants/engine/${NATIVE_ENGINE_BINARY}"
readonly NATIVE_ENGINE_CACHE_DIR=${CACHE_ROOT}/bin/native-engine

function _build_native_code() {
  # Builds the native code, and echos the path of the built binary.

  (
    # Change into $REPO_ROOT in a subshell. This is necessary so that we're in a child of a
    # directory containing the rust-toolchain file, so that rustup knows which version of rust we
    # should be using.
    cd "${REPO_ROOT}"
    "${REPO_ROOT}/build-support/bin/native/cargo" build ${MODE_FLAG} \
      --manifest-path "${NATIVE_ROOT}/Cargo.toml" -p engine_cffi
  ) || die
  echo "${CARGO_TARGET_DIR}/${MODE}/libengine_cffi.${LIB_EXTENSION}"
}

function bootstrap_native_code() {
  # Bootstraps the native code only if needed.
  local native_engine_version
  native_engine_version="$(calculate_current_hash)"
  local engine_version_hdr="engine_version: ${native_engine_version}"
  local target_binary="${NATIVE_ENGINE_CACHE_DIR}/${native_engine_version}/${NATIVE_ENGINE_BINARY}"
  local target_binary_metadata="${target_binary}.metadata"
  if [[ -d "${NATIVE_ROOT}/target" ]]
  then
    die "The old native code cache ${NATIVE_ROOT}/target has been replaced
with ${CARGO_TARGET_DIR}\n
Please remove the old directory with: \`rm -rf ${NATIVE_ROOT}/target\`"
  fi

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

    mkdir -p "$(dirname "${target_binary}")"
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
