#!/usr/bin/env bash

# Defines:
# + LIB_EXTENSION: The extension of native libraries.
# + KERNEL: The lower-cased name of the kernel as reported by uname.
# + OS_NAME: The name of the OS as seen by pants.
# + OS_ID: The ID of the current OS as seen by pants.

# TODO(John Sirois): Eliminate this replication of BinaryUtil logic internal to pants code when
# https://github.com/pantsbuild/pants/issues/4006 is complete.
readonly KERNEL=$(uname -s | tr '[:upper:]' '[:lower:]')
case "${KERNEL}" in
  linux)
    readonly LIB_EXTENSION=so
    readonly OS_NAME=linux
    readonly OS_ID=${OS_NAME}/$(uname -m)
    ;;
  darwin)
    readonly LIB_EXTENSION=dylib
    readonly OS_NAME=mac
    readonly OS_ID=${OS_NAME}/$(sw_vers -productVersion | cut -d: -f2 | tr -d ' \t' | cut -d. -f1-2)
    ;;
  *)
    die "Unknown kernel ${KERNEL}, cannot bootstrap pants native code!"
    ;;
esac