# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../../.. && pwd -P)"

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
  local engine_version_calculated
  engine_version_calculated="$(calculate_current_hash)"
  local engine_version_in_metadata
  if [[ -f "${NATIVE_ENGINE_RESOURCE_METADATA}" ]]; then
    engine_version_in_metadata="$(sed -n 's/^engine_version: //p' "${NATIVE_ENGINE_RESOURCE_METADATA}")"
  fi
  if [[ ! -f "${NATIVE_ENGINE_RESOURCE}" || "${engine_version_calculated}" != "${engine_version_in_metadata}" ]]; then
    echo "Building native engine"
    local -r native_binary="$(_build_native_code)"

    # If bootstrapping the native engine fails, don't attempt to run pants
    # afterwards.
    if [[ ! -f "${native_binary}" ]]; then
      die "Failed to build native engine."
    fi

    # Pick up Cargo.lock changes if any caused by the `cargo build`.
    engine_version_calculated="$(calculate_current_hash)"

    # Create the native engine resource.
    # NB: On Mac Silicon, for some reason, first removing the old native_engine.so is necessary to avoid the Pants
    #  process from being killed when recompiling.
    rm -f "${NATIVE_ENGINE_RESOURCE}"
    cp "${native_binary}" "${NATIVE_ENGINE_RESOURCE}"

    # Create the accompanying metadata file.
    local -r metadata_file=$(mktemp -t pants.native_engine.metadata.XXXXXX)
    echo "engine_version: ${engine_version_calculated}" > "${metadata_file}"
    echo "repo_version: $(git describe --dirty)" >> "${metadata_file}"
    mv "${metadata_file}" "${NATIVE_ENGINE_RESOURCE_METADATA}"
  fi
}
