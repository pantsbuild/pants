#!/usr/bin/env bash

# Defines:
# + RUST_OSX_MIN_VERSION: The minimum minor version of OSX supported by Rust; eg 7 for OSX 10.7.
# + OSX_MAX_VERSION: The current latest OSX minor version; eg 12 for OSX Sierra 10.12.
# + LIB_EXTENSION: The extension of native libraries.
# + KERNEL: The lower-cased name of the kernel as reported by uname.
# + OS_NAME: The name of the OS as seen by pants.
# + OS_ID: The ID of the current OS as seen by pants.
# Exposes:
# + get_native_engine_version: Echoes the current native engine version.
# + get_rust_osx_versions: Produces the osx minor versions supported by Rust one per line.
# + get_rust_os_ids: Produces the BinaryUtil os id paths supported by rust, one per line.

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../../.. && pwd -P)

function get_native_engine_version() {
  ${REPO_ROOT}/pants options --scope=native-engine --name=version --output-format=json | \
    python -c 'import json, sys; print(json.load(sys.stdin)["native-engine.version"]["value"])'
}

readonly RUST_OSX_MIN_VERSION=7

# Bump this when there is a new OSX released:
readonly OSX_MAX_VERSION=12

function get_rust_osx_versions() {
  seq ${RUST_OSX_MIN_VERSION} ${OSX_MAX_VERSION}
}

function get_rust_os_ids() {
  for os_id in linux/{i386,x86_64}
  do
    echo "${os_id}"
  done
  for rev in $(get_rust_osx_versions)
  do
    echo "mac/10.${rev}"
  done
}

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
