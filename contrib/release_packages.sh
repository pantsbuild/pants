#!/usr/bin/env bash

#
# List of contrib packages to be released
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
PKG_SCROOGE=(
  "pantsbuild.pants.contrib.scrooge"
  "//contrib/scrooge/src/python/pants/contrib/scrooge:plugin"
  "pkg_scrooge_install_test"
)
function pkg_scrooge_install_test() {
  PIP_ARGS="$@"
  pip install ${PIP_ARGS} pantsbuild.pants.contrib.scrooge==$(local_version) && \
  execute_packaged_pants_with_internal_backends --explain gen | grep "scrooge" &> /dev/null && \
  execute_packaged_pants_with_internal_backends goals | grep "thrift-linter" &> /dev/null
}

PKG_BUILDGEN=(
  "pantsbuild.pants.contrib.buildgen"
  "//contrib/buildgen/src/python/pants/contrib/buildgen:plugin"
  "pkg_buildgen_install_test"
)
function pkg_buildgen_install_test() {
  PIP_ARGS="$@"
  pip install ${PIP_ARGS} pantsbuild.pants.contrib.buildgen==$(local_version) && \
  execute_packaged_pants_with_internal_backends test contrib/buildgen::
}

# Once individual (new) package is declared above, insert it into the array below)
CONTRIB_PACKAGES=(
  PKG_SCROOGE
  PKG_BUILDGEN
)
