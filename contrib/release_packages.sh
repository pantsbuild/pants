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
  # TODO(John Sirois): The generated pantsbuild.pants.contrib.scrooge should have a requirement on
  # pantsbuild.pants but it currently does not so we must manually install it here.  Investigate
  # this and when fixed, drop the pantsbuild.pants install requirement here.
  # See: https://github.com/pantsbuild/pants/issues/1126
  pip install ${PIP_ARGS} \
    pantsbuild.pants==$(local_version) \
    pantsbuild.pants.contrib.scrooge==$(local_version) && \
  execute_packaged_pants_with_internal_backends --explain gen | grep "scrooge" &> /dev/null && \
  execute_packaged_pants_with_internal_backends goals | grep "thrift-linter" &> /dev/null
}

# Once individual (new) package is declared above, insert it into the array below)
CONTRIB_PACKAGES=(
  PKG_SCROOGE
)
