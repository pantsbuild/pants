#!/usr/bin/env bash

set -e

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../../.. && pwd -P)

# Exports:
# + CARGO_HOME: The CARGO_HOME of the Pants-controlled rust toolchain.
# Exposes:
# + ensure_native_build_prerequisites: Bootstraps a Pants-controlled rust toolchain and associated
#                                      extras.
source "${REPO_ROOT}/build-support/bin/native/bootstrap_rust.sh"
ensure_native_build_prerequisites >&2

# The following is needed by grpcio-sys and we have no better way to hook its build.rs than this;
# ie: wrapping cargo.
readonly download_binary="${REPO_ROOT}/build-support/bin/download_binary.sh"
readonly cmakeroot="$("${download_binary}" "binaries.pantsbuild.org" "cmake" "3.9.5" "cmake.tar.gz")"
readonly goroot="$("${download_binary}" "binaries.pantsbuild.org" "go" "1.7.3" "go.tar.gz")/go"

export GOROOT="${goroot}"
export PATH="${cmakeroot}/bin:${goroot}/bin:${CARGO_HOME}/bin:${PATH}"

readonly cargo_bin="${CARGO_HOME}/bin/cargo"

if [[ -n "${CARGO_WRAPPER_DEBUG}" ]]; then
  cat << DEBUG >&2
>>> Executing ${cargo_bin} $@
>>> In ENV:
>>>   GOROOT=${GOROOT}
>>>   PATH=${PATH}
>>>
DEBUG
fi

exec "${cargo_bin}" "$@"
