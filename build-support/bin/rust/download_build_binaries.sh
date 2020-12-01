#!/bin/bash

set -euo pipefail

# Download the binaries required by cargo.sh to build our native code.
# Sets associated env vars as needed.

# Note that this scripts logs to stderr as a script that indirectly calls it relies on
# capturing stdout to identify a file created by an intermediate script.

bin_cache="${HOME}/.cache/pants/bin"
arch="$(uname)"

if [[ ! "${arch}" =~ ^(Darwin|Linux)$ ]]; then
    die "Unrecognized arch (uname=${arch})"
fi

arch_lower="$(echo "${arch}" | tr '[:upper:]' '[:lower:]')"

# Download cmake

cmake_rev="3.9.5"
cmake_cache="${bin_cache}/cmake"
cmake_archive="${cmake_cache}/cmake.tar.gz"
mkdir -p "${cmake_cache}"
case "${arch}" in
  "Darwin") cmake_bin_reldir="CMake.app/Contents/bin" ;;
  "Linux") cmake_bin_reldir="bin" ;;
esac
cmake_bin_dir="${cmake_cache}/cmake-${cmake_rev}-${arch}-x86_64/${cmake_bin_reldir}"
if [[ ! -f "${cmake_bin_dir}/cmake" ]]; then
  echo "Downloading cmake ${cmake_rev} ..." 1>&2
  curl --fail -L -o "${cmake_archive}" "https://cmake.org/files/v3.9/cmake-${cmake_rev}-${arch}-x86_64.tar.gz"
  tar xzf "${cmake_archive}" -C "${cmake_cache}"
  rm -f "${cmake_archive}"
fi
PATH="${cmake_bin_dir}:${PATH}"


# Download go

go_rev="1.7.3"
go_cache="${bin_cache}/go"
go_archive="${go_cache}/go.tar.gz"
mkdir -p "${go_cache}"
go_bin_dir="${go_cache}/go/bin"
if [[ ! -f "${go_bin_dir}/go" ]]; then
  echo "Downloading go ${go_rev}..." 1>&2
  curl --fail -L -o "${go_archive}" "https://storage.googleapis.com/golang/go1.7.3.${arch_lower}-amd64.tar.gz"
  tar xzf "${go_archive}" -C "${go_cache}"
  rm -f "${go_archive}"
fi
PATH="${go_bin_dir}:${PATH}"
export GOROOT="${go_cache}/go"


# Download protoc

protoc_rev="3.5.0"
protoc_cache="${bin_cache}/protoc"
protoc_archive="${protoc_cache}/protoc.zip"
mkdir -p "${protoc_cache}"
protoc_bin_dir="${protoc_cache}/bin"
if [[ ! -f "${protoc_bin_dir}/protoc" ]]; then
  case "${arch}" in
    "Darwin") arch_str="osx" ;;
    "Linux") arch_str="linux" ;;
  esac
  echo "Downloading protoc ${protoc_rev}..." 1>&2
  curl --fail -L -o "${protoc_archive}" "https://github.com/protocolbuffers/protobuf/releases/download/v${protoc_rev}/protoc-${protoc_rev}-${arch_str}-x86_64.zip"
  unzip -qq "${protoc_archive}" -d "${protoc_cache}"
  rm -f "${protoc_archive}"
fi
PATH="${protoc_bin_dir}:${PATH}"
export PROTOC="${protoc_bin_dir}/protoc"


# Download binutils on linux

case "${arch}" in
  "Darwin")
    # The homebrew version of the `ar` tool appears to "sometimes" create libnative_engine_ffi.a
    # instances which aren't recognized as Mach-O x86-64 binaries when first on the PATH. This
    # causes a silent linking error at build time due to the use of the `-undefined dynamic_lookup`
    # flag, which then becomes:
    # "Symbol not found: _wrapped_PyInit_native_engine"
    # when attempting to import the native engine library in native.py.
    # NB: This line uses the version of `ar` provided by OSX itself, which avoids the linking error.
    export AR='/usr/bin/ar'
    ;;
  "Linux")
    # While the linking error when consuming libnative_engine_ffi.a does not repro on Linux, since
    # we have a reliable version of `ar` available from the pantsbuild s3, we might as well use it.
    binutils_rev="2.30"
    binutils_cache="${bin_cache}/binutils"
    binutils_archive="${binutils_cache}/binutils.tar.gz"
    mkdir -p "${binutils_cache}"
    binutils_bin_dir="${binutils_cache}/bin"
    if [[ ! -f "${binutils_bin_dir}/ar" ]]; then
      echo "Downloading binutils ${binutils_rev}..." 1>&2
      curl --fail -L -o "${binutils_archive}" "https://binaries.pantsbuild.org/bin/binutils/linux/x86_64/${binutils_rev}/binutils.tar.gz"
      tar xzf "${binutils_archive}" -C "${binutils_cache}"
      rm -f "${binutils_archive}"
    fi
    PATH="${binutils_bin_dir}:${PATH}"
    export AR="${binutils_bin_dir}/ar"
    ;;
esac

export PATH
