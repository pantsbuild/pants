#!/usr/bin/env bash

#
# List of contrib packages to be released
# See build-support/README.md for more information on the format of each
# `PKG_$NAME` definition.
#

PKG_ANDROID=(
  "pantsbuild.pants.contrib.android"
  "//contrib/android/src/python/pants/contrib/android:plugin"
  "pkg_android_install_test"
)
function pkg_android_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.android==${version}']" \
    --explain apk | grep "apk" &> /dev/null
}


PKG_SCROOGE=(
  "pantsbuild.pants.contrib.scrooge"
  "//contrib/scrooge/src/python/pants/contrib/scrooge:plugin"
  "pkg_scrooge_install_test"
)
function pkg_scrooge_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.scrooge==${version}']" \
    --explain gen | grep "scrooge" &> /dev/null && \
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.scrooge==${version}']" \
    goals | grep "thrift-linter" &> /dev/null
}

PKG_BUILDGEN=(
  "pantsbuild.pants.contrib.buildgen"
  "//contrib/buildgen/src/python/pants/contrib/buildgen:plugin"
  "pkg_buildgen_install_test"
)
function pkg_buildgen_install_test() {
  local version=$1
  shift
  local PIP_ARGS="$@"
  pip install ${PIP_ARGS} "pantsbuild.pants.contrib.buildgen==${version}" && \
  python -c "from pants.contrib.buildgen.build_file_manipulator import *"
}

PKG_GO=(
  "pantsbuild.pants.contrib.go"
  "//contrib/go/src/python/pants/contrib/go:plugin"
  "pkg_go_install_test"
)
function pkg_go_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.go==${version}']" \
      --explain test | grep "GoTest_test_go" &> /dev/null
}

PKG_NODE=(
  "pantsbuild.pants.contrib.node"
  "//contrib/node/src/python/pants/contrib/node:plugin"
  "pkg_node_install_test"
)
function pkg_node_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.node==${version}']" \
      --explain test | grep "NodeTest_test_node" &> /dev/null
}

PKG_SCALAJS=(
  "pantsbuild.pants.contrib.scalajs"
  "//contrib/scalajs/src/python/pants/contrib/scalajs:plugin"
  "pkg_scalajs_install_test"
)
function pkg_scalajs_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.scalajs==${version}']" \
      --explain compile | grep "scala-js-link" &> /dev/null
}

PKG_PYTHON_CHECKS=(
  "pantsbuild.pants.contrib.python.checks"
  "//contrib/python/src/python/pants/contrib/python/checks:plugin"
  "pkg_python_checks_install_test"
)
function pkg_python_checks_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.python.checks==${version}']" \
    --explain lint | grep "python-eval" &> /dev/null && \
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.python.checks==${version}']" \
    --explain lint | grep "pythonstyle" &> /dev/null
}

PKG_FINDBUGS=(
  "pantsbuild.pants.contrib.findbugs"
  "//contrib/findbugs/src/python/pants/contrib/findbugs:plugin"
  "pkg_findbugs_install_test"
)
function pkg_findbugs_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.findbugs==${version}']" \
      --explain compile | grep "findbugs" &> /dev/null
}

PKG_CPP=(
  "pantsbuild.pants.contrib.cpp"
  "//contrib/cpp/src/python/pants/contrib/cpp:plugin"
  "pkg_cpp_install_test"
)
function pkg_cpp_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.cpp==${version}']" \
      --explain compile | grep "cpp" &> /dev/null
}

PKG_CONFLUENCE=(
  "pantsbuild.pants.contrib.confluence"
  "//contrib/confluence/src/python/pants/contrib/confluence:plugin"
  "pkg_confluence_install_test"
)
function pkg_confluence_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.confluence==${version}']" \
      --explain confluence | grep "ConfluencePublish_confluence" &> /dev/null
}

PKG_ERRORPRONE=(
  "pantsbuild.pants.contrib.errorprone"
  "//contrib/errorprone/src/python/pants/contrib/errorprone:plugin"
  "pkg_errorprone_install_test"
)
function pkg_errorprone_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.errorprone==${version}']" \
      --explain compile | grep "errorprone" &> /dev/null
}

PKG_CODEANALYSIS=(
  "pantsbuild.pants.contrib.codeanalysis"
  "//contrib/codeanalysis/src/python/pants/contrib/codeanalysis:plugin"
  "pkg_codeanalysis_install_test"
)
function pkg_codeanalysis_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.codeanalysis==${version}']" \
      --explain index | grep "kythe" &> /dev/null
}

PKG_JAXWS=(
  "pantsbuild.pants.contrib.jax_ws"
  "//contrib/jax_ws/src/python/pants/contrib/jax_ws:plugin"
  "pkg_jax_ws_install_test"
)
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

PKG_MYPY=(
  "pantsbuild.pants.contrib.mypy"
  "//contrib/mypy/src/python/pants/contrib/mypy:plugin"
  "pkg_mypy_install_test"
)
function pkg_mypy_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.mypy==${version}']" \
    --explain mypy &> /dev/null
}

PKG_AVRO=(
  "pantsbuild.pants.contrib.avro"
  "//contrib/avro/src/python/pants/contrib/avro:plugin"
  "pkg_avro_install_test"
)
function pkg_avro_install_test() {
  local version=$1
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.avro==${version}']" \
    --explain gen | grep "avro-java" &> /dev/null
}

# Once individual (new) package is declared above, insert it into the array below)
CONTRIB_PACKAGES=(
  PKG_ANDROID
  PKG_SCROOGE
  PKG_BUILDGEN
  PKG_GO
  PKG_NODE
  PKG_PYTHON_CHECKS
  PKG_SCALAJS
  PKG_FINDBUGS
  PKG_CPP
  PKG_CONFLUENCE
  PKG_ERRORPRONE
  PKG_CODEANALYSIS
  PKG_JAXWS
  PKG_MYPY
  PKG_AVRO
)
