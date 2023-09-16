# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# shellcheck shell=bash

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../../.. && pwd -P)"

echo

# Exposes:
# + fingerprint_data: Fingerprints the data on stdin.
# shellcheck source=build-support/common.sh
source "${REPO_ROOT}/build-support/common.sh"

readonly NATIVE_ROOT="${REPO_ROOT}/src/rust/engine"

# N.B. Set $MODE to "debug" for faster builds.
readonly MODE="${MODE:-release}"
case "$MODE" in
  debug) MODE_FLAG="" ;;
  *) MODE_FLAG="--release" ;;
esac

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
      echo "${MODE_FLAG}"
      uname -mps
      # the engine only depends on the implementation and major.minor version, not the patch
      "${PY}" -c 'import sys; print(sys.implementation.name, sys.version_info.major, sys.version_info.minor)'
      git ls-files --cached --others --exclude-standard \
        "${NATIVE_ROOT}" \
        "${REPO_ROOT}/build-support/bin/rust" |
        grep -v -E -e "/BUILD$" -e "/[^/]*\.md$" -e "src/rust/engine/cargo_build_shim.sh$" |
        git hash-object --stdin-paths
    ) | fingerprint_data
  )
}
