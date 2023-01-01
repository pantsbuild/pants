#!/usr/bin/env bash

REPO_ROOT="$(git rev-parse --show-toplevel)"

BASE_COMMAND="${REPO_ROOT}/cargo fmt --all --"

$BASE_COMMAND --check
exit_code=$?

if [[ ${exit_code} -ne 0 ]]; then
  echo >&2 "Rust files incorrectly formatted, run \`${BASE_COMMAND}\` to reformat them."
  exit 1
fi
