# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# shellcheck shell=bash

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../../.. && pwd -P)"

# shellcheck source=build-support/common.sh
source "${REPO_ROOT}/build-support/common.sh"

# Defines:
# + NATIVE_ROOT: The Rust code directory, ie: src/rust.
# + MODE: Whether to run in debug or release mode.
# + MODE_FLAG: An array of arguments to pass to Cargo to select the profile to build with.
# + CARGO_BUILD_CMD: The Cargo subcommand to build with: `build`, or `zigbuild` if $ZIGBUILD is set.
# + TARGET_FLAG: An array of arguments to pass to Cargo to select the target to build for.
# Exposes:
# + calculate_current_hash: Generate a stable hash to determine if we need to rebuild the engine.
# shellcheck source=build-support/bin/rust/calculate_engine_hash.sh
source "${REPO_ROOT}/build-support/bin/rust/calculate_engine_hash.sh"

if [[ -n "${NATIVE_TARGET}" ]]; then
  case "${NATIVE_TARGET}" in
    *-linux-*) KERNEL=linux ;;
    *-apple-darwin*) KERNEL=darwin ;;
    *) KERNEL="${NATIVE_TARGET}" ;;
  esac
else
  KERNEL=$(uname -s | tr '[:upper:]' '[:lower:]')
fi
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

if [[ -n "${ZIGBUILD}" ]] && ! command -v cargo-zigbuild &> /dev/null; then
  die "ZIGBUILD is set, but \`cargo-zigbuild\` is not on your PATH. See https://github.com/rust-cross/cargo-zigbuild#installation"
fi
if [[ -z "${ZIGBUILD}" && "${NATIVE_TARGET}" == *.* ]]; then
  die "NATIVE_TARGET=${NATIVE_TARGET} has a glibc version suffix, which is only supported with ZIGBUILD=1."
fi

if [[ -n "${NATIVE_TARGET}" ]]; then
  # Cargo writes target-specific output under a directory named for the triple, without any
  # zigbuild glibc version suffix.
  readonly NATIVE_TARGET_DIR="${NATIVE_ROOT}/target/${NATIVE_TARGET%%.*}/${MODE}"
else
  readonly NATIVE_TARGET_DIR="${NATIVE_ROOT}/target/${MODE}"
fi

readonly NATIVE_ENGINE_BINARY="native_engine.so"
export NATIVE_CLIENT_BINARY="${REPO_ROOT}/src/python/pants/bin/native_client"
export NATIVE_SANDBOXER_BINARY="${REPO_ROOT}/src/python/pants/bin/sandboxer"
export NATIVE_PANTS_LOCK_BINARY="${REPO_ROOT}/src/python/pants/bin/pants_lock"
readonly NATIVE_ENGINE_RESOURCE="${REPO_ROOT}/src/python/pants/engine/internals/${NATIVE_ENGINE_BINARY}"
readonly NATIVE_ENGINE_RESOURCE_METADATA="${NATIVE_ENGINE_RESOURCE}.metadata"
readonly NATIVE_CLIENT_TARGET="${NATIVE_TARGET_DIR}/pants"
readonly NATIVE_SANDBOXER_TARGET="${NATIVE_TARGET_DIR}/sandboxer"
readonly NATIVE_PANTS_LOCK_TARGET="${NATIVE_TARGET_DIR}/pants_lock"

# Previously built native code, keyed by engine hash, so that returning to a previously built
# state of the repo doesn't require recompiling or relinking.
readonly NATIVE_CODE_CACHE="${HOME}/.cache/pants/native_code"
readonly NATIVE_CODE_CACHE_MAX_ENTRIES="${PANTS_NATIVE_CODE_CACHE_MAX_ENTRIES:-20}"

function _native_code_cached() {
  local -r cache_entry="$1"
  [[ -f "${cache_entry}/${NATIVE_ENGINE_BINARY}" && -f "${cache_entry}/native_client" &&
    -f "${cache_entry}/sandboxer" && -f "${cache_entry}/pants_lock" ]]
}

function _cache_native_code() {
  local -r cache_entry="$1"
  local -r native_binary="$2"
  mkdir -p "${NATIVE_CODE_CACHE}"
  # Populate a temporary dir and then rename it into place, so that concurrent bootstraps never
  # see a partially populated cache entry.
  local tmp_entry
  # NB: The dot prefix hides it from the eviction listing below.
  tmp_entry="$(mktemp -d "${NATIVE_CODE_CACHE}/.tmp.XXXXXX")" || die
  cp "${native_binary}" "${tmp_entry}/${NATIVE_ENGINE_BINARY}" || die
  cp "${NATIVE_CLIENT_TARGET}" "${tmp_entry}/native_client" || die
  cp "${NATIVE_SANDBOXER_TARGET}" "${tmp_entry}/sandboxer" || die
  cp "${NATIVE_PANTS_LOCK_TARGET}" "${tmp_entry}/pants_lock" || die
  if [[ -d "${cache_entry}" ]]; then
    # A concurrent bootstrap already created this entry.
    rm -rf "${tmp_entry}"
  else
    mv "${tmp_entry}" "${cache_entry}"
  fi

  # Evict the least recently used entries beyond the limit (cache hits touch their entry).
  # shellcheck disable=SC2012
  ls -1t "${NATIVE_CODE_CACHE}" | tail -n +"$((NATIVE_CODE_CACHE_MAX_ENTRIES + 1))" |
    while read -r stale_entry; do
      rm -rf "${NATIVE_CODE_CACHE:?}/${stale_entry}"
    done
}

