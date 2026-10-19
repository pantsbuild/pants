# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# shellcheck shell=bash

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../../.. && pwd -P)"

# Exposes:
# + fingerprint_data: Fingerprints the data on stdin.
# shellcheck source=build-support/common.sh
source "${REPO_ROOT}/build-support/common.sh"

readonly NATIVE_ROOT="${REPO_ROOT}/src/rust"

# N.B. Set $MODE to "debug" for faster builds, or "dist" for the profile used
# to build published artifacts.
readonly MODE="${MODE:-release}"
case "$MODE" in
  debug) MODE_FLAG=() ;;
  dist) MODE_FLAG=(--profile dist) ;;
  *) MODE_FLAG=(--release) ;;
esac

# N.B. Set $NATIVE_TARGET to a Rust target triple (e.g. "aarch64-unknown-linux-gnu") to build the
# native code for that target instead of for the host. Set $ZIGBUILD=1 to compile and link via
# `cargo zigbuild` (https://github.com/rust-cross/cargo-zigbuild), which uses Zig as the C
# compiler and linker, and so can cross-link without a target-specific toolchain. With $ZIGBUILD,
# $NATIVE_TARGET may carry a glibc version suffix (e.g. "x86_64-unknown-linux-gnu.2.17").
readonly NATIVE_TARGET="${NATIVE_TARGET:-}"
readonly ZIGBUILD="${ZIGBUILD:-}"
if [[ -n "${ZIGBUILD}" ]]; then
  CARGO_BUILD_CMD=(zigbuild)
else
  CARGO_BUILD_CMD=(build)
fi
if [[ -n "${NATIVE_TARGET}" ]]; then
  TARGET_FLAG=(--target "${NATIVE_TARGET}")
else
  TARGET_FLAG=()
fi

function calculate_current_hash() {
  # Cached and unstaged files, with ignored files excluded.
  # NB: We fork a subshell because one or both of `ls-files`/`hash-object` are
  # sensitive to the CWD, and the `--work-tree` option doesn't seem to resolve that.
  #
  # Assumes that PY is set to the path to the interpreter that will be used to build the
  # native engine. We only use this to extract the full Python version, so this can point
  # to a raw interpreter, not necessarily one in a venv with Pants requirements installed.
  (
    cd "${REPO_ROOT}" || exit 1
    (
      echo "${MODE_FLAG[*]}"
      echo "${CARGO_BUILD_CMD[*]} ${TARGET_FLAG[*]}"
      uname -mps
      # the engine only depends on the implementation and major.minor version, not the patch
      "${PY}" -c 'import sys; print(sys.implementation.name, sys.version_info.major, sys.version_info.minor, sys.abiflags)'
      git ls-files --cached --others --exclude-standard \
        "${NATIVE_ROOT}" \
        "${REPO_ROOT}/build-support/bin/rust" |
        grep -v -E -e "/BUILD$" -e "/[^/]*\.md$" |
        git hash-object --stdin-paths
    ) | fingerprint_data
  )
}
