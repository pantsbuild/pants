#!/usr/bin/env bash
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# TravisCI-specific environment fixups can live in this script which forwards to the generic ci
# script post fixups.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

function pyenv_path {
  local -r pyenv_root="$(cd "$(dirname "$(which pyenv)")/.." && pwd -P)"
  pyenv versions --bare | while read v; do
    echo "${pyenv_root}/versions/${v}/bin"
  done
}

# TravisCI uses pyenv to provide some interpreters pre-installed for images. Unfortunately it places
# `~/.pyenv/shims` on the PATH and these shims are broken (see:
# https://github.com/travis-ci/travis-ci/issues/8363). We work around this by placing
# `~/.pyenv/versions/<version>/bin` dirs on the PATH ahead of the broken shims.
if which pyenv &>/dev/null; then
  PYENV_PYTHONS="$(pyenv_path)"
  PYENV_PATH="$(echo ${PYENV_PYTHONS} | tr ' ' ':')"

  echo "Executing ./build-support/bin/ci.sh "$@" with ${PYENV_PATH} preprended to the PATH"

  export PATH="${PYENV_PATH}:${PATH}"
fi

exec ./build-support/bin/ci.sh "$@"