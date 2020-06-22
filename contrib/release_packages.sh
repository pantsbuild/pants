#!/usr/bin/env bash

#
# List of contrib packages to be released
# See build-support/README.md for more information on the format of each
# `PKG_$NAME` definition.
#

function pkg_mypy_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.mypy==${version}']" \
    --explain lint | grep "mypy" &> /dev/null
}
