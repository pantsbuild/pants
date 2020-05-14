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

function pkg_buildgen_install_test() {
  local version=$1
  shift
  local PIP_ARGS=("$@")
  pip install "${PIP_ARGS[@]}" "pantsbuild.pants.contrib.buildgen==${version}" && \
  python -c "from pants.contrib.buildgen.build_file_manipulator import *"
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

function pkg_checks_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.python.checks==${version}']" \
    --explain lint | grep "python-eval" &> /dev/null && \
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.python.checks==${version}']" \
    --explain lint | grep "pythonstyle" &> /dev/null
}

function pkg_checker_install_test() {
  local version=$1
  execute_pex --pypi \
    "pantsbuild.pants.contrib.python.checks.checker==${version}" \
    -c checker -- --help
}

function pkg_confluence_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.confluence==${version}']" \
      --explain confluence | grep "ConfluencePublish_confluence" &> /dev/null
}

function pkg_codeanalysis_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.codeanalysis==${version}']" \
      --explain index | grep "kythe" &> /dev/null
}

function pkg_mypy_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.mypy==${version}']" \
    --explain lint | grep "mypy" &> /dev/null
}

function pkg_awslambda_python_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.awslambda_python==${version}']" \
    --backend-packages2="-['pants.backend.awslambda.python']" \
    --explain bundle | grep "lambdex" &> /dev/null
}
