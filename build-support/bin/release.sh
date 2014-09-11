#!/usr/bin/env bash
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


#
# List of packages to be released
#
# Each package definition is of form:
#
# PKG_<NAME>=(
#   "package.name"
#   "build.target"
#   "pkg_<name>_install_test"
# )
# function pkg_<name>_install_test() {
#   ...
# }
#
PKG_PANTS=(
  "pantsbuild.pants"
  "//src/python/pants:pants-packaged"
  "pkg_pants_install_test"
  )
function pkg_pants_install_test() {
  PIP_ARGS="$@"
  pip install ${PIP_ARGS} pantsbuild.pants==$(local_version) && \
  pants goal list //:: && [[ "$(pants --version 2>/dev/null)" == "$(local_version)" ]]
}

PKG_PANTS_TESTINFRA=(
  "pantsbuild.pants.testinfra"
  "//src/python/pants:test_infra"
  "pkg_pants_testinfra_install_test"
  )
function pkg_pants_testinfra_install_test() {
  PIP_ARGS="$@"
  pip install ${PIP_ARGS} pantsbuild.pants.testinfra==$(local_version) \
    --allow-external antlr-python-runtime --allow-unverified antlr-python-runtime && \
  python -c "import pants_test"
}

# Once individual (new) package is declared above, insert it into the array below)
RELEASE_PACKAGES=(PKG_PANTS PKG_PANTS_TESTINFRA)
#
# End of package declarations.
#


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

function pkg_name() {
  PACKAGE=$1
  eval NAME=\${$PACKAGE[0]}
  echo ${NAME}
}

function pkg_build_target() {
  PACKAGE=$1
  eval TARGET=\${$PACKAGE[1]}
  echo ${TARGET}
}

function pkg_install_test_func() {
  PACKAGE=$1
  eval INSTALL_TEST_FUNC=\${$PACKAGE[2]}
  echo ${INSTALL_TEST_FUNC}
}

function local_version() {
  run_local_pants --version 2>/dev/null
}

function build_packages() {
  for PACKAGE in "${RELEASE_PACKAGES[@]}"
  do
    NAME=$(pkg_name $PACKAGE)
    BUILD_TARGET=$(pkg_build_target $PACKAGE)

    banner "Building package ${NAME}-$(local_version) with target '${BUILD_TARGET}' ..."

    run_local_pants setup_py --recursive ${BUILD_TARGET} || \
    die "Failed to build package ${NAME}-$(local_version) with target '${BUILD_TARGET}'!"
  done
}

function publish_packages() {
  for PACKAGE in "${RELEASE_PACKAGES[@]}"
  do
    NAME=$(pkg_name $PACKAGE)
    BUILD_TARGET=$(pkg_build_target $PACKAGE)

    banner "Publishing package ${NAME}-$(local_version) with target '${BUILD_TARGET}' ..."

    # TODO(Jin Feng) Note --recursive option would cause some of the packages being
    # uploaded multiple times because of dependencies. No harms, but not efficient.
    run_local_pants setup_py --run="sdist upload" --recursive ${BUILD_TARGET} || \
    die "Failed to publish package ${NAME}-$(local_version) with target '${BUILD_TARGET}'!"
  done
}

function pre_install() {
  VENV_DIR=$(mktemp -d -t pants.XXXXX) && \
  ${ROOT}/build-support/virtualenv $VENV_DIR && \
  source $VENV_DIR/bin/activate
}

function post_install() {
  # this assume pre_install is called and a new temp venv activation has been done.
  deactivate
}

function install_and_test_packages() {
  PIP_ARGS="$@"

  for PACKAGE in "${RELEASE_PACKAGES[@]}"
  do
    NAME=$(pkg_name $PACKAGE)
    INSTALL_TEST_FUNC=$(pkg_install_test_func $PACKAGE)

    banner "Installing and testing package ${NAME}-$(local_version) ..."

    pre_install && \
    eval $INSTALL_TEST_FUNC $PIP_ARGS && \
    post_install || \
    die "Failed to install and test package ${NAME}-$(local_version)!"
  done
}

function dry_run_install() {
  build_packages && \
  install_and_test_packages --find-links=file://${ROOT}/dist
}

function usage() {
  echo "Releases the following source distributions to PyPi."
  for PACKAGE in "${RELEASE_PACKAGES[@]}"
  do
    NAME=$(pkg_name $PACKAGE)
    echo "    ${NAME}-$(local_version)"
  done
  echo
  echo "With no options all packages are built, smoke tested and published to"
  echo "PyPi.  Credentials are needed for this as described in the"
  echo "release docs: http://pantsbuild.github.io/release.html"
  echo
  echo "Usage: $0 (-h|-opd)"
  echo " -h  Prints out this help message."
  echo " -n  Performs a release dry run."
  echo "       All package distributions will be built, installed locally in"
  echo "       an ephemeral virtualenv and exercised to validate basic"
  echo "       functioning."
  echo " -t  Tests a live release."
  echo "       Ensures the latest packages have been propagated to PyPi"
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
  banner "Performing a dry run release - no artifacts will be uploaded." && \
  (
    dry_run_install && \
    banner "Dry run release succeeded."
  ) || die "Dry run release failed."
elif [[ "${test_release}" == "true" ]]; then
  banner "Installing and testing the latest released packages." && \
  (
    install_and_test_packages && \
    banner "Successfully installed and tested the latest released packages."
  ) || die "Failed to install and test the latest released packages."
else
  banner "Releasing packages to PyPi." && \
  (
    dry_run_install && publish_packages && \
    banner "Successfully released packages to PyPi."
  ) || die "Failed to release packages to PyPi."
fi
