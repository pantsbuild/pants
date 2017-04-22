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

PKG_ANDROID=(
  "pantsbuild.pants.contrib.android"
  "//contrib/android/src/python/pants/contrib/android:plugin"
  "pkg_android_install_test"
)
function pkg_android_install_test() {
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.android==$(local_version)']" \
    --explain apk | grep "apk" &> /dev/null
}


PKG_SCROOGE=(
  "pantsbuild.pants.contrib.scrooge"
  "//contrib/scrooge/src/python/pants/contrib/scrooge:plugin"
  "pkg_scrooge_install_test"
)
function pkg_scrooge_install_test() {
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.scrooge==$(local_version)']" \
    --explain gen | grep "scrooge" &> /dev/null && \
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.scrooge==$(local_version)']" \
    goals | grep "thrift-linter" &> /dev/null
}

PKG_BUILDGEN=(
  "pantsbuild.pants.contrib.buildgen"
  "//contrib/buildgen/src/python/pants/contrib/buildgen:plugin"
  "pkg_buildgen_install_test"
)
function pkg_buildgen_install_test() {
  PIP_ARGS="$@"
  pip install ${PIP_ARGS} pantsbuild.pants.contrib.buildgen==$(local_version) && \
  python -c "from pants.contrib.buildgen.build_file_manipulator import *"
}

PKG_GO=(
  "pantsbuild.pants.contrib.go"
  "//contrib/go/src/python/pants/contrib/go:plugin"
  "pkg_go_install_test"
)
function pkg_go_install_test() {
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.go==$(local_version)']" \
      buildgen test contrib/go/examples::
}

PKG_NODE=(
  "pantsbuild.pants.contrib.node"
  "//contrib/node/src/python/pants/contrib/node:plugin"
  "pkg_node_install_test"
)
function pkg_node_install_test() {
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.node==$(local_version)']" \
      test.node contrib/node/examples::
}

PKG_SCALAJS=(
  "pantsbuild.pants.contrib.scalajs"
  "//contrib/scalajs/src/python/pants/contrib/scalajs:plugin"
  "pkg_scalajs_install_test"
)
function pkg_scalajs_install_test() {
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.scalajs==$(local_version)']" \
      test contrib/scalajs::
}

PKG_PYTHON_CHECKS=(
  "pantsbuild.pants.contrib.python.checks"
  "//contrib/python/src/python/pants/contrib/python/checks:plugin"
  "pkg_python_checks_install_test"
)
function pkg_python_checks_install_test() {
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.python.checks==$(local_version)']" \
    --explain lint | grep "python-eval" &> /dev/null && \
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.python.checks==$(local_version)']" \
    --explain lint | grep "pythonstyle" &> /dev/null
}

PKG_FINDBUGS=(
  "pantsbuild.pants.contrib.findbugs"
  "//contrib/findbugs/src/python/pants/contrib/findbugs:plugin"
  "pkg_findbugs_install_test"
)
function pkg_findbugs_install_test() {
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.findbugs==$(local_version)']" \
      --explain compile | grep "findbugs" &> /dev/null
}

PKG_CPP=(
  "pantsbuild.pants.contrib.cpp"
  "//contrib/cpp/src/python/pants/contrib/cpp:plugin"
  "pkg_cpp_install_test"
)
function pkg_cpp_install_test() {
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.cpp==$(local_version)']" \
      --explain compile | grep "cpp" &> /dev/null
}

PKG_ERRORPRONE=(
  "pantsbuild.pants.contrib.errorprone"
  "//contrib/errorprone/src/python/pants/contrib/errorprone:plugin"
  "pkg_errorprone_install_test"
)
function pkg_errorprone_install_test() {
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.errorprone==$(local_version)']" \
      --explain compile | grep "errorprone" &> /dev/null
}

PKG_JAXWS=(
  "pantsbuild.pants.contrib.jax_ws"
  "//contrib/jax_ws/src/python/pants/contrib/jax_ws:plugin"
  "pkg_jax_ws_install_test"
)
function pkg_jax_ws_install_test() {
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.jax_ws==$(local_version)']" \
      --explain gen | grep "jax-ws" &> /dev/null
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
  PKG_ERRORPRONE
  PKG_JAXWS
)
