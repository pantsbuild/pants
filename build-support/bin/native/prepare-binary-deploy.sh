#!/usr/bin/env bash

set -e

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../../.. && pwd -P)

# Indirectly defines:
# + RUST_OSX_MIN_VERSION: The minimum minor version of OSX supported by Rust; eg 7 for OSX 10.7.
# + OSX_MAX_VERSION: The current latest OSX minor version; eg 12 for OSX Sierra 10.12.
# + LIB_EXTENSION: The extension of native libraries.
# + KERNEL: The lower-cased name of the kernel as reported by uname.
# + OS_NAME: The name of the OS as seen by pants.
# + OS_ID: The ID of the current OS as seen by pants.
# Indirectly exposes:
# + get_native_engine_version: Echoes the current native engine version.
# + get_rust_osx_versions: Produces the osx minor versions supported by Rust one per line.
# + get_rust_osx_ids: Produces the BinaryUtil osx os id paths supported by rust, one per line.
# + get_rust_os_ids: Produces the BinaryUtil os id paths supported by rust, one per line.
# Defines:
# + CACHE_ROOT: The pants cache root dir.
# + NATIVE_ENGINE_CACHE_DIR: The native engine binary root cache directory.
# + NATIVE_ENGINE_CACHE_TARGET_DIR: The directory containing all versions of the native engine for
#                                   the current OS.
# + NATIVE_ENGINE_BINARY: The basename of the native engine binary for the current OS.
# + NATIVE_ENGINE_VERSION_RESOURCE: The path of the resource file containing the native engine
#                                   version hash.
# Exposes:
# + calculate_current_hash: Calculates the current native engine version hash and echoes it to
#                           stdout.
# + bootstrap_native_code: Builds target-specific native engine binaries.
source "${REPO_ROOT}/build-support/bin/native/bootstrap.sh"

readonly native_engine_version=$(get_native_engine_version)
readonly cached_bin_path="${NATIVE_ENGINE_CACHE_TARGET_DIR}/${native_engine_version}/${NATIVE_ENGINE_BINARY}"

readonly s3_upload_root="${REPO_ROOT}/build-support/bin/native/s3-upload"
readonly s3_native_engine_dir="${s3_upload_root}/bin/native-engine"

function prepare_chroot() {
  rm -rf "${s3_upload_root}"
  mkdir -p "$(dirname ${s3_native_engine_dir})"
  cp -vpr "${NATIVE_ENGINE_CACHE_DIR}" "${s3_native_engine_dir}"
}

function prepare_osx_versions() {
  for os_id in $(get_rust_osx_ids)
  do
    if [ "${OS_ID}" != "${os_id}" ]
    then
      local target="${s3_native_engine_dir}/${os_id}/${native_engine_version}/${NATIVE_ENGINE_BINARY}"
      mkdir -p "$(dirname ${target})"
      cp -vp "${cached_bin_path}" "${target}"
    fi
  done
}

# Sanity check the locally built native engine binary exists in the first place.
ensure_file_exists "${cached_bin_path}"

# Prepare a chroot for s3 deploy of the binary(ies).
prepare_chroot

# Maybe add copies of the mac native engine binary for the other supported OSX versions.
if [ "${OS_NAME}" == "mac" ]
then
  prepare_osx_versions
fi