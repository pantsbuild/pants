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

function local_version() {
  run_local_pants --version 2>/dev/null
}

readonly DEPLOY_DIR="${ROOT}/dist/deploy"
readonly DEPLOY_WHEELS_PATH="wheels/pantsbuild.pants/$(local_version)"
readonly DEPLOY_WHEEL_DIR="${DEPLOY_DIR}/${DEPLOY_WHEELS_PATH}"
readonly DEPLOY_SDIST_DIR="${DEPLOY_DIR}/sdists/pantsbuild.pants/$(local_version)"

source ${ROOT}/contrib/release_packages.sh

function find_pkg() {
  local readonly pkg_name=$1
  local readonly search_dir=${2:-${ROOT}/dist/${pkg_name}-$(local_version)/dist}
  find "${search_dir}" -type f -name "${pkg_name}-$(local_version)-*.whl"
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
# Each package definition is of form:
#
# PKG_<NAME>=(
#   "package.name"
#   "//a/build:target"
#   "pkg_<name>_install_test"
#   "bdist_wheel flags" # NB: this entry is optional.
# )
# function pkg_<name>_install_test() {
#   ...
# }
#
PKG_PANTS=(
  "pantsbuild.pants"
  "//src/python/pants:pants-packaged"
  "pkg_pants_install_test"
  "--python-tag cp27 --plat-name $(find_plat_name)"
)
function pkg_pants_install_test() {
  PIP_ARGS="$@"
  pip install ${PIP_ARGS} "$(find_pkg pantsbuild.pants)" || \
    die "pip install of pantsbuild.pants failed!"
  execute_packaged_pants_with_internal_backends list src:: || \
    die "'pants list src::' failed in venv!"
  [[ "$(execute_packaged_pants_with_internal_backends --version 2>/dev/null)" \
     == "$(local_version)" ]] || die "Installed version of pants does match local version!"
}

PKG_PANTS_TESTINFRA=(
  "pantsbuild.pants.testinfra"
  "//tests/python/pants_test:test_infra"
  "pkg_pants_testinfra_install_test"
)
function pkg_pants_testinfra_install_test() {
  PIP_ARGS="$@"
  pip install ${PIP_ARGS} "$(find_pkg pantsbuild.pants.testinfra)" && \
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

# When we do (dry-run) testing, we need to run the packaged pants.
# It doesn't have internal backend plugins so when we execute it
# at the repo build root, the root pants.ini will ask it to load
# internal backend packages and their dependencies which it doesn't have,
# and it'll fail. To solve that problem, we load the internal backend package
# dependencies into the pantsbuild.pants venv.
function execute_packaged_pants_with_internal_backends() {
  pip install --ignore-installed \
    -r pants-plugins/3rdparty/python/requirements.txt &> /dev/null && \
  PANTS_PYTHON_REPOS_REPOS="${DEPLOY_WHEEL_DIR}" pants \
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

function build_packages() {
  # TODO(John Sirois): Remove sdist generation and twine upload when
  # https://github.com/pantsbuild/pants/issues/4956 is resolved.

  rm -rf "${DEPLOY_WHEEL_DIR}" "${DEPLOY_SDIST_DIR}"
  mkdir -p "${DEPLOY_WHEEL_DIR}" "${DEPLOY_SDIST_DIR}"

  for PACKAGE in "${RELEASE_PACKAGES[@]}"
  do
    NAME=$(pkg_name $PACKAGE)
    BUILD_TARGET=$(pkg_build_target $PACKAGE)
    BDIST_WHEEL_FLAGS=$(bdist_wheel_flags $PACKAGE)

    start_travis_section "${NAME}" "Building package ${NAME}-$(local_version) with target '${BUILD_TARGET}'"
    run_local_pants setup-py \
      --run="sdist bdist_wheel ${BDIST_WHEEL_FLAGS:---python-tag py27}" \
        ${BUILD_TARGET} || \
      die "Failed to build package ${NAME}-$(local_version) with target '${BUILD_TARGET}'!"
    wheel=$(find_pkg ${NAME})
    cp -p "${wheel}" "${DEPLOY_WHEEL_DIR}/"
    cp -p "${ROOT}/dist/${NAME}-$(local_version)/dist/${NAME}-$(local_version).tar.gz" "${DEPLOY_SDIST_DIR}/"
    end_travis_section
  done
}

function pre_install() {
  start_travis_section "SetupVenv" "Setting up virtualenv"
  VENV_DIR=$(mktemp -d -t pants.XXXXX) && \
  ${ROOT}/build-support/virtualenv $VENV_DIR && \
  source $VENV_DIR/bin/activate
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
  CORE_ONLY=$1
  shift 1
  PIP_ARGS=(
    "$@"
    --quiet

    # Make sure we go out and hit pypi to get the new packages.
    --no-cache-dir
  )

  pre_install || die "Failed to setup virtualenv while testing ${NAME}-$(local_version)!"

  # Make sure we install fresh plugins since pants uses a fixed version number between releases.
  export PANTS_PLUGIN_CACHE_DIR=$(mktemp -d -t plugins_cache.XXXXX)
  trap "rm -rf ${PANTS_PLUGIN_CACHE_DIR}" EXIT

  if [[ "${CORE_ONLY}" == "true" ]]
  then
    PACKAGES=("${CORE_PACKAGES[@]}")
  else
    PACKAGES=("${RELEASE_PACKAGES[@]}")
  fi

  for PACKAGE in "${PACKAGES[@]}"
  do
    NAME=$(pkg_name $PACKAGE)
    INSTALL_TEST_FUNC=$(pkg_install_test_func $PACKAGE)

    start_travis_section "${NAME}" "Installing and testing package ${NAME}-$(local_version)"
    eval $INSTALL_TEST_FUNC ${PIP_ARGS[@]} || \
      die "Failed to install and test package ${NAME}-$(local_version)!"
    end_travis_section
  done

  post_install || die "Failed to deactivate virtual env while testing ${NAME}-$(local_version)!"

}

function dry_run_install() {
  CORE_ONLY=$1
  build_packages && \
  install_and_test_packages "${CORE_ONLY}" --find-links="${DEPLOY_WHEEL_DIR}"
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
  release_version="$(local_version)" && \
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
  version="$(local_version)"
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
   username="$1"
   package_name="$2"

   for owner in $(get_owners ${package_name})
   do
     # NB: A case-insensitive comparison is done since pypi is case-insensitive wrt usernames.
     # Note that the ^^ case operator requires bash 4.  If you're on a Mac you may need to brew
     # install bash, as the version that comes with MacOS is ancient.
     if [[ "${username^^}" == "${owner^^}" ]]
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

readonly BINARY_BASE_URL=https://binaries.pantsbuild.org

function list_prebuilt_wheels() {
  wheel_listing="$(mktemp -t pants.wheels.XXXXX)"
  trap "rm -f ${wheel_listing}" RETURN

  curl -sSL "${BINARY_BASE_URL}/?prefix=${DEPLOY_WHEELS_PATH}" > "${wheel_listing}"
  "${PY}" << EOF
from __future__ import print_function
import sys
import xml.etree.ElementTree as ET
root = ET.parse("${wheel_listing}")
ns = {'s3': 'http://s3.amazonaws.com/doc/2006-03-01/'}
for key in root.findall('s3:Contents/s3:Key', ns):
  print(key.text)
EOF
}

function fetch_prebuilt_wheels() {
  local readonly to_dir="$1"

  banner "Fetching prebuilt wheels for $(local_version)"
  (
    cd "${to_dir}"
    list_prebuilt_wheels | {
      while read path
      do
        echo "${BINARY_BASE_URL}/${path}:"
        curl --progress-bar -O "${BINARY_BASE_URL}/${path}"
      done
    }
  )
}

function check_prebuilt_wheels() {
  local check_dir="$1"
  if [[ -z "${check_dir}" ]]
  then
    check_dir=$(mktemp -d -t pants.wheel_check.XXXXX)
    trap "rm -rf ${check_dir}" RETURN
  fi

  banner "Checking prebuilt wheels for $(local_version)"
  fetch_prebuilt_wheels "${check_dir}"

  local missing=()
  for PACKAGE in "${RELEASE_PACKAGES[@]}"
  do
    NAME=$(pkg_name $PACKAGE)
    packages=($(find_pkg "${NAME}" "${check_dir}"))
    (( ${#packages[@]} > 0 )) || missing+=("${NAME}")

    # Here we re-name the linux platform specific wheels we build to masquerade as manylinux1
    # compatible wheels. We take care to support this when we generate the wheels and pypi will
    # only accept manylinux1 linux binary wheels.
    for package in "${packages[@]}"
    do
      if [[ "${package}" =~ "-linux_" ]]
      then
        mv -v "${package}" "${package/-linux_/-manylinux1_}"
      fi
    done
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

function activate_twine() {
  local readonly venv_dir="${ROOT}/build-support/twine-deps.venv"

  rm -rf "${venv_dir}"
  "${ROOT}/build-support/virtualenv" "${venv_dir}"
  source "${venv_dir}/bin/activate"
  pip install twine
}

function publish_packages() {
  rm -rf "${DEPLOY_WHEEL_DIR}"
  mkdir -p "${DEPLOY_WHEEL_DIR}"

  start_travis_section "Publishing" "Publishing packages"

  check_prebuilt_wheels "${DEPLOY_WHEEL_DIR}"

  activate_twine
  trap deactivate RETURN

  twine upload --sign --identity=$(get_pgp_keyid) "${DEPLOY_WHEEL_DIR}"/*.whl
  twine upload --sign --identity=$(get_pgp_keyid) "${DEPLOY_SDIST_DIR}"/*.tar.gz

  end_travis_section
}

function usage() {
  echo "With no options all packages are built, smoke tested and published to"
  echo "PyPi.  Credentials are needed for this as described in the"
  echo "release docs: http://pantsbuild.org/release.html"
  echo
  echo "Usage: $0 [-d] [-c] (-h|-n|-t|-l|-o|-e)"
  echo " -d  Enables debug mode (verbose output, script pauses after venv creation)"
  echo " -h  Prints out this help message."
  echo " -n  Performs a release dry run."
  echo "       All package distributions will be built, installed locally in"
  echo "       an ephemeral virtualenv and exercised to validate basic"
  echo "       functioning."
  echo " -t  Tests a live release."
  echo "       Ensures the latest packages have been propagated to PyPi"
  echo "       and can be installed in an ephemeral virtualenv."
  echo " -c  Skips contrib during a dry or test run."
  echo "       It is still necessary to pass -n or -t to trigger the test/dry run."
  echo " -l  Lists all pantsbuild packages that this script releases."
  echo " -o  Lists all pantsbuild package owners."
  echo " -e  Check that wheels are prebuilt for this release."
  echo
  echo "All options (except for '-d' and '-c') are mutually exclusive."

  if (( $# > 0 )); then
    die "$@"
  else
    exit 0
  fi
}

while getopts "hdntcloe" opt; do
  case ${opt} in
    h) usage ;;
    d) debug="true" ;;
    n) dry_run="true" ;;
    t) test_release="true" ;;
    c) core_only="true" ;;
    l) list_packages && exit 0 ;;
    o) list_owners && exit 0 ;;
    e) check_prebuilt_wheels && exit 0 ;;
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
    dry_run_install "${core_only}" && \
    banner "Dry run release succeeded"
  ) || die "Dry run release failed."
elif [[ "${test_release}" == "true" ]]; then
  banner "Installing and testing the latest released packages" && \
  (
    install_and_test_packages "${core_only}" && \
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
