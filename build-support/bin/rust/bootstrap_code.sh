# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# shellcheck shell=bash

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../../.. && pwd -P)"

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
export NATIVE_CLIENT_BINARY="${REPO_ROOT}/src/python/pants/bin/native_client"
readonly NATIVE_ENGINE_RESOURCE="${REPO_ROOT}/src/python/pants/engine/internals/${NATIVE_ENGINE_BINARY}"
readonly NATIVE_ENGINE_RESOURCE_METADATA="${NATIVE_ENGINE_RESOURCE}.metadata"
readonly NATIVE_CLIENT_TARGET="${NATIVE_ROOT}/target/${MODE}/pants"

function _build_native_code() {
  banner "Building native code..."
  # NB: See Cargo.toml with regard to the `extension-module` features.
  "${REPO_ROOT}/cargo" build \
    --features=extension-module \
    ${MODE_FLAG} \
    -p engine \
    -p client || die
}

function bootstrap_native_code() {
  # Bootstraps the native code only if needed.
  local engine_version_calculated
  engine_version_calculated="$(calculate_current_hash)"
  local engine_version_in_metadata
  if [[ -f "${NATIVE_ENGINE_RESOURCE_METADATA}" ]]; then
    engine_version_in_metadata="$(sed -n 's/^engine_version: //p' "${NATIVE_ENGINE_RESOURCE_METADATA}")"
  fi

  if [[ -f "${NATIVE_ENGINE_RESOURCE}" && -f "${NATIVE_CLIENT_BINARY}" &&
    "${engine_version_calculated}" == "${engine_version_in_metadata}" ]]; then
    return 0
  fi

  _build_native_code || die

  # If bootstrapping the native engine fails, don't attempt to run Pants afterwards.
  local -r native_binary="${NATIVE_ROOT}/target/${MODE}/libengine.${LIB_EXTENSION}"
  if [[ ! -f "${native_binary}" ]]; then
    die "Failed to build native engine, file missing at ${native_binary}."
  fi

  # If bootstrapping the native client fails, don't attempt to run Pants afterwards.
  if [[ ! -f "${NATIVE_CLIENT_TARGET}" ]]; then
    die "Failed to build native client."
  fi

  # Pick up Cargo.lock changes if any caused by the `cargo build`.
  engine_version_calculated="$(calculate_current_hash)"

  # Create the native engine resource.
  # NB: On Mac Silicon, for some reason, first removing the old native_engine.so is necessary to avoid the Pants
  #  process from being killed when recompiling.
  rm -f "${NATIVE_ENGINE_RESOURCE}" "${NATIVE_CLIENT_BINARY}"
  cp "${native_binary}" "${NATIVE_ENGINE_RESOURCE}"
  cp "${NATIVE_CLIENT_TARGET}" "${NATIVE_CLIENT_BINARY}"

  # Create the accompanying metadata file.
  local -r metadata_file=$(mktemp -t pants.native_engine.metadata.XXXXXX)
  echo "engine_version: ${engine_version_calculated}" > "${metadata_file}"
  echo "repo_version: $(git describe --dirty)" >> "${metadata_file}"

  # Here we set up a file lock via bash tricks to avoid concurrent `mv` failing.
  if {
    set -C # Set noclobber temporarily to ensure file creation via `>` is atomic and exclusive.
    echo 2> /dev/null "$$" > "${NATIVE_ENGINE_RESOURCE_METADATA}.lock"
  }; then
    # N.B.: We want the NATIVE_ENGINE_RESOURCE_METADATA env var to be expanded now.
    # See: https://github.com/koalaman/shellcheck/wiki/SC2064
    #
    # shellcheck disable=SC2064
    trap "rm -f ${NATIVE_ENGINE_RESOURCE_METADATA}.lock" RETURN
    mv "${metadata_file}" "${NATIVE_ENGINE_RESOURCE_METADATA}"
  else
    local -r locked_by="$(
      cat "${NATIVE_ENGINE_RESOURCE_METADATA}.lock" 2 > /dev/null || echo "<unknown>"
    )"
    echo >&2 "Process $$ yielding to concurrent bootstrap by pid ${locked_by}."
  fi
  set +C
}
