#!/usr/bin/env bash
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

set -e

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../../.. && pwd -P)

export PY=${PY:-python3}
# Consumed by the cpython crate.
export PYTHON_SYS_EXECUTABLE="${PY}"

# Exports:
# + CARGO_HOME: The CARGO_HOME of the Pants-controlled rust toolchain.
# Exposes:
# + bootstrap_rust: Bootstraps a Pants-controlled rust toolchain and associated extras.
# shellcheck source=build-support/bin/native/bootstrap_rust.sh
source "${REPO_ROOT}/build-support/bin/native/bootstrap_rust.sh"

# Exposes:
# + activate_pants_venv: Activate a virtualenv for pants requirements, creating it if needed.
#
# This is necessary for any `cpython`-dependent crates, which need a python interpeter on the PATH.
# shellcheck source=build-support/pants_venv
source "${REPO_ROOT}/build-support/pants_venv"

bootstrap_rust >&2

activate_pants_venv

download_binary="${REPO_ROOT}/build-support/bin/download_binary.sh"

# The following is needed by grpcio-sys and we have no better way to hook its build.rs than this;
# ie: wrapping cargo.
cmakeroot="$("${download_binary}" "cmake" "3.9.5" "cmake.tar.gz")"
goroot="$("${download_binary}" "go" "1.7.3" "go.tar.gz")/go"

# Code generation in the bazel_protos crate needs to be able to find protoc on the PATH.
protoc="$("${download_binary}" "protobuf" "3.4.1" "protoc")"

export GOROOT="${goroot}"
PATH="${cmakeroot}/bin:${goroot}/bin:${CARGO_HOME}/bin:$(dirname "${protoc}"):${PATH}"
export PATH
export PROTOC="${protoc}"

# We implicitly pull in `ar` to create libnative_engine_ffi.a from native_engine.o via the `cc`
# crate in engine_cffi/build.rs.
case "$(uname)" in
  "Darwin")
    # The homebrew version of the `ar` tool appears to "sometimes" create libnative_engine_ffi.a
    # instances which aren't recognized as Mach-O x86-64 binaries when first on the PATH. This
    # causes a silent linking error at build time due to the use of the `-undefined dynamic_lookup`
    # flag, which then becomes:
    # "Symbol not found: _wrapped_PyInit_native_engine"
    # when attempting to import the native engine library in native.py.
    # NB: This line uses the version of `ar` provided by OSX itself, which avoids the linking error.
    export AR='/usr/bin/ar'
    ;;
  "Linux")
    # While the linking error when consuming libnative_engine_ffi.a does not repro on Linux, since
    # we have a reliable version of `ar` available from the pantsbuild s3, we might as well use it.
    binutils="$("${download_binary}" "binutils" "2.30" "binutils.tar.gz")"
    export AR="${binutils}/bin/ar"
    ;;
  *)
    die "Unknown platform: uname was $(uname)"
    ;;
esac

cargo_bin="${CARGO_HOME}/bin/cargo"

if [[ -n "${CARGO_WRAPPER_DEBUG}" ]]; then
  cat << DEBUG >&2
>>> Executing ${cargo_bin} $@
>>> In ENV:
>>>   GOROOT=${GOROOT}
>>>   PATH=${PATH}
>>>   PROTOC=${PROTOC}
>>>   AR=${AR:-<not explicitly set>}
>>>
DEBUG
fi

exec "${cargo_bin}" "$@"
