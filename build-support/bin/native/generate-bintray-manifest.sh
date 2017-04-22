#!/usr/bin/env bash

set -e

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../../.. && pwd -P)

# Indirectly defines:
# + RUST_OSX_MIN_VERSION: The minimum minor version of OSX supported by Rust; eg 7 for OSX 10.7.
# + OSX_MAX_VERSION: The current latest OSX minor version; eg 12 for OSX Sierra 10.12
# + LIB_EXTENSION: The extension of native libraries.
# + KERNEL: The lower-cased name of the kernel as reported by uname.
# + OS_NAME: The name of the OS as seen by pants.
# + OS_ID: The ID of the current OS as seen by pants.
# Indirectly exposes:
# + get_native_engine_version: Echoes the current native engine version.
# + get_rust_osx_versions: Produces the osx minor versions supported by Rust one per line.
# + get_rust_os_ids: Produces the BinaryUtil os id paths supported by rust, one per line.
# Defines:
# + CACHE_TARGET_DIR: The directory containing all versions of the native engine for the current OS.
# Exposes:
# + build_native_code: Builds target-specific native engine binaries.
source ${REPO_ROOT}/build-support/bin/native/bootstrap.sh

readonly native_engine_version=$(get_native_engine_version)

cat << __EOF__ > ${REPO_ROOT}/native-engine.bintray.json
{
  "package": {
    "subject": "pantsbuild",
    "repo": "bin",
    "name": "native-engine",
    "desc": "The pants native engine library.",
    "website_url": "http://www.pantsbuild.org",
    "issue_tracker_url": "https://github.com/pantsbuild/pants/issues",
    "vcs_url": "https://github.com/pantsbuild/pants.git",
    "licenses": ["Apache-2.0"],
    "public_download_numbers": true,
    "public_stats": true,
    "github_use_tag_release_notes": false,
    "attributes": [],
    "labels": []
  },

  "version": {
    "name": "${native_engine_version}",
    "desc": "The native engine at sha1: ${native_engine_version}",
    "released": "$(date +'%Y-%m-%d')",
    "vcs_tag": "$(git rev-parse HEAD)",
    "attributes": [],
    "gpgSign": false
  },

  "publish": true,

  "files": [
__EOF__

function emit_osx_files() {
  local readonly cached_bin_path="${CACHE_TARGET_DIR}/${native_engine_version}/${NATIVE_ENGINE_BINARY}"
  ensure_file_exists "${cached_bin_path}"

  # Rust targets OSX 10.7+ as noted here: https://doc.rust-lang.org/book/getting-started.html#tier-1
  for version in $(get_rust_osx_versions)
  do
    local cached_link_path="${cached_bin_path}.10.${version}"

    if (( ${version} < ${OSX_MAX_VERSION} ))
    then
      local sep=","
    else
      local sep=""
    fi
    # It appears to be the case that upload de-dupes on includePattern keys; so we make a unique
    # includePattern per uploadPattern via a symlink here per OSX version.
    ln -fs "${cached_bin_path}" "${cached_link_path}"
    cat << __EOF__ >> ${REPO_ROOT}/native-engine.bintray.json
    {
      "includePattern": "${cached_link_path}",
      "uploadPattern": "build-support/bin/native-engine/mac/10.${version}/${native_engine_version}/${NATIVE_ENGINE_BINARY}"
    }${sep}
__EOF__
  done
}

function emit_linux_files() {
  local readonly cached_bin_path="${CACHE_TARGET_DIR}/${native_engine_version}/${NATIVE_ENGINE_BINARY}"
  ensure_file_exists "${cached_bin_path}"

  cat << __EOF__ >> ${REPO_ROOT}/native-engine.bintray.json
    {
      "includePattern": "${cached_bin_path}",
      "uploadPattern": "build-support/bin/native-engine/linux/x86_64/${native_engine_version}/${NATIVE_ENGINE_BINARY}"
    }
__EOF__
}

if [ "${OS_NAME}" == "mac" ]
then
  emit_osx_files
else
  emit_linux_files
fi

cat << __EOF__ >> ${REPO_ROOT}/native-engine.bintray.json
  ]
}
__EOF__