function _build_native_code() {
  banner "Building native code..."
  # NB: See Cargo.toml with regard to the `extension-module` features.
  "${REPO_ROOT}/cargo" "${CARGO_BUILD_CMD[@]}" \
    --features=extension-module \
    "${MODE_FLAG[@]}" \
    "${TARGET_FLAG[@]}" \
    -p engine \
    -p client \
    -p sandboxer \
    -p pants_lock || die
}

function bootstrap_native_code() {
  # Bootstraps the native code only if needed.
  local engine_version_calculated
  engine_version_calculated="$(calculate_current_hash)"
  local engine_version_in_metadata
  if [[ -f "${NATIVE_ENGINE_RESOURCE_METADATA}" ]]; then
    engine_version_in_metadata="$(sed -n 's/^engine_version: //p' "${NATIVE_ENGINE_RESOURCE_METADATA}")"
  fi

  if [[ -f "${NATIVE_ENGINE_RESOURCE}" && -f "${NATIVE_CLIENT_BINARY}" && -f "${NATIVE_SANDBOXER_BINARY}" &&
    -f "${NATIVE_PANTS_LOCK_BINARY}" &&
    "${engine_version_calculated}" == "${engine_version_in_metadata}" ]]; then
    return 0
  fi

  local cache_entry="${NATIVE_CODE_CACHE}/${engine_version_calculated}"
  if _native_code_cached "${cache_entry}"; then
    banner "Using cached native code from ${cache_entry}"
    touch "${cache_entry}"
  else
    _build_native_code || die

    # If bootstrapping the native engine fails, don't attempt to run Pants afterwards.
    local -r native_binary="${NATIVE_TARGET_DIR}/libengine.${LIB_EXTENSION}"
    if [[ ! -f "${native_binary}" ]]; then
      die "Failed to build native engine, file missing at ${native_binary}."
    fi

    # If bootstrapping the native client fails, don't attempt to run Pants afterwards.
    if [[ ! -f "${NATIVE_CLIENT_TARGET}" ]]; then
      die "Failed to build native client, file missing at ${NATIVE_CLIENT_TARGET}."
    fi

    # If bootstrapping the sandboxer fails, don't attempt to run Pants afterwards.
    if [[ ! -f "${NATIVE_SANDBOXER_TARGET}" ]]; then
      die "Failed to build native sandboxer, file missing at ${NATIVE_SANDBOXER_TARGET}."
    fi

    # If bootstrapping the pants_lock fails, don't attempt to run Pants afterwards.
    if [[ ! -f "${NATIVE_PANTS_LOCK_TARGET}" ]]; then
      die "Failed to build native pants_lock, file missing at ${NATIVE_PANTS_LOCK_TARGET}."
    fi

    # Pick up Cargo.lock changes if any caused by the `cargo build`.
    engine_version_calculated="$(calculate_current_hash)"
    cache_entry="${NATIVE_CODE_CACHE}/${engine_version_calculated}"
    _cache_native_code "${cache_entry}" "${native_binary}"
  fi

  # Create the native engine resource.
  # NB: Remove the old files rather than copying over them:
  #  * On Mac Silicon, for some reason, overwriting the old native_engine.so causes the Pants
  #    process to be killed when recompiling.
  #  * For the sandboxer, we needed to delete it to void copying over a
  #    running binary, which could ironically fail with ETXTBSY
  rm -f "${NATIVE_ENGINE_RESOURCE}" "${NATIVE_CLIENT_BINARY}" "${NATIVE_SANDBOXER_BINARY}" \
    "${NATIVE_PANTS_LOCK_BINARY}"
  cp "${cache_entry}/${NATIVE_ENGINE_BINARY}" "${NATIVE_ENGINE_RESOURCE}"
  cp "${cache_entry}/native_client" "${NATIVE_CLIENT_BINARY}"
  cp "${cache_entry}/sandboxer" "${NATIVE_SANDBOXER_BINARY}"
  cp "${cache_entry}/pants_lock" "${NATIVE_PANTS_LOCK_BINARY}"

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
