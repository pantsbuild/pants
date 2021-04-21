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

# NB: Pants core does not have the ability to change its own version, so we compute the
# suffix here and mutate the VERSION_FILE to affect the current version.
readonly VERSION_FILE="${ROOT}/src/python/pants/VERSION"
PANTS_STABLE_VERSION="$(cat "${VERSION_FILE}")"
HEAD_SHA=$(git rev-parse --verify HEAD)
# We add a non-numeric prefix 'git' before the sha in order to avoid a hex sha which happens to
# contain only [0-9] being parsed as a number -- see #7399.
# TODO(#7399): mix in the timestamp before the sha instead of 'git' to get monotonic ordering!
readonly PANTS_UNSTABLE_VERSION="${PANTS_STABLE_VERSION}+git${HEAD_SHA:0:8}"

readonly DEPLOY_DIR="${ROOT}/dist/deploy"
readonly DEPLOY_3RDPARTY_WHEELS_PATH="wheels/3rdparty/${HEAD_SHA}"
readonly DEPLOY_PANTS_WHEELS_PATH="wheels/pantsbuild.pants/${HEAD_SHA}"
readonly DEPLOY_3RDPARTY_WHEEL_DIR="${DEPLOY_DIR}/${DEPLOY_3RDPARTY_WHEELS_PATH}"
readonly DEPLOY_PANTS_WHEEL_DIR="${DEPLOY_DIR}/${DEPLOY_PANTS_WHEELS_PATH}"

function run_packages_script() {
  (
    cd "${ROOT}"
    ./pants run "${ROOT}/build-support/bin/packages.py" -- "$@"
  )
}

function safe_curl() {
  real_curl="$(command -v curl)"
  set +e
  "${real_curl}" --fail -SL "$@"
  exit_code=$?
  set -e
  if [[ "${exit_code}" -ne 0 ]]; then
    echo >&2 "Curl failed with args: $*"
    exit 1
  fi
}

# A space-separated list of pants packages to include in any pexes that are built: by default,
# only pants core is included.
: "${PANTS_PEX_PACKAGES:="pantsbuild.pants"}"

# URL from which pex release binaries can be downloaded.
: "${PEX_DOWNLOAD_PREFIX:="https://github.com/pantsbuild/pex/releases/download"}"

function requirement() {
  package="$1"
  grep "^${package}[^A-Za-z0-9]" "${ROOT}/3rdparty/python/requirements.txt" || die "Could not find requirement for ${package}"
}

function run_pex() {
  # TODO: Cache this in case we run pex multiple times
  (
    PEX_VERSION="$(requirement pex | sed -e "s|pex==||")"

    pexdir="$(mktemp -d -t build_pex.XXXXX)"
    trap 'rm -rf "${pexdir}"' EXIT

    pex="${pexdir}/pex"

    safe_curl -s "${PEX_DOWNLOAD_PREFIX}/v${PEX_VERSION}/pex" > "${pex}"
    "${PY}" "${pex}" "$@"
  )
}

function execute_pex() {
  run_pex \
    --no-build \
    --no-pypi \
    --disable-cache \
    -f "${DEPLOY_PANTS_WHEEL_DIR}/${PANTS_UNSTABLE_VERSION}" \
    -f "${DEPLOY_3RDPARTY_WHEEL_DIR}/${PANTS_UNSTABLE_VERSION}" \
    "$@"
}

function build_pex() {
  # Builds a pex from the current UNSTABLE version.
  # If $1 == "build", builds a pex just for this platform, from source.
  # If $1 == "fetch", fetches the linux and OSX wheels which were built on travis.
  local mode="$1"

  local linux_platform_noabi="linux_x86_64"
  local osx_platform_noabi="macosx_10.15_x86_64"

  case "${mode}" in
    build)
      # NB: When building locally, we explicitly target our local Py3. This will not be compatible
      # with platforms other than `current` nor will it be compatible with multiple Python versions.
      local distribution_target_flags=("--python=$(command -v "$PY")")
      local dest="${ROOT}/dist/pants.${PANTS_UNSTABLE_VERSION}.${platform}.pex"
      local stable_dest="${DEPLOY_DIR}/pex/pants.${PANTS_STABLE_VERSION}.pex"
      ;;
    fetch)
      local distribution_target_flags=()
      abis=("cp-37-m" "cp-38-cp38" "cp-39-cp39")
      for platform in "${linux_platform_noabi}" "${osx_platform_noabi}"; do
        for abi in "${abis[@]}"; do
          distribution_target_flags=("${distribution_target_flags[@]}" "--platform=${platform}-${abi}")
        done
      done
      local dest="${ROOT}/dist/pants.${PANTS_UNSTABLE_VERSION}.pex"
      local stable_dest="${DEPLOY_DIR}/pex/pants.${PANTS_STABLE_VERSION}.pex"
      ;;
    *)
      echo >&2 "Bad build_pex mode ${mode}"
      exit 1
      ;;
  esac

  rm -rf "${DEPLOY_DIR}"
  mkdir -p "${DEPLOY_DIR}"

  if [[ "${mode}" == "fetch" ]]; then
    run_packages_script fetch-and-check-prebuilt-wheels --wheels-dest "${DEPLOY_DIR}"
  else
    run_packages_script build-pants-wheels
    run-packages-script build-3rdparty-wheels
  fi

  local requirements=()
  for pkg_name in $PANTS_PEX_PACKAGES; do
    requirements=("${requirements[@]}" "${pkg_name}==${PANTS_UNSTABLE_VERSION}")
  done

  execute_pex \
    -o "${dest}" \
    --no-strip-pex-env \
    --script=pants \
    --unzip \
    "${distribution_target_flags[@]}" \
    "${requirements[@]}"

  if [[ "${PANTS_PEX_RELEASE}" == "stable" ]]; then
    mkdir -p "$(dirname "${stable_dest}")"
    cp "${dest}" "${stable_dest}"
  fi

  banner "Successfully built ${dest}"
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
      build_pex fetch
      exit $?
      ;;
    q)
      build_pex build
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
