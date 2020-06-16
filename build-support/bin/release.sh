#!/usr/bin/env bash
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

set -e

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd "$(git rev-parse --show-toplevel)" && pwd)

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

# shellcheck source=build-support/common.sh
source "${ROOT}/build-support/common.sh"

# TODO: make this less hacky when porting to Python 3. Use proper `--python-version` flags, like
#  those used by ci.py.
if [[ "${USE_PY37:-false}" == "true" ]]; then
  default_python=python3.7
  interpreter_constraint="==3.7.*"
elif [[ "${USE_PY38:-false}" == "true" ]]; then
  default_python=python3.8
  interpreter_constraint="==3.8.*"
else
  default_python=python3.6
  interpreter_constraint="==3.6.*"
fi

export PY="${PY:-${default_python}}"
if ! command -v "${PY}" >/dev/null; then
  die "Python interpreter ${PY} not discoverable on your PATH."
fi
py_major_minor=$(${PY} -c 'import sys; print(".".join(map(str, sys.version_info[0:2])))')
if [[ "${py_major_minor}" != "3.6"  && "${py_major_minor}" != "3.7" && "${py_major_minor}" != "3.8" ]]; then
  die "Invalid interpreter. The release script requires Python 3.6, 3.7, or 3.8 (you are using ${py_major_minor})."
fi

export PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS="['${interpreter_constraint}']"

function run_local_pants() {
  "${ROOT}/pants" "$@"
}

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

# A space-separated list of pants packages to include in any pexes that are built: by default,
# only pants core is included.
: "${PANTS_PEX_PACKAGES:="pantsbuild.pants"}"

# URL from which pex release binaries can be downloaded.
: "${PEX_DOWNLOAD_PREFIX:="https://github.com/pantsbuild/pex/releases/download"}"

# shellcheck source=contrib/release_packages.sh
source "${ROOT}/contrib/release_packages.sh"

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

function run_packages_script() {
  (
    cd "${ROOT}"
    ./v2 --concurrent run "${ROOT}/build-support/bin/packages.py" -- "$@"
  )
}

function pkg_pants_install_test() {
  local version=$1
  shift
  local PIP_ARGS=("$@")
  pip install "${PIP_ARGS[@]}" "pantsbuild.pants==${version}" || \
    die "pip install of pantsbuild.pants failed!"
  execute_packaged_pants_with_internal_backends list src:: || \
    die "'pants list src::' failed in venv!"
  [[ "$(execute_packaged_pants_with_internal_backends --version 2>/dev/null)" \
     == "${version}" ]] || die "Installed version of pants does not match requested version!"
}

function pkg_testutil_install_test() {
  local version=$1
  shift
  local PIP_ARGS=("$@")
  pip install "${PIP_ARGS[@]}" "pantsbuild.pants.testutil==${version}" && \
  python -c "import pants.testutil"
}

#
# End of package declarations.
#

REQUIREMENTS_3RDPARTY_FILES=(
  "3rdparty/python/requirements.txt"
  "3rdparty/python/twitter/commons/requirements.txt"
)

# When we do (dry-run) testing, we need to run the packaged pants.
# It doesn't have internal backend plugins so when we execute it
# at the repo build root, the root pants.toml will ask it to load
# internal backend packages and their dependencies which it doesn't have,
# and it'll fail. To solve that problem, we load the internal backend package
# dependencies into the pantsbuild.pants venv.
#
# TODO: Starting and stopping pantsd repeatedly here works fine, but because the
# created venvs are located within the buildroot, pantsd will fingerprint them on
# startup. Production usecases should generally not experience this cost, because
# either pexes or venvs (as created by the `pants` script that we distribute) are
# created outside of the buildroot.
function execute_packaged_pants_with_internal_backends() {
  pip install --ignore-installed \
    -r pants-plugins/3rdparty/python/requirements.txt &> /dev/null && \
  pants \
    --no-verify-config \
    --no-pantsd \
    --pythonpath="['pants-plugins/src/python']" \
    --backend-packages="[\
        'pants.backend.codegen',\
        'pants.backend.docgen',\
        'pants.backend.graph_info',\
        'pants.backend.jvm',\
        'pants.backend.native',\
        'pants.backend.project_info',\
        'pants.backend.python',\
        'pants.cache',\
        'internal_backend.repositories',\
        'internal_backend.sitegen',\
        'internal_backend.utilities',\
      ]" \
      --backend-packages2="[\
        'pants.backend.awslambda.python',\
        'pants.backend.python',\
        'pants.backend.project_info',\
      ]" \
    "$@"
}

function build_3rdparty_packages() {
  # Builds whls for 3rdparty dependencies of pants.
  local version=$1

  mkdir -p "${DEPLOY_3RDPARTY_WHEEL_DIR}/${version}"

  local req_args=()
  for req_file in "${REQUIREMENTS_3RDPARTY_FILES[@]}"; do
    req_args=("${req_args[@]}" -r "${ROOT}/$req_file")
  done

  start_travis_section "3rdparty" "Building 3rdparty whls from ${REQUIREMENTS_3RDPARTY_FILES[*]}"
  activate_tmp_venv

  pip wheel --wheel-dir="${DEPLOY_3RDPARTY_WHEEL_DIR}/${version}" "${req_args[@]}"

  deactivate
  end_travis_section
}

