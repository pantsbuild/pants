#!/usr/bin/env bash
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd "$(git rev-parse --show-toplevel)" && pwd)
source ${ROOT}/build-support/common.sh

PY=$(which python2.7)
[[ -n "${PY}" ]] || die "You must have python2.7 installed and on the path to release."
export PY

source ${ROOT}/contrib/release_packages.sh

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
  pip install ${PIP_ARGS} "${ROOT}/dist/pantsbuild.pants-$(local_version).tar.gz" || \
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
  pip install ${PIP_ARGS} "${ROOT}/dist/pantsbuild.pants.testinfra-$(local_version).tar.gz" && \
  python -c "import pants_test"
}

# Once an individual (new) package is declared above, insert it into the array below)
RELEASE_PACKAGES=(
  PKG_PANTS
  PKG_PANTS_TESTINFRA
  ${CONTRIB_PACKAGES[*]}
)
#
# End of package declarations.
#

function run_local_pants() {
  ${ROOT}/pants "$@"
}

# When we do (dry-run) testing, we need to run the packaged pants.
# It doesn't have internal backend plugins so when we execute it
# at the repo build root, the root pants.ini will ask it load
# internal backend packages and their dependencies which it doesn't have,
# and it'll fail. To solve that problem, we load the internal backend package
# dependencies into the pantsbuild.pants venv.
function execute_packaged_pants_with_internal_backends() {
  pip install --ignore-installed \
    -r pants-plugins/3rdparty/python/requirements.txt &> /dev/null && \
  PANTS_PYTHON_REPOS_REPOS="['${ROOT}/dist']" pants \
    --no-verify-config \
    --pythonpath="['pants-plugins/src/python']" \
    --backend-packages="[ \
        'pants.backend.docgen', \
        'internal_backend.optional', \
        'internal_backend.repositories', \
        'internal_backend.sitegen', \
        'internal_backend.utilities', \
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

function local_version() {
  run_local_pants --version 2>/dev/null
}

function build_packages() {
  for PACKAGE in "${RELEASE_PACKAGES[@]}"
  do
    NAME=$(pkg_name $PACKAGE)
    BUILD_TARGET=$(pkg_build_target $PACKAGE)

    banner "Building package ${NAME}-$(local_version) with target '${BUILD_TARGET}' ..."

    run_local_pants setup-py --recursive ${BUILD_TARGET} || \
    die "Failed to build package ${NAME}-$(local_version) with target '${BUILD_TARGET}'!"
  done
}

function publish_packages() {
  targets=()
  for PACKAGE in "${RELEASE_PACKAGES[@]}"
  do
    targets+=($(pkg_build_target $PACKAGE))
  done
  banner "Publishing packages ..."
  run_local_pants setup-py --run="register sdist upload --sign --identity=$(get_pgp_keyid)" \
    --recursive ${targets[@]} || \
  die "Failed to publish packages!"
}

function pre_install() {
  VENV_DIR=$(mktemp -d -t pants.XXXXX) && \
  ${ROOT}/build-support/virtualenv $VENV_DIR && \
  source $VENV_DIR/bin/activate
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

  for PACKAGE in "${RELEASE_PACKAGES[@]}"
  do
    NAME=$(pkg_name $PACKAGE)
    INSTALL_TEST_FUNC=$(pkg_install_test_func $PACKAGE)

    banner "Installing and testing package ${NAME}-$(local_version) ..."

    eval $INSTALL_TEST_FUNC ${PIP_ARGS[@]} || \
    die "Failed to install and test package ${NAME}-$(local_version)!"
  done

  post_install || die "Failed to deactivate virtual env while testing ${NAME}-$(local_version)!"

}

function dry_run_install() {
  build_packages && \
  install_and_test_packages --find-links=file://${ROOT}/dist
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
  ${PY} << EOF || die
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
  git tag \
    --local-user=$(get_pgp_keyid) \
    -m "pantsbuild.pants release ${release_version}" \
    ${tag_name} && \
  git push git@github.com:pantsbuild/pants.git ${tag_name}
}

function publish_docs_if_master() {
  branch=$(get_branch)
  if [[ $branch =~ "^master$" ]]; then
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
        grep -oE  "/pypi/${package_name}/[0-9]+\.[0-9]+\.[0-9]+(-(rc|dev)[0-9]+)?" | head -n1
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
  banner "Checking package ownership for pypi user ${username} of ${total} packages ..."
  dont_own=()
  index=0
  for PACKAGE in "${RELEASE_PACKAGES[@]}"
  do
    index=$((index+1))
    package_name="$(pkg_name $PACKAGE)"
    banner "[${index}/${total}] checking that ${username} owns ${package_name}..."
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

function usage() {
  echo "With no options all packages are built, smoke tested and published to"
  echo "PyPi.  Credentials are needed for this as described in the"
  echo "release docs: http://pantsbuild.github.io/release.html"
  echo
  echo "Usage: $0 [-d] (-h|-n|-t|-l|-o)"
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
  echo
  echo "All options (except for '-d') are mutually exclusive."

  if (( $# > 0 )); then
    die "$@"
  else
    exit 0
  fi
}

while getopts "hdntlo" opt; do
  case ${opt} in
    h) usage ;;
    d) debug="true" ;;
    n) dry_run="true" ;;
    t) test_release="true" ;;
    l) list_packages && exit 0 ;;
    o) list_owners && exit 0 ;;
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
    check_origin && check_clean_branch && check_pgp && check_owners && \
      dry_run_install && publish_packages && tag_release && publish_docs_if_master && \
      banner "Successfully released packages to PyPi."
  ) || die "Failed to release packages to PyPi."
fi
