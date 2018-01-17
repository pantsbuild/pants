#!/usr/bin/env bash
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd "$(git rev-parse --show-toplevel)" && pwd)
source ${ROOT}/build-support/common.sh

PY=$(which python2.7)
[[ -n "${PY}" ]] || die "You must have python2.7 installed and on the path to release."
export PY

function run_local_pants() {
  ${ROOT}/pants "$@"
}

# NB: Pants core does not have the ability to change its own version, so we compute the
# suffix here and mutate the VERSION_FILE to affect the current version.
readonly HEAD_SHA=$(git rev-parse --verify HEAD)
readonly PANTS_STABLE_VERSION="$(run_local_pants --version 2>/dev/null)"
readonly PANTS_UNSTABLE_VERSION="${PANTS_STABLE_VERSION}+${HEAD_SHA:0:8}"

readonly DEPLOY_DIR="${ROOT}/dist/deploy"
readonly DEPLOY_3RDPARTY_WHEELS_PATH="wheels/3rdparty/${HEAD_SHA}"
readonly DEPLOY_PANTS_WHEELS_PATH="wheels/pantsbuild.pants/${HEAD_SHA}"
readonly DEPLOY_PANTS_SDIST_PATH="sdists/pantsbuild.pants/${HEAD_SHA}"
readonly DEPLOY_3RDPARTY_WHEEL_DIR="${DEPLOY_DIR}/${DEPLOY_3RDPARTY_WHEELS_PATH}"
readonly DEPLOY_PANTS_WHEEL_DIR="${DEPLOY_DIR}/${DEPLOY_PANTS_WHEELS_PATH}"
readonly DEPLOY_PANTS_SDIST_DIR="${DEPLOY_DIR}/${DEPLOY_PANTS_SDIST_PATH}"

readonly VERSION_FILE="${ROOT}/src/python/pants/VERSION"

# A space-separated list of pants packages to include in any pexes that are built: by default,
# only pants core is included.
: ${PANTS_PEX_PACKAGES:="pantsbuild.pants"}

source ${ROOT}/contrib/release_packages.sh

source "${ROOT}/build-support/bin/native/bootstrap.sh"

function find_pkg() {
  local readonly pkg_name=$1
  local readonly version=$2
  local readonly search_dir=$3
  find "${search_dir}" -type f -name "${pkg_name}-${version}-*.whl"
}

function find_plat_name() {
  # See: https://www.python.org/dev/peps/pep-0425/#id13
  "${PY}" << EOF
from __future__ import print_function
from distutils.util import get_platform

print(get_platform().replace('-', '_').replace('.', '_'))
EOF
}

#
# List of packages to be released
#
# See build-support/README.md for more information on the format of each
# `PKG_$NAME` definition.
#
PKG_PANTS=(
  "pantsbuild.pants"
  "//src/python/pants:pants-packaged"
  "pkg_pants_install_test"
  "--python-tag cp27 --plat-name $(find_plat_name)"
)
function pkg_pants_install_test() {
  local version=$1
  shift
  local PIP_ARGS="$@"
  pip install ${PIP_ARGS} "pantsbuild.pants==${version}" || \
    die "pip install of pantsbuild.pants failed!"
  execute_packaged_pants_with_internal_backends list src:: || \
    die "'pants list src::' failed in venv!"
  [[ "$(execute_packaged_pants_with_internal_backends --version 2>/dev/null)" \
     == "${version}" ]] || die "Installed version of pants does match requested version!"
}

PKG_PANTS_TESTINFRA=(
  "pantsbuild.pants.testinfra"
  "//tests/python/pants_test:test_infra"
  "pkg_pants_testinfra_install_test"
)
function pkg_pants_testinfra_install_test() {
  local version=$1
  shift
  local PIP_ARGS="$@"
  pip install ${PIP_ARGS} "pantsbuild.pants.testinfra==${version}" && \
  python -c "import pants_test"
}

# Once an individual (new) package is declared above, insert it into the array below)
CORE_PACKAGES=(
  PKG_PANTS
  PKG_PANTS_TESTINFRA
)
RELEASE_PACKAGES=(
  ${CORE_PACKAGES[*]}
  ${CONTRIB_PACKAGES[*]}
)

