#!/bin/bash -e

# This script wraps the main() method in binary_util.py.

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../.. && pwd -P)
BINARY_HELPER_SCRIPT="${REPO_ROOT}/src/python/pants/binaries/binary_util.py"

# shellcheck source=build-support/pants_venv
source "${REPO_ROOT}/build-support/pants_venv"

activate_pants_venv 1>&2
PYTHONPATH="${REPO_ROOT}/src/python:${PYTHONPATH}" python "$BINARY_HELPER_SCRIPT" "$@"
