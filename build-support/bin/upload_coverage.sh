#!/bin/bash -e

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../.. && pwd -P)

# shellcheck source=build-support/common.sh
source "${REPO_ROOT}/build-support/common.sh"

PY="$(determine_python)"
export PY

# shellcheck source=build-support/pants_venv
source "${REPO_ROOT}/build-support/pants_venv"

activate_pants_venv 1>&2
PYTHONPATH="${REPO_ROOT}/src/python:${PYTHONPATH}" pip install coveralls
cp "${REPO_ROOT}/dist/coverage/python/.coverage" .
PYTHONPATH="${REPO_ROOT}/src/python:${PYTHONPATH}" coveralls
rm .coverage