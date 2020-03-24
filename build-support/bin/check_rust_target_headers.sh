#!/usr/bin/env bash

REPO_ROOT="$(git rev-parse --show-toplevel)"

cargo="${REPO_ROOT}/build-support/bin/native/cargo"

"${cargo}" ensure-installed --package cargo-ensure-prefix --version 0.1.3

if ! out="$("${cargo}" ensure-prefix \
  --manifest-path="${REPO_ROOT}/src/rust/engine/Cargo.toml" \
  --prefix-path="${REPO_ROOT}/build-support/rust-target-prefix.txt" \
  --all --exclude=bazel_protos)"; then
  echo >&2 "Rust targets didn't have correct prefix:"
  echo >&2 "${out}"
  exit 1
fi
