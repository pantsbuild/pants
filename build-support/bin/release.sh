#!/usr/bin/env bash
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

set -e

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd "$(git rev-parse --show-toplevel)" && pwd)

# shellcheck source=build-support/common.sh
source "${ROOT}/build-support/common.sh"

# TODO: make this less hacky when porting to Python 3. Use proper `--python-version` flags, like
#  those used by ci.py.
if [[ "${USE_PY38:-false}" == "true" ]]; then
  default_python=python3.8
  interpreter_constraint="==3.8.*"
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
export PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS="['${interpreter_constraint}']"

function run_packages_script() {
  (
    cd "${ROOT}"
    ./pants run "${ROOT}/build-support/bin/packages.py" -- "$@"
  )
}

_OPTS="hnftlowepq"

function usage() {
  echo "With no options all packages are built, smoke tested and published to"
  echo "PyPI.  Credentials are needed for this as described in the"
  echo "release docs: https://www.pantsbuild.org/docs/releases"
  echo
  echo "Usage: $0 (-h|-n|-f|-t|-l|-o|-w|-e|-p|-q)"
  echo " -h  Prints out this help message."
  echo " -n  Performs a release dry run."
  echo "       All package distributions will be built, installed locally in"
  echo "       an ephemeral virtualenv and exercised to validate basic"
  echo "       functioning."
  echo " -f  Build the fs_util binary."
  echo " -t  Tests a live release."
  echo "       Ensures the latest packages have been propagated to PyPI"
  echo "       and can be installed in an ephemeral virtualenv."
  echo " -l  Lists all pantsbuild packages that this script releases."
  echo " -o  Lists all pantsbuild package owners."
  echo " -w  List pre-built wheels for this release (specifically the URLs to download)."
  echo " -e  Check that wheels are prebuilt for this release."
  echo " -p  Build a pex from prebuilt wheels for this release."
  echo " -q  Build a pex which only works on the host platform, using the code as exists on disk."
  echo
  echo "All options (except for '-d') are mutually exclusive."

  if (($# > 0)); then
    die "$@"
  else
    exit 0
  fi
}

while getopts ":${_OPTS}" opt; do
  case ${opt} in
    h) usage ;;
    n) dry_run="true" ;;
    f)
      run_packages_script build-fs-util
      exit $?
      ;;
    t) test_release="true" ;;
    l)
      run_packages_script list-packages
      exit $?
      ;;
    o)
      run_packages_script list-owners
      exit $?
      ;;
    w)
      run_packages_script list-prebuilt-wheels
      exit $?
      ;;
    e)
      run_packages_script fetch-and-check-prebuilt-wheels
      exit $?
      ;;
    p)
      run_packages_script build-universal-pex
      exit $?
      ;;
    q)
      run_packages_script build-local-pex
      exit $?
      ;;
    *) usage "Invalid option: -${OPTARG}" ;;
  esac
done

if [[ "${dry_run}" == "true" && "${test_release}" == "true" ]]; then
  usage "The dry run and test options are mutually exclusive, pick one."
elif [[ "${dry_run}" == "true" ]]; then
  (run_packages_script dry-run-install) || die "Dry run release failed."
elif [[ "${test_release}" == "true" ]]; then
  (run_packages_script test-release) || die "Failed to install and test the latest released packages."
else
  (run_packages_script publish) || die "Failed to release packages to PyPI."
fi
