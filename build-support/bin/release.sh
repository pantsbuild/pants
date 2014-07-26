#!/usr/bin/env bash
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

function die() {
  if (( $# > 0 )); then
    echo -e "\n$@"
  fi
  exit 1
}

ROOT=$(
  git rev-parse --show-toplevel || \
    die "Failed to find the root of this pantsbuild/pants clone"
)

function banner() {
  echo
  echo "[== $@ ==]"
  echo
}

function run_local_pants() {
  PANTS_DEV=1 ${ROOT}/pants "$@"
}

function package() {
  run_local_pants setup_py --recursive //src/python/pants:pants-packaged
}

function publish() {
  run_local_pants setup_py --run="sdist upload" --recursive //src/python/pants:pants-packaged
}

function local_version() {
  run_local_pants --version 2>/dev/null
}

function install() {
  PIP_ARGS="$@"

  VENV_DIR=$(mktemp -d -t pants.XXXXX) && \
  ${ROOT}/build-support/virtualenv $VENV_DIR && \
  source $VENV_DIR/bin/activate && \
  pip install ${PIP_ARGS} pantsbuild.pants==$(local_version) && \
  pants goal list //:: && [[ "$(pants --version 2>/dev/null)" == "$(local_version)" ]] && \
  deactivate
}

function dry_run_install() {
  package && install --find-links=file://${ROOT}/dist || die "Local dry run install failed."
}

function usage() {
  echo "Releases the pantsbuild.pants source distribution to PyPi."
  echo
  echo "With no options pants is built, smoke tested and published to"
  echo "PyPi.  Credentials are needed for this as described in the"
  echo "release docs: http://pantsbuild.github.io/jsirois/release.html"
  echo
  echo "Usage: $0 (-h|-opd)"
  echo " -h  Rrint out this help message."
  echo " -n  Performs a release dry run."
  echo "       A pants distribution will be built, installed locally in"
  echo "       an ephemeral virtualenv and exercised to validate basic"
  echo "       functioning."
  echo " -t  Tests a live release."
  echo "       Ensures the latest pants version has propagated to PyPi"
  echo "       and can be installed in an ephemeral virtualenv."
  echo
  echo "All options are mutually exclusive."

  if (( $# > 0 )); then
    die "$@"
  else
    exit 0
  fi
}

while getopts "hnt" opt; do
  case ${opt} in
    h) usage ;;
    n) dry_run="true" ;;
    t) test_release="true" ;;
    *) usage "Invalid option: -${OPTARG}" ;;
  esac
done

if [[ "${dry_run}" == "true" && "${test_release}" == "true" ]]; then
  usage "The dry run and test options are mutually exclusive, pick one."
elif [[ "${dry_run}" == "true" ]]; then
  banner "Performing a dry run pants release - no artifacts will be uploaded." && \
  (
    dry_run_install && \
    banner "Dry run release succeeded for pantsbuild.pants-$(local_version)."
  ) || die "Dry run release failed."
elif [[ "${test_release}" == "true" ]]; then
  banner "Testing the latest released pantsbuild.pants" && \
  (
    install && \
    banner "Successfully installed pantsbuild.pants-$(local_version) from PyPi."
  ) || die "Failed to install pantsbuild.pants-$(local_version) from PyPi."
else
  banner "Releasing pantsbuild.pants to PyPi." && \
  (
    dry_run_install && publish && \
    banner "Successfully released pantsbuild.pants-$(local_version) to PyPi."
  ) || die "Failed to publish pantsbuild.pants to PyPi."
fi