function activate_tmp_venv() {
  # Because the venv/bin/activate script's location is dynamic and not located in a fixed
  # place, Shellcheck will not be able to find it so we tell Shellcheck to ignore the file.
  # shellcheck source=/dev/null
  VENV_DIR=$(mktemp -d -t pants.XXXXX) && \
  "${ROOT}/build-support/virtualenv" "$VENV_DIR" && \
  source "$VENV_DIR/bin/activate"
}

function pre_install() {
  start_travis_section "SetupVenv" "Setting up virtualenv"
  activate_tmp_venv
  end_travis_section
}

function post_install() {
  # this assume pre_install is called and a new temp venv activation has been done.
  if [[ "${pause_after_venv_creation}" == "true" ]]; then
    cat <<EOM

If you want to poke around with the new version of pants that has been built
and installed in a temporary virtualenv, fire up another shell window and type:

  source ${VENV_DIR}/bin/activate
  cd ${ROOT}

From there, you can run 'pants' (not './pants') to do some testing.

When you're done testing, press enter to continue.
EOM
    read -r
  fi
  deactivate
}

function install_and_test_packages() {
  local VERSION=$1
  shift
  local PIP_ARGS=(
    "${VERSION}"
    "$@"
    --quiet
    # Prefer remote or `--find-links` packages to cache contents.
    --no-cache-dir
  )

  export PANTS_PYTHON_REPOS_REPOS="${DEPLOY_PANTS_WHEEL_DIR}/${VERSION}"

  start_travis_section "wheel_check" "Validating ${VERSION} pantsbuild.pants wheels"
  activate_twine
  twine check "${PANTS_PYTHON_REPOS_REPOS}"/*.whl || die "Failed to validate wheels."
  deactivate
  end_travis_section

  pre_install || die "Failed to setup virtualenv while testing ${NAME}-${VERSION}!"

  # Avoid caching plugin installs.
  PANTS_PLUGIN_CACHE_DIR=$(mktemp -d -t plugins_cache.XXXXX)
  export PANTS_PLUGIN_CACHE_DIR
  trap 'rm -rf "${PANTS_PLUGIN_CACHE_DIR}"' EXIT

  # WONTFIX: fixing the array expansion is too difficult to be worth it. See https://github.com/koalaman/shellcheck/wiki/SC2207.
  # shellcheck disable=SC2207
  packages=(
    $(run_packages_script list-packages | grep '.' | awk '{print $1}')
  ) || die "Failed to list packages!"

  for package in "${packages[@]}"
  do
    start_travis_section "${package}" "Installing and testing package ${package}-${VERSION}"
    # shellcheck disable=SC2086
    eval pkg_${package##*\.}_install_test "${PIP_ARGS[@]}" || \
      die "Failed to install and test package ${package}-${VERSION}!"
    end_travis_section
  done
  unset PANTS_PYTHON_REPOS_REPOS

  post_install || die "Failed to deactivate virtual env while testing ${NAME}-${VERSION}!"
}

function dry_run_install() {
  # Build a complete set of whls, and then ensure that we can install pants using only whls.
  local VERSION="${PANTS_UNSTABLE_VERSION}"
  run_packages_script build-pants-wheels && \
  build_3rdparty_packages "${VERSION}" && \
  install_and_test_packages "${VERSION}" \
    --only-binary=:all: \
    -f "${DEPLOY_3RDPARTY_WHEEL_DIR}/${VERSION}" -f "${DEPLOY_PANTS_WHEEL_DIR}/${VERSION}"
}

function get_pgp_keyid() {
  git config --get user.signingkey
}

function get_pgp_program() {
  git config --get gpg.program || echo "gpg"
}

function reversion_whls() {
  # Reversions all whls from an input directory to an output directory.
  # Adds one pants-specific glob to match the `VERSION` file in `pantsbuild.pants`.
  local src_dir=$1
  local dest_dir=$2
  local output_version=$3

  for whl in "${src_dir}"/*.whl; do
    run_local_pants -q run src/python/pants/releases:reversion -- \
      --glob='pants/VERSION' \
      "${whl}" "${dest_dir}" "${output_version}" \
      || die "Could not reversion whl ${whl} to ${output_version}"
  done
}

function adjust_wheel_platform() {
  # Renames wheels to adjust their tag from a src platform to a dst platform.
  local src_plat="$1"
  local dst_plat="$2"
  local dir="$3"
  find "$dir" -type f -name "*${src_plat}.whl" | while read -r src_whl; do
    local dst_whl=${src_whl/$src_plat/$dst_plat}
    mv -f "${src_whl}" "${dst_whl}"
  done
}

function activate_twine() {
  local -r venv_dir="${ROOT}/build-support/twine-deps.venv"

  rm -rf "${venv_dir}"
  "${ROOT}/build-support/virtualenv" "${venv_dir}"
  # Because the venv/bin/activate script's location is dynamic and not located in a fixed
  # place, Shellcheck will not be able to find it so we tell Shellcheck to ignore the file.
  # shellcheck source=/dev/null
  source "${venv_dir}/bin/activate"
  pip install twine
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
  local osx_platform_noabi="macosx_10.11_x86_64"

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
      abis=("cp-36-m" "cp-37-m" "cp-38-cp38")
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
    build_3rdparty_packages "${PANTS_UNSTABLE_VERSION}"
  fi

  local requirements=()
  for pkg_name in $PANTS_PEX_PACKAGES; do
    requirements=("${requirements[@]}" "${pkg_name}==${PANTS_UNSTABLE_VERSION}")
  done

  # Pants depends on twitter.common libraries that trigger pex warnings for not properly declaring
  # their dependency on setuptools (for namespace package support). To prevent these known warnings
  # from polluting stderr we pass `--no-emit-warnings`.
  execute_pex \
    -o "${dest}" \
    --no-emit-warnings \
    --no-strip-pex-env \
    --script=pants \
    "${distribution_target_flags[@]}" \
    "${requirements[@]}"

  if [[ "${PANTS_PEX_RELEASE}" == "stable" ]]; then
    mkdir -p "$(dirname "${stable_dest}")"
    cp "${dest}" "${stable_dest}"
  fi

  banner "Successfully built ${dest}"
}

function publish_packages() {
  rm -rf "${DEPLOY_PANTS_WHEEL_DIR}"
  mkdir -p "${DEPLOY_PANTS_WHEEL_DIR}/${PANTS_STABLE_VERSION}"

  start_travis_section "Publishing" "Publishing packages for ${PANTS_STABLE_VERSION}"

  # Fetch unstable wheels, rename any linux whls to manylinux, and reversion them
  # from PANTS_UNSTABLE_VERSION to PANTS_STABLE_VERSION
  run_packages_script fetch-and-check-prebuilt-wheels --wheels-dest "${DEPLOY_DIR}"
  # See https://www.python.org/dev/peps/pep-0599/. We build on Centos7 so use manylinux2014.
  adjust_wheel_platform "linux_x86_64" "manylinux2014_x86_64" \
    "${DEPLOY_PANTS_WHEEL_DIR}/${PANTS_UNSTABLE_VERSION}"
  reversion_whls \
    "${DEPLOY_PANTS_WHEEL_DIR}/${PANTS_UNSTABLE_VERSION}" \
    "${DEPLOY_PANTS_WHEEL_DIR}/${PANTS_STABLE_VERSION}" \
    "${PANTS_STABLE_VERSION}"

  activate_twine
  trap deactivate RETURN

  twine upload --sign "--sign-with=$(get_pgp_program)" "--identity=$(get_pgp_keyid)" \
    "${DEPLOY_PANTS_WHEEL_DIR}/${PANTS_STABLE_VERSION}"/*.whl

  end_travis_section
}

_OPTS="dhnftlowepq"

function usage() {
  echo "With no options all packages are built, smoke tested and published to"
  echo "PyPI.  Credentials are needed for this as described in the"
  echo "release docs: http://pantsbuild.org/release.html"
  echo
  echo "Usage: $0 [-d] (-h|-n|-f|-t|-l|-o|-w|-e|-p|-q)"
  echo " -d  Enables debug mode (verbose output, script pauses after venv creation)"
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

  if (( $# > 0 )); then
    die "$@"
  else
    exit 0
  fi
}

while getopts ":${_OPTS}" opt; do
  case ${opt} in
    h) usage ;;
    d) debug="true" ;;
    n) dry_run="true" ;;
    f) run_packages_script build-fs-util ; exit $? ;;
    t) test_release="true" ;;
    l) run_packages_script list-packages ; exit $? ;;
    o) run_packages_script list-owners ; exit $? ;;
    w) run_packages_script list-prebuilt-wheels ; exit $? ;;
    e) run_packages_script fetch-and-check-prebuilt-wheels ; exit $? ;;
    p) build_pex fetch ; exit $? ;;
    q) build_pex build ; exit $? ;;
    *) usage "Invalid option: -${OPTARG}" ;;
  esac
done

if [[ "${debug}" == "true" ]]; then
  set -x
  pause_after_venv_creation="true"
fi

if [[ "${dry_run}" == "true" && "${test_release}" == "true" ]]; then
  usage "The dry run and test options are mutually exclusive, pick one."
elif [[ "${dry_run}" == "true" ]]; then
  banner "Performing a dry run release"
  (
    dry_run_install && \
    banner "Dry run release succeeded"
  ) || die "Dry run release failed."
elif [[ "${test_release}" == "true" ]]; then
  banner "Installing and testing the latest released packages"
  (
    install_and_test_packages "${PANTS_STABLE_VERSION}" && \
    banner "Successfully installed and tested the latest released packages"
  ) || die "Failed to install and test the latest released packages."
else
  banner "Releasing packages to PyPI"
  (
    run_packages_script check-release-prereqs && publish_packages && \
    run_packages_script post-publish && banner "Successfully released packages to PyPI"
  ) || die "Failed to release packages to PyPI."
fi
