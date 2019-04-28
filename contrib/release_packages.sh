
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
  local PIP_ARGS="$@"
  pip install ${PIP_ARGS} "pantsbuild.pants.contrib.buildgen==${version}" && \
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

function pkg_scalajs_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.scalajs==${version}']" \
      --explain compile | grep "scala-js-link" &> /dev/null
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

function pkg_findbugs_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.findbugs==${version}']" \
      --explain compile | grep "findbugs" &> /dev/null
}

function pkg_cpp_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.cpp==${version}']" \
      --explain compile | grep "cpp" &> /dev/null
}

function pkg_confluence_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.confluence==${version}']" \
      --explain confluence | grep "ConfluencePublish_confluence" &> /dev/null
}

function pkg_errorprone_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.errorprone==${version}']" \
      --explain compile | grep "errorprone" &> /dev/null
}

function pkg_codeanalysis_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.codeanalysis==${version}']" \
      --explain index | grep "kythe" &> /dev/null
}

function pkg_jax_ws_install_test() {
  local version=$1
  # Ensure our goal and target are installed and exposed.
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.jax_ws==${version}']" \
      --explain gen | grep "jax-ws" &> /dev/null
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.jax_ws==${version}']" \
      targets | grep "jax_ws_library" &> /dev/null
}

function pkg_mypy_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.mypy==${version}']" \
    --explain mypy &> /dev/null
}

function pkg_avro_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.avro==${version}']" \
    --explain gen | grep "avro-java" &> /dev/null
}

function pkg_awslambda_python_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.awslambda_python==${version}']" \
    --explain bundle | grep "lambdex" &> /dev/null
}

function pkg_thrifty_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.thrifty==${version}']" \
    --explain gen | grep "thrifty" &> /dev/null
}

function pkg_googlejavaformat_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.googlejavaformat==${version}']" \
    --explain fmt | grep "google-java-format" &> /dev/null
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.googlejavaformat==${version}']" \
    --explain lint | grep "google-java-format" &> /dev/null
}
