#!/usr/bin/env bash

set -e

REPO_ROOT="$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../.. && pwd -P)"

source "${REPO_ROOT}/build-support/bin/native/bootstrap.sh"

readonly actual_native_engine_version="$(calculate_current_hash)"
readonly current_native_engine_version="$(cat ${NATIVE_ENGINE_VERSION_RESOURCE} | tr -d ' \n\r')"


if [ "${actual_native_engine_version}" != "${current_native_engine_version}" ]; then
  die "failed verification: ${current_native_engine_version} != ${actual_native_engine_version}";
else
  echo "verified: ${current_native_engine_version}"
fi
