#!/usr/bin/env bash

set -e

REPO_ROOT="$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../.. && pwd -P)"

# Defines:
# + CACHE_ROOT: The pants cache root dir.
# + NATIVE_ENGINE_CACHE_DIR: The native engine binary root cache directory.
# + NATIVE_ENGINE_CACHE_TARGET_DIR: The directory containing all versions of the native engine for
#                                   the current OS.
# + NATIVE_ENGINE_BINARY: The basename of the native engine binary for the current OS.
# + NATIVE_ENGINE_VERSION_RESOURCE: The path of the resource file containing the native engine
#                                   version hash.
# Exposes:
# + calculate_current_hash: Calculates the current native engine version hash and echoes it to
#                           stdout.
# + bootstrap_native_code: Builds target-specific native engine binaries.
source "${REPO_ROOT}/build-support/bin/native/bootstrap.sh"

readonly actual_native_engine_version="$(calculate_current_hash)"
readonly current_native_engine_version="$(cat ${NATIVE_ENGINE_VERSION_RESOURCE} | tr -d ' \n\r')"


if [ "${actual_native_engine_version}" != "${current_native_engine_version}" ]; then
  die "failed verification: ${current_native_engine_version} != ${actual_native_engine_version}";
else
  echo "verified: ${current_native_engine_version}"
fi
