#!/usr/bin/env bash
# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

set -e

source "build-support/common.sh"

if [[ "${USE_PY38:-false}" == "true" ]]; then
  default_python=python3.8
elif [[ "${USE_PY39:-false}" == "true" ]]; then
  default_python=python3.9
  interpreter_constraint="==3.9.*"
else
  default_python=python3.7
  interpreter_constraint="==3.7.*"
fi

export PY="${PY:-${default_python}}"
if ! command -v "${PY}" > /dev/null; then
  die "Python interpreter ${PY} not discoverable on your PATH."
fi
py_major_minor=$(${PY} -c 'import sys; print(".".join(map(str, sys.version_info[0:2])))')
if [[ "${py_major_minor}" != "3.7" && "${py_major_minor}" != "3.8" && "${py_major_minor}" != "3.9" ]]; then
  die "Invalid interpreter. The release script requires Python 3.7, 3.8, or 3.9 (you are using ${py_major_minor})."
fi

# This influences what setuptools is run with, which determines the interpreter used for building
# `pantsbuild.pants`. It also influences what package.py is run with, which determines which Python is used to create
# a temporary venv to build 3rdparty wheels.
#
# NB: This must align with $PY for the native wheel to be built correctly.
export PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS="['${interpreter_constraint}']"

exec ./pants run build-support/bin/release_helper.py -- "$@"
