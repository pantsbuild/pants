#!/bin/bash -e

# This script exists to work around https://github.com/rust-lang/rust/issues/44862
# `cargo test --all` doesn't work because we can't use a workspace, so this script replicates its
# behavior.

here=$(cd $(dirname "${BASH_SOURCE[0]}") && pwd)
REPO_ROOT=$(dirname $(dirname $(dirname ${here})))

source "${REPO_ROOT}/build-support/pants_venv"
source "${REPO_ROOT}/build-support/bin/native/bootstrap.sh"

activate_pants_venv

exit_code=0

for crate in $(find ${here} -name Cargo.toml); do
  (
    echo >&2 "Running tests for ${crate}:"
    RUST_BACKTRACE=1 PANTS_SRCPATH="${REPO_ROOT}/src/python" ensure_cffi_sources=1 run_cargo test ${MODE_FLAG} \
      --manifest-path=${crate}
  ) || exit_code=1
done

exit ${exit_code}
