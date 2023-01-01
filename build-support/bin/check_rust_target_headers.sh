#!/usr/bin/env bash

REPO_ROOT="$(git rev-parse --show-toplevel)"

"${REPO_ROOT}/cargo" install cargo-ensure-prefix --locked --version "=0.1.7"

if ! out="$("${REPO_ROOT}/cargo" ensure-prefix \
  --manifest-path="${REPO_ROOT}/src/rust/engine/Cargo.toml" \
  --prefix-path="${REPO_ROOT}/build-support/rust-target-prefix.txt" \
  --all --exclude=protos)"; then
  echo >&2 "Rust targets didn't have correct prefix:"
  echo >&2 "${out}"
  exit 1
fi
