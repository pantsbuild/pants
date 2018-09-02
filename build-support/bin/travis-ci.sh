#!/usr/bin/env bash

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

function pyenv_path {
  local -r pyenv_root="$(cd "$(dirname "$(which pyenv)")/.." && pwd -P)"
  pyenv versions --bare | while read v; do
    echo "${pyenv_root}/versions/${v}/bin"
  done
}

if which pyenv &>/dev/null; then
  PYENV_PYTHONS="$(pyenv_path)"
  PYENV_PATH="$(echo ${PYENV_PYTHONS} | tr ' ' ':')"

  echo "Executing ./build-support/bin/ci.sh "$@" with ${PYENV_PATH} preprended to the PATH"

  export PATH="${PYENV_PATH}:${PATH}"
fi
exec ./build-support/bin/ci.sh "$@"