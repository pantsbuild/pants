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

PKG_SPINDLE=(
  "pantsbuild.pants.contrib.spindle"
  "//contrib/spindle/src/python/pants/contrib/spindle:plugin"
  "pkg_spindle_install_test"
)
function pkg_spindle_install_test() {
  execute_packaged_pants_with_internal_backends \
    --plugins="['pantsbuild.pants.contrib.spindle==$(local_version)']" \
    --explain gen | grep "spindle" &> /dev/null
}

PKG_GO=(
  "pantsbuild.pants.contrib.go"
  "//contrib/go/src/python/pants/contrib/go:plugin"
  "pkg_go_install_test"
)
function pkg_go_install_test() {
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.go==$(local_version)']" \
      test.go contrib/go/examples::
}

PKG_NODE=(
  "pantsbuild.pants.contrib.node"
  "//contrib/node/src/python/pants/contrib/node:plugin"
  "pkg_node_install_test"
)
function pkg_node_install_test() {
  (cat << EOF
var typ = require('typ');
console.log("type of boolean is: " + typ.BOOLEAN);
EOF
  ) | \
  execute_packaged_pants_with_internal_backends \
      --plugins="['pantsbuild.pants.contrib.node==$(local_version)']" \
      repl.node contrib/node/examples::
}

# Once individual (new) package is declared above, insert it into the array below)
CONTRIB_PACKAGES=(
  PKG_SCROOGE
  PKG_BUILDGEN
  PKG_SPINDLE
  PKG_GO
  PKG_NODE
)
