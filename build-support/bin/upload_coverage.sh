#!/bin/bash -e

export PY=${PY:-python3}
export PYTHON_SYS_EXECUTABLE="${PY}"

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../.. && pwd -P)
# shellcheck source=build-support/pants_venv
source "${REPO_ROOT}/build-support/pants_venv"

activate_pants_venv 1>&2
PYTHONPATH="${REPO_ROOT}/src/python:${PYTHONPATH}" pip install coveralls
cp "${REPO_ROOT}/dist/coverage/python/.coverage" .
PYTHONPATH="${REPO_ROOT}/src/python:${PYTHONPATH}" coveralls
rm .coverage