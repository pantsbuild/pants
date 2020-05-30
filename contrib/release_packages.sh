#!/usr/bin/env bash

#
# List of contrib packages to be released
# See build-support/README.md for more information on the format of each
# `PKG_$NAME` definition.
#

function pkg_scrooge_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.scrooge==${version}']" \
    --explain gen | grep "scrooge" &> /dev/null && \
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.scrooge==${version}']" \
    --explain lint | grep "thrift" &> /dev/null
}

function pkg_go_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.go==${version}']" \
      --explain test | grep "GoTest_test_go" &> /dev/null
}

function pkg_node_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.node==${version}']" \
      --explain test | grep "NodeTest_test_node" &> /dev/null
}

function pkg_confluence_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.confluence==${version}']" \
      --explain confluence | grep "ConfluencePublish_confluence" &> /dev/null
}

function pkg_mypy_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.mypy==${version}']" \
    --explain lint | grep "mypy" &> /dev/null
}
