#!/usr/bin/env bash
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../.. && pwd -P)"

cd "$REPO_ROOT" || exit 1

# This script is used to generate pants.pex, which is used in pants' own integration tests.

export PY="${PY:-python3}"

# shellcheck source=build-support/common.sh
source "${REPO_ROOT}/build-support/common.sh"
# shellcheck source=build-support/pants_venv
source "${REPO_ROOT}/build-support/pants_venv"
# shellcheck source=build-support/bin/native/bootstrap_code.sh
source "${REPO_ROOT}/build-support/bin/native/bootstrap_code.sh"

./v2 binary src/python/pants/bin:pants_local_binary || exit 1
mv dist/pants_local_binary.pex pants.pex
