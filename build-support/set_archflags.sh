#!/usr/bin/env bash

# Prevent bootstrapping failure due to unrecognized flag:
# https://github.com/pantsbuild/pants/issues/78
function set_archflags() {
  GCC_VERSION=`gcc -v 2>&1`
  if [[ "$GCC_VERSION" == *503.0.38* ]]; then
    # Required for clang version 503.0.38
    export set ARCHFLAGS=-Wno-error=unused-command-line-argument-hard-error-in-future
  fi
}
set_archflags