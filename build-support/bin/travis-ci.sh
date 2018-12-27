#!/usr/bin/env bash
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# TravisCI-specific environment fixups can live in this script which forwards to the generic ci
# script post fixups.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

export RUNNING_VIA_TRAVIS_CI_SCRIPT=1

PYENV_ROOT="$(pyenv root 2>/dev/null || true)"

function pyenv_path {
  pyenv versions --bare --skip-aliases | while read v; do
    echo "${PYENV_ROOT}/versions/${v}/bin/python"
  done
}

# TravisCI uses pyenv to provide some interpreters pre-installed for images. Unfortunately it places
# `~/.pyenv/shims` on the PATH and these shims are broken (see:
# https://github.com/travis-ci/travis-ci/issues/8363). We work around this by setting
# PEX_PYTHON_PATH in <buildroot>/.pexrc. This will force pex to use only these paths at runtime,
# and we similarly force pants to do so at pex build time by setting the interpreter_search_path
# appropriately in pants.travis-ci.ini.
if [ -n "${PYENV_ROOT}" ]; then
  PEXRC_FILE=./.pexrc
  PYENV_PYTHONS="$(pyenv_path)"
  PYENV_PATH="$(echo ${PYENV_PYTHONS} | tr ' ' ':')"
  PEX_PYTHON_PATH_STANZA="PEX_PYTHON_PATH=${PYENV_PATH}"
  echo ${PEX_PYTHON_PATH_STANZA} > ${PEXRC_FILE}

cat <<EOF
Executing ./build-support/bin/ci.sh "$@" with ${PEX_PYTHON_PATH_STANZA} set in ${PEXRC_FILE}
EOF
fi

exec ./build-support/bin/ci.sh "$@"
