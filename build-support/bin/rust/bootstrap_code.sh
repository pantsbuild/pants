# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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
# shellcheck source=build-support/bin/rust/calculate_engine_hash.sh
source "${REPO_ROOT}/build-support/bin/rust/calculate_engine_hash.sh"

KERNEL=$(uname -s | tr '[:upper:]' '[:lower:]')
case "${KERNEL}" in
  linux)
    readonly LIB_EXTENSION=so
    ;;
  darwin)
    readonly LIB_EXTENSION=dylib
    ;;
  *)
    die "Unknown kernel ${KERNEL}, cannot bootstrap Pants native code!"
    ;;
esac

readonly NATIVE_ENGINE_BINARY="native_engine.so"
readonly NATIVE_ENGINE_RESOURCE="${REPO_ROOT}/src/python/pants/engine/internals/${NATIVE_ENGINE_BINARY}"
readonly NATIVE_ENGINE_RESOURCE_METADATA="${NATIVE_ENGINE_RESOURCE}.metadata"
readonly NATIVE_ENGINE_CACHE_DIR=${CACHE_ROOT}/bin/native-engine

function _build_native_code() {
  # NB: See Cargo.toml with regard to the `extension-module` feature.
  "${REPO_ROOT}/cargo" build --features=extension-module ${MODE_FLAG} -p engine || die
  echo "${NATIVE_ROOT}/target/${MODE}/libengine.${LIB_EXTENSION}"
}

function bootstrap_native_code() {
  # We expose a safety valve to skip compilation iff the user already has `native_engine.so`. This
  # can result in using a stale `native_engine.so`, but we trust that the user knows what
  # they're doing.
  if [[ "${SKIP_NATIVE_ENGINE_SO_BOOTSTRAP}" == "true" ]]; then
    if [[ ! -f "${NATIVE_ENGINE_RESOURCE}" ]]; then
      die "You requested to override bootstrapping native_engine.so via the env var" \
          "SKIP_NATIVE_ENGINE_SO_BOOTSTRAP, but the file does not exist at" \
           "${NATIVE_ENGINE_RESOURCE}. This is not safe to do."
    fi
    return
  fi
  # Bootstraps the native code only if needed.
  local native_engine_version
  native_engine_version="$(calculate_current_hash)"
  local engine_version_hdr="engine_version: ${native_engine_version}"
  local target_binary="${NATIVE_ENGINE_CACHE_DIR}/${native_engine_version}/${NATIVE_ENGINE_BINARY}"
  local target_binary_metadata="${target_binary}.metadata"
  if [[ ! -f "${target_binary}" || ! -f "${target_binary_metadata}" ]]; then
    local -r native_binary="$(_build_native_code)"

    # If bootstrapping the native engine fails, don't attempt to run pants
    # afterwards.
    if [[ ! -f "${native_binary}" ]]; then
      die "Failed to build native engine."
    fi

    # Pick up Cargo.lock changes if any caused by the `cargo build`.
    native_engine_version="$(calculate_current_hash)"
    engine_version_hdr="engine_version: ${native_engine_version}"

    mkdir -p "$(dirname "${target_binary}")"
    cp "${native_binary}" "${target_binary}"

    local -r metadata_file=$(mktemp -t pants.native_engine.metadata.XXXXXX)
    echo "${engine_version_hdr}" > "${metadata_file}"
    echo "repo_version: $(git describe --dirty)" >> "${metadata_file}"
    mv "${metadata_file}" "${target_binary_metadata}"
  fi

  # Establishes the native engine wheel resource if it doesn't exist or its metadata mismatches.
  if [[
    ! -f "${NATIVE_ENGINE_RESOURCE}" ||
    ! -f "${NATIVE_ENGINE_RESOURCE_METADATA}" ||
    "$(head -1 "${NATIVE_ENGINE_RESOURCE_METADATA}" | tr '\0' '\n' 2>/dev/null)" != "${engine_version_hdr}"
  ]]; then
    rm -f "${NATIVE_ENGINE_RESOURCE_METADATA}" "${NATIVE_ENGINE_RESOURCE}"
    cp "${target_binary}" "${NATIVE_ENGINE_RESOURCE}"
    cp "${target_binary_metadata}" "${NATIVE_ENGINE_RESOURCE_METADATA}"
  fi
}
