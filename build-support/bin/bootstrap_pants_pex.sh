#!/usr/bin/env bash
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../.. && pwd -P)"

cd "$REPO_ROOT" || exit 1

# This script is used to generate pants.pex, which is used to run Pants in CI.

# shellcheck source=build-support/common.sh
source "${REPO_ROOT}/build-support/common.sh"

PY="$(determine_python)"
export PY

# shellcheck source=build-support/pants_venv
source "${REPO_ROOT}/build-support/pants_venv"
# shellcheck source=build-support/bin/rust/bootstrap_code.sh
source "${REPO_ROOT}/build-support/bin/rust/bootstrap_code.sh"

./pants package src/python/pants/bin:pants_local_binary || exit 1
mv dist/src.python.pants.bin/pants_local_binary.pex pants.pex
