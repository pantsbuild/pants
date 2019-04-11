#!/usr/bin/env bash

set -e

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../../.. && pwd -P)

export PY=${PY:-python}

# Exports:
# + CARGO_HOME: The CARGO_HOME of the Pants-controlled rust toolchain.
# Exposes:
# + bootstrap_rust: Bootstraps a Pants-controlled rust toolchain and associated extras.
source "${REPO_ROOT}/build-support/bin/native/bootstrap_rust.sh"

bootstrap_rust >&2

download_binary="${REPO_ROOT}/build-support/bin/download_binary.sh"

# The following is needed by grpcio-sys and we have no better way to hook its build.rs than this;
# ie: wrapping cargo.
cmakeroot="$("${download_binary}" "cmake" "3.9.5" "cmake.tar.gz")"
goroot="$("${download_binary}" "go" "1.7.3" "go.tar.gz")/go"

# Code generation in the bazel_protos crate needs to be able to find protoc on the PATH.
protoc="$("${download_binary}" "protobuf" "3.4.1" "protoc")"

export GOROOT="${goroot}"
export PATH="${cmakeroot}/bin:${goroot}/bin:${CARGO_HOME}/bin:$(dirname "${protoc}"):${PATH}"
export PROTOC="${protoc}"

cargo_bin="${CARGO_HOME}/bin/cargo"

if [[ -n "${CARGO_WRAPPER_DEBUG}" ]]; then
  cat << DEBUG >&2
>>> Executing ${cargo_bin} $@
>>> In ENV:
>>>   GOROOT=${GOROOT}
>>>   PATH=${PATH}
>>>   PROTOC=${PROTOC}
>>>
DEBUG
fi

exec "${cargo_bin}" "$@"
