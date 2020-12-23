# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../../.. && pwd -P)"

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

RUST_TOOLCHAIN_CONTENTS="$(cat "${REPO_ROOT}/rust-toolchain")"

function calculate_current_hash() {
  # Cached and unstaged files, with ignored files excluded.
  # NB: We fork a subshell because one or both of `ls-files`/`hash-object` are
  # sensitive to the CWD, and the `--work-tree` option doesn't seem to resolve that.
  #
  # Assumes we're in the venv that will be used to build the native engine.
  #
  # NB: Ensure that this stays in sync with `githooks/prepare-commit-msg`.
  (
   cd "${REPO_ROOT}" || exit 1
   (echo "${MODE_FLAG}"
    echo "${RUST_TOOLCHAIN_CONTENTS}"
    uname
    python --version 2>&1
    git ls-files --cached --others --exclude-standard \
     "${NATIVE_ROOT}" \
     "${REPO_ROOT}/rust-toolchain" \
     "${REPO_ROOT}/build-support/bin/rust" \
   | grep -v -E -e "/BUILD$" -e "/[^/]*\.md$" \
   | git hash-object --stdin-paths) | fingerprint_data
  )
}