#
# End of package declarations.
#

REQUIREMENTS_3RDPARTY_FILES=(
  "3rdparty/python/requirements.txt"
  "3rdparty/python/twitter/commons/requirements.txt"
)

# When we do (dry-run) testing, we need to run the packaged pants.
# It doesn't have internal backend plugins so when we execute it
# at the repo build root, the root pants.ini will ask it to load
# internal backend packages and their dependencies which it doesn't have,
# and it'll fail. To solve that problem, we load the internal backend package
# dependencies into the pantsbuild.pants venv.
function execute_packaged_pants_with_internal_backends() {
  pip install --ignore-installed \
    -r pants-plugins/3rdparty/python/requirements.txt &> /dev/null && \
  pants \
    --no-verify-config \
    --pythonpath="['pants-plugins/src/python']" \
    --backend-packages="[\
        'pants.backend.codegen',\
        'pants.backend.docgen',\
        'pants.backend.graph_info',\
        'pants.backend.jvm',\
        'pants.backend.project_info',\
        'pants.backend.python',\
        'internal_backend.repositories',\
        'internal_backend.sitegen',\
        'internal_backend.utilities',\
      ]" \
    "$@"
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

function bdist_wheel_flags() {
  PACKAGE=$1
  eval BDIST_WHEEL_FLAGS=\${$PACKAGE[3]}
    echo ${BDIST_WHEEL_FLAGS}
}

function pants_version_reset() {
  pushd ${ROOT} > /dev/null
    git checkout -- ${VERSION_FILE}
  popd > /dev/null
}

function pants_version_set() {
  # Mutates `src/python/pants/VERSION` to temporarily override it. Sets a `trap` to restore to
  # HEAD on exit.
  local version=$1
  trap pants_version_reset EXIT
  echo "${version}" > "${VERSION_FILE}"
}

function build_3rdparty_packages() {
  # Builds whls for 3rdparty dependencies of pants.
  local version=$1

  rm -rf "${DEPLOY_3RDPARTY_WHEEL_DIR}"
  mkdir -p "${DEPLOY_3RDPARTY_WHEEL_DIR}/${version}"

  local req_args=""
  for req_file in "${REQUIREMENTS_3RDPARTY_FILES[@]}"; do
    req_args="${req_args} -r ${ROOT}/$req_file"
  done

  start_travis_section "3rdparty" "Building 3rdparty whls from ${REQUIREMENTS_3RDPARTY_FILES[@]}"
  activate_tmp_venv

  pip wheel --wheel-dir="${DEPLOY_3RDPARTY_WHEEL_DIR}/${version}" ${req_args}

  deactivate
  end_travis_section
}

function build_pants_packages() {
  # TODO(John Sirois): Remove sdist generation and twine upload when
  # https://github.com/pantsbuild/pants/issues/4956 is resolved.
  local version=$1

  rm -rf "${DEPLOY_PANTS_WHEEL_DIR}" "${DEPLOY_PANTS_SDIST_DIR}"
  mkdir -p "${DEPLOY_PANTS_WHEEL_DIR}/${version}" "${DEPLOY_PANTS_SDIST_DIR}/${version}"

  pants_version_set "${version}"
  for PACKAGE in "${RELEASE_PACKAGES[@]}"
  do
    NAME=$(pkg_name $PACKAGE)
    BUILD_TARGET=$(pkg_build_target $PACKAGE)
    BDIST_WHEEL_FLAGS=$(bdist_wheel_flags $PACKAGE)

    start_travis_section "${NAME}" "Building package ${NAME}-${version} with target '${BUILD_TARGET}'"
    (
      run_local_pants setup-py \
        --run="sdist bdist_wheel ${BDIST_WHEEL_FLAGS:---python-tag py27}" \
          ${BUILD_TARGET} && \
      wheel=$(find_pkg ${NAME} ${version} "${ROOT}/dist") && \
      cp -p "${wheel}" "${DEPLOY_PANTS_WHEEL_DIR}/${version}" && \
      cp -p "${ROOT}/dist/${NAME}-${version}/dist/${NAME}-${version}.tar.gz" "${DEPLOY_PANTS_SDIST_DIR}/${version}"
    ) || die "Failed to build package ${NAME}-${version} with target '${BUILD_TARGET}'!"
    end_travis_section
  done

  start_travis_section "fs_util" "Building fs_util binary"
  # fs_util is a standalone tool which can be used to inspect and manipulate
  # Pants's engine's file store, and interact with content addressable storage
  # services which implement the Bazel remote execution API.
  # It is a useful standalone tool which people may want to consume, for
  # instance when debugging pants issues, or if they're implementing a remote
  # execution API. Accordingly, we include it in our releases.
  (
    set -e
    RUST_BACKTRACE=1 PANTS_SRCPATH="${ROOT}/src/python" run_cargo build --release --manifest-path="${ROOT}/src/rust/engine/fs/fs_util/Cargo.toml"
    dst_dir="${DEPLOY_DIR}/bin/fs_util/$("${ROOT}/build-support/bin/get_os.sh")/${version}"
    mkdir -p "${dst_dir}"
    cp "${ROOT}/src/rust/engine/fs/fs_util/target/release/fs_util" "${dst_dir}/"
  ) || die "Failed to build fs_util"
  end_travis_section

  pants_version_reset
}

function activate_tmp_venv() {
  VENV_DIR=$(mktemp -d -t pants.XXXXX) && \
  ${ROOT}/build-support/virtualenv $VENV_DIR && \
  source $VENV_DIR/bin/activate
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
    read
  fi
  deactivate
}

function install_and_test_packages() {
  local VERSION=$1
  shift 2
  local PIP_ARGS=(
    "${VERSION}"
    "$@"
    --quiet
    # Prefer remote or `--find-links` packages to cache contents.
    --no-cache-dir
  )

  pre_install || die "Failed to setup virtualenv while testing ${NAME}-${VERSION}!"

  # Avoid caching plugin installs.
  export PANTS_PLUGIN_CACHE_DIR=$(mktemp -d -t plugins_cache.XXXXX)
  trap "rm -rf ${PANTS_PLUGIN_CACHE_DIR}" EXIT

  PACKAGES=("${RELEASE_PACKAGES[@]}")

  export PANTS_PYTHON_REPOS_REPOS="${DEPLOY_PANTS_WHEEL_DIR}/${VERSION}"
  for PACKAGE in "${PACKAGES[@]}"
  do
    NAME=$(pkg_name $PACKAGE)
    INSTALL_TEST_FUNC=$(pkg_install_test_func $PACKAGE)

    start_travis_section "${NAME}" "Installing and testing package ${NAME}-${VERSION}"
    eval $INSTALL_TEST_FUNC ${PIP_ARGS[@]} || \
      die "Failed to install and test package ${NAME}-${VERSION}!"
    end_travis_section
  done
  unset PANTS_PYTHON_REPOS_REPOS

  post_install || die "Failed to deactivate virtual env while testing ${NAME}-${VERSION}!"
}

function dry_run_install() {
  # Build a complete set of whls, and then ensure that we can install pants using only whls.
  local VERSION="${PANTS_UNSTABLE_VERSION}"
  build_pants_packages "${VERSION}" && \
  build_3rdparty_packages "${VERSION}" && \
  install_and_test_packages "${VERSION}" \
    --only-binary=:all: \
    -f "${DEPLOY_3RDPARTY_WHEEL_DIR}/${VERSION}" -f "${DEPLOY_PANTS_WHEEL_DIR}/${VERSION}"
}

ALLOWED_ORIGIN_URLS=(
  git@github.com:pantsbuild/pants.git
  https://github.com/pantsbuild/pants.git
)

function check_origin() {
  banner "Checking for a valid git origin"

  origin_url="$(git remote -v | grep origin | grep "\(push\)" | cut -f2 | cut -d' ' -f1)"
  for url in "${ALLOWED_ORIGIN_URLS[@]}"
  do
    if [[ "${origin_url}" == "${url}" ]]
    then
      return
    fi
  done
  msg=$(cat << EOM
Your origin url is not valid for releasing:
  ${origin_url}

It must be one of:
$(echo "${ALLOWED_ORIGIN_URLS[@]}" | tr ' ' '\n' | sed -E "s|^|  |")
EOM
)
  die "$msg"
}

function get_branch() {
  git branch | grep -E '^\* ' | cut -d' ' -f2-
}

function check_clean_branch() {
  banner "Checking for a clean branch"

  pattern="^(master)|([0-9]+\.[0-9]+\.x)$"
  branch=$(get_branch)
  [[ -z "$(git status --porcelain)" &&
     $branch =~ $pattern
  ]] || die "You are not on a clean branch."
}

function check_pgp() {
  banner "Checking pgp setup"

  msg=$(cat << EOM
You must configure your release signing pgp key.

You can configure the key by running:
  git config --add user.signingkey [key id]

Key id should be the id of the pgp key you have registered with pypi.
EOM
)
  get_pgp_keyid &> /dev/null || die "${msg}"
  echo "Found the following key for release signing:"
  gpg -k $(get_pgp_keyid)
  read -p "Is this the correct key? [Yn]: " answer
  [[ "${answer:-y}" =~ [Yy]([Ee][Ss])? ]] || die "${msg}"
}

function get_pgp_keyid() {
  git config --get user.signingkey
}

function check_pypi() {
  if [[ ! -r ~/.pypirc ]]
  then
    msg=$(cat << EOM
You must create a ~/.pypirc file with your pypi credentials:
cat << EOF > ~/.pypirc && chmod 600 ~/.pypirc
[server-login]
username: <fill me in>
password: <fill me in>
EOF

More information is here: https://wiki.python.org/moin/EnhancedPyPI
EOM
)
    die "${msg}"
  fi
  "${PY}" << EOF || die
from __future__ import print_function

import os
import sys
from ConfigParser import ConfigParser

config = ConfigParser()
config.read(os.path.expanduser('~/.pypirc'))

def check_option(section, option):
  if config.has_option(section, option):
    return config.get(section, option)
  print('Your ~/.pypirc must define a {} option in the {} section'.format(option, section))

username = check_option('server-login', 'username')
if not (username or check_option('server-login', 'password')):
  sys.exit(1)
else:
  print(username)
EOF
}

function tag_release() {
  release_version="${PANTS_STABLE_VERSION}" && \
  tag_name="release_${release_version}" && \
  git tag -f \
    --local-user=$(get_pgp_keyid) \
    -m "pantsbuild.pants release ${release_version}" \
    ${tag_name} && \
  git push -f git@github.com:pantsbuild/pants.git ${tag_name}
}

function publish_docs_if_master() {
  branch=$(get_branch)
  if [[ "${branch}" == "master" ]]; then
    ${ROOT}/build-support/bin/publish_docs.sh -p -y
  else
    echo "Skipping docsite publishing on non-master branch (${branch})."
  fi
}

function list_packages() {
  echo "Releases the following source distributions to PyPi."
  version="${PANTS_STABLE_VERSION}"
  for PACKAGE in "${RELEASE_PACKAGES[@]}"
  do
    echo "  $(pkg_name $PACKAGE)-${version}"
  done
}

function package_exists() {
  package_name="$1"

  curl --fail --head https://pypi.python.org/pypi/${package_name} &>/dev/null
}

function get_owners() {
  package_name="$1"

  latest_package_path=$(
    curl -s https://pypi.python.org/pypi/${package_name} | \
        grep -oE  "/pypi/${package_name}/[0-9]+\.[0-9]+\.[0-9]+([-.]?(rc|dev)[0-9]+)?" | head -n1
  )
  curl -s "https://pypi.python.org${latest_package_path}" | \
    grep -A1 "Owner" | tail -1 | \
    cut -d'>' -f2 | cut -d'<' -f1 | \
    tr ',' ' ' | sed -E -e "s|[[:space:]]+| |g"
}

function list_owners() {
  for PACKAGE in "${RELEASE_PACKAGES[@]}"
  do
    package_name=$(pkg_name $PACKAGE)
    if package_exists ${package_name}
    then
      echo "Owners of ${package_name}:"
      owners=($(get_owners ${package_name}))
      for owner in "${owners[@]}"
      do
        echo "  ${owner}"
      done
    else
      echo "The ${package_name} package is new!  There are no owners yet."
    fi
    echo
  done
}

function check_owner() {
  username=$(echo "$1" | tr '[:upper:]' '[:lower:]')
  package_name="$2"

  for owner in $(get_owners ${package_name})
  do
    # NB: A case-insensitive comparison is done since pypi is case-insensitive wrt usernames.
    owner=$(echo "${owner}" | tr '[:upper:]' '[:lower:]')
    if [[ "${username}" == "${owner}" ]]
    then
      return 0
    fi
  done
  return 1
}

function check_owners() {
  username="$(check_pypi)"

  total=${#RELEASE_PACKAGES[@]}
  banner "Checking package ownership for pypi user ${username} of ${total} packages"
  dont_own=()
  index=0
  for PACKAGE in "${RELEASE_PACKAGES[@]}"
  do
    index=$((index+1))
    package_name="$(pkg_name $PACKAGE)"
    banner "[${index}/${total}] checking that ${username} owns ${package_name}"
    if package_exists ${package_name}
    then
      if ! check_owner "${username}" "${package_name}"
      then
        dont_own+=("${package_name}")
      fi
    else
      echo "The ${package_name} package is new!  There are no owners yet."
    fi
  done

  if (( ${#dont_own[@]} > 0 ))
  then
    msg=$(cat << EOM
Your pypi account ${username} needs to be added as an owner for the
following packages:
$(echo "${dont_own[@]}" | tr ' ' '\n' | sed -E "s|^|  |")
EOM
)
    die "${msg}"
  fi
}

function reversion_whls() {
  # Reversions all whls from an input directory to an output directory.
  # Adds one pants-specific glob to match the `VERSION` file in `pantsbuild.pants`.
  local src_dir=$1
  local dest_dir=$2
  local output_version=$3

  for whl in `ls -1 "${src_dir}"/*.whl`; do
    run_local_pants -q run src/python/pants/releases:reversion -- \
      --glob='pants/VERSION' \
      "${whl}" "${dest_dir}" "${output_version}" \
      || die "Could not reversion whl ${whl} to ${output_version}"
  done
}

readonly BINARY_BASE_URL=https://binaries.pantsbuild.org

function list_prebuilt_wheels() {
  # List prebuilt wheels as tab-separated tuples of filename and URL-encoded name.
  wheel_listing="$(mktemp -t pants.wheels.XXXXX)"
  trap "rm -f ${wheel_listing}" RETURN

  for wheels_path in "${DEPLOY_PANTS_WHEELS_PATH}" "${DEPLOY_3RDPARTY_WHEELS_PATH}"; do
    curl -sSL "${BINARY_BASE_URL}/?prefix=${wheels_path}" > "${wheel_listing}"
    "${PY}" << EOF
from __future__ import print_function
import sys
import urllib
import xml.etree.ElementTree as ET
root = ET.parse("${wheel_listing}")
ns = {'s3': 'http://s3.amazonaws.com/doc/2006-03-01/'}
for key in root.findall('s3:Contents/s3:Key', ns):
  # Because filenames may contain characters that have different meanings
  # in URLs (namely '+'), # print the key both as url-encoded and as a file path.
  print('{}\t{}'.format(key.text, urllib.quote_plus(key.text)))
EOF
 done
}

function fetch_prebuilt_wheels() {
  local readonly to_dir="$1"

  banner "Fetching prebuilt wheels for ${PANTS_UNSTABLE_VERSION}"
  (
    cd "${to_dir}"
    list_prebuilt_wheels | {
      while read path_tuple
      do
        local file_path=$(echo "$path_tuple" | awk -F'\t' '{print $1}')
        local url_path=$(echo "$path_tuple" | awk -F'\t' '{print $2}')
        echo "${BINARY_BASE_URL}/${url_path}:"
        local dest="${to_dir}/${file_path}"
        mkdir -p "$(dirname "${dest}")"
        curl --fail --progress-bar -o "${dest}" "${BINARY_BASE_URL}/${url_path}" \
          || die "Could not fetch ${dest}."
      done
    }
  )
}

function fetch_and_check_prebuilt_wheels() {
  # Fetches wheels from S3 into subdirectories of the given directory.
  local check_dir="$1"
  if [[ -z "${check_dir}" ]]
  then
    check_dir=$(mktemp -d -t pants.wheel_check.XXXXX)
    trap "rm -rf ${check_dir}" RETURN
  fi

  banner "Checking prebuilt wheels for ${PANTS_UNSTABLE_VERSION}"
  fetch_prebuilt_wheels "${check_dir}"

  local missing=()
  for PACKAGE in "${RELEASE_PACKAGES[@]}"
  do
    NAME=$(pkg_name $PACKAGE)
    packages=($(find_pkg "${NAME}" "${PANTS_UNSTABLE_VERSION}" "${check_dir}"))
    if [ ${#packages[@]} -eq 0 ]; then
      missing+=("${NAME}")
      continue
    fi

    # Confirm that if the package is not cross platform that we have whls for two platforms.
    local cross_platform=""
    for package in "${packages[@]}"
    do
      if [[ "${package}" =~ "-none-any.whl" ]]
      then
        cross_platform="true"
      fi
    done

    if [ "${cross_platform}" != "true" ] && [ ${#packages[@]} -ne 2 ]; then
      missing+=("${NAME} (expected whls for each platform: had only ${packages[@]})")
      continue
    fi
  done

  if (( ${#missing[@]} > 0 ))
  then
    echo "Failed to find prebuilt packages for:"
    for package in "${missing[@]}"
    do
      echo "  ${package}"
    done
    die
  fi
}

function adjust_wheel_platform() {
  # Renames wheels to adjust their tag from a src platform to a dst platform.
  # TODO: pypi will only accept manylinux wheels, but pex does not support manylinux whls:
  # this function is used to go in one direction or another, depending on who is consuming.
  #   see https://github.com/pantsbuild/pants/issues/4956
  local src_plat="$1"
  local dst_plat="$2"
  local dir="$3"
  for src_whl in `find "${dir}" -name '*'"${src_plat}.whl"`; do
    local dst_whl=${src_whl/$src_plat/$dst_plat}
    mv -f "${src_whl}" "${dst_whl}"
  done
}

function activate_twine() {
  local readonly venv_dir="${ROOT}/build-support/twine-deps.venv"

  rm -rf "${venv_dir}"
  "${ROOT}/build-support/virtualenv" "${venv_dir}"
  source "${venv_dir}/bin/activate"
  pip install twine
}

function build_pex() {
  # Builds a pex from the current UNSTABLE version.

  local linux_platform="linux_x86_64"

  rm -rf "${DEPLOY_DIR}"
  mkdir -p "${DEPLOY_DIR}"
  fetch_and_check_prebuilt_wheels "${DEPLOY_DIR}"
  adjust_wheel_platform "manylinux1_x86_64" "${linux_platform}" "${DEPLOY_DIR}"

  local dest="${ROOT}/dist/pants.${PANTS_UNSTABLE_VERSION}.pex"

  activate_tmp_venv && trap deactivate RETURN && pip install "pex==1.2.13" || die "Failed to install pex."

  local requirements_string=""
  for pkg_name in $PANTS_PEX_PACKAGES; do
    requirements_string="${requirements_string} ${pkg_name}==${PANTS_UNSTABLE_VERSION}"
  done

  pex \
    -o "${dest}" \
    --entry-point="pants.bin.pants_loader:main" \
    --no-build \
    --no-pypi \
    --disable-cache \
    --platform="macosx_10.10_x86_64" \
    --platform="${linux_platform}" \
    -f "${DEPLOY_PANTS_WHEEL_DIR}/${PANTS_UNSTABLE_VERSION}" \
    -f "${DEPLOY_3RDPARTY_WHEEL_DIR}/${PANTS_UNSTABLE_VERSION}" \
    ${requirements_string}

  banner "Successfully built ${dest}"
}

function publish_packages() {
  # TODO(John Sirois): Remove sdist generation and twine upload when
  # https://github.com/pantsbuild/pants/issues/4956 is resolved.
  # NB: We need this step to generate sdists. It also generates wheels locally, but we nuke them
  # and replace with pre-tested binary wheels we download from s3.
  build_pants_packages "${PANTS_STABLE_VERSION}"

  rm -rf "${DEPLOY_PANTS_WHEEL_DIR}"
  mkdir -p "${DEPLOY_PANTS_WHEEL_DIR}/${PANTS_STABLE_VERSION}"

  start_travis_section "Publishing" "Publishing packages for ${PANTS_STABLE_VERSION}"

  # Fetch unstable wheels, rename any linux whls to manylinux, and reversion them
  # from PANTS_UNSTABLE_VERSION to PANTS_STABLE_VERSION
  fetch_and_check_prebuilt_wheels "${DEPLOY_DIR}"
  adjust_wheel_platform "linux_x86_64" "manylinux1_x86_64" \
    "${DEPLOY_PANTS_WHEEL_DIR}/${PANTS_UNSTABLE_VERSION}"
  reversion_whls \
    "${DEPLOY_PANTS_WHEEL_DIR}/${PANTS_UNSTABLE_VERSION}" \
    "${DEPLOY_PANTS_WHEEL_DIR}/${PANTS_STABLE_VERSION}" \
    "${PANTS_STABLE_VERSION}"

  activate_twine
  trap deactivate RETURN

  twine upload --sign --identity=$(get_pgp_keyid) "${DEPLOY_PANTS_WHEEL_DIR}/${PANTS_STABLE_VERSION}"/*.whl
  twine upload --sign --identity=$(get_pgp_keyid) "${DEPLOY_PANTS_SDIST_DIR}/${PANTS_STABLE_VERSION}"/*.tar.gz

  end_travis_section
}

function usage() {
  echo "With no options all packages are built, smoke tested and published to"
  echo "PyPi.  Credentials are needed for this as described in the"
  echo "release docs: http://pantsbuild.org/release.html"
  echo
  echo "Usage: $0 [-d] [-c] (-h|-n|-t|-l|-o|-e|-p)"
  echo " -d  Enables debug mode (verbose output, script pauses after venv creation)"
  echo " -h  Prints out this help message."
  echo " -n  Performs a release dry run."
  echo "       All package distributions will be built, installed locally in"
  echo "       an ephemeral virtualenv and exercised to validate basic"
  echo "       functioning."
  echo " -t  Tests a live release."
  echo "       Ensures the latest packages have been propagated to PyPi"
  echo "       and can be installed in an ephemeral virtualenv."
  echo " -l  Lists all pantsbuild packages that this script releases."
  echo " -o  Lists all pantsbuild package owners."
  echo " -e  Check that wheels are prebuilt for this release."
  echo " -p  Build a pex from prebuilt wheels for this release."
  echo
  echo "All options (except for '-d') are mutually exclusive."

  if (( $# > 0 )); then
    die "$@"
  else
    exit 0
  fi
}

while getopts "hdntcloep" opt; do
  case ${opt} in
    h) usage ;;
    d) debug="true" ;;
    n) dry_run="true" ;;
    t) test_release="true" ;;
    l) list_packages ; exit $? ;;
    o) list_owners ; exit $? ;;
    e) fetch_and_check_prebuilt_wheels ; exit $? ;;
    p) build_pex ; exit $? ;;
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
  banner "Performing a dry run release" && \
  (
    dry_run_install && \
    banner "Dry run release succeeded"
  ) || die "Dry run release failed."
elif [[ "${test_release}" == "true" ]]; then
  banner "Installing and testing the latest released packages" && \
  (
    install_and_test_packages "${PANTS_STABLE_VERSION}" && \
    banner "Successfully installed and tested the latest released packages"
  ) || die "Failed to install and test the latest released packages."
else
  banner "Releasing packages to PyPi" && \
  (
    check_origin && check_clean_branch && check_pgp && check_owners && \
      publish_packages && tag_release && publish_docs_if_master && \
      banner "Successfully released packages to PyPi"
  ) || die "Failed to release packages to PyPi."
fi
