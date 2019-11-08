#!/usr/bin/env bash

set -euo pipefail

# Install the requested Python version(s) through Pyenv.

# While Travis ships with Pyenv on both OSX and Linux, the Pyenv version is too
# outdated on several images for installing modern Python versions like 3.7. To
# get around this, we directly clone the Pyenv repo.

source build-support/common.sh

PYTHON_VERSIONS=("$@")

if [[ -z "${PYENV_ROOT:+''}" ]]; then
  die "Caller of the script must set the env var PYENV_ROOT."
fi
PYENV_BIN="${PYENV_ROOT}/bin/pyenv"

# We first check if Pyenv is already installed thanks to Travis's cache.
if [[ ! -x "${PYENV_BIN}" ]]; then
  rm -rf "${PYENV_ROOT}"
  git clone https://github.com/pyenv/pyenv "${PYENV_ROOT}"
fi

for python_version in "${PYTHON_VERSIONS[@]}"; do
  if [[ ! -d ${PYENV_ROOT}/versions/"${python_version}" ]]; then
    "${PYENV_BIN}" install "${python_version}"
  fi
done
