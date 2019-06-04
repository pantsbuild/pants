#!/usr/bin/env bash

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}"

./build-support/bin/native/cargo clippy --manifest-path="${REPO_ROOT}/src/rust/engine/Cargo.toml" --all
