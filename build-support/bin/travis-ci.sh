#!/usr/bin/env bash
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# TravisCI-specific environment fixups can live in this script which forwards to the generic ci
# script post fixups.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

PYENV="$(which pyenv 2>/dev/null)"
PYENV_ROOT="$(pyenv root 2>/dev/null || true)"

function pyenv_path {
  "${PYENV}" versions --bare --skip-aliases | while read v; do
    echo "${PYENV_ROOT}/versions/${v}/bin"
  done
}

function list_pythons {
  which -a python{,2,3} | sort -u | while read python_bin; do
    ${python_bin} <<EOF
import os
import sys

print('{} -> {}'.format(os.path.realpath(sys.executable),
                        '.'.join(map(str, sys.version_info[:3]))))
EOF
  done
}

# TravisCI uses pyenv to provide some interpreters pre-installed for images. Unfortunately it places
# `~/.pyenv/shims` on the PATH and these shims are broken (see:
# https://github.com/travis-ci/travis-ci/issues/8363). We work around this by placing
# removing shims from the PATH and adding `~/.pyenv/versions/<version>/bin`.
if [ -n "${PYENV}" ]; then
  PYENV_PYTHONS="$(pyenv_path)"
  PYENV_PATH="$(echo ${PYENV_PYTHONS} | tr ' ' ':')"

  SHIMLESS_PATH="$(echo "${PATH}" | tr : '\n' | grep -v "${PYENV_ROOT}/shims")"
  PATH="$(echo ${SHIMLESS_PATH} | tr ' ' ':')"

  export PATH="${PYENV_PATH}:${PATH}"

cat <<EOF
Executing ./build-support/bin/ci.sh "$@" with "${PYENV_PATH}" preprended to the PATH
and "${PYENV_ROOT}/shims" removed from the PATH.

Visible pythons are now:
$(list_pythons | sort -u)

EOF
fi

exec ./build-support/bin/ci.sh "$@"
