#!/usr/bin/env bash

readonly REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../../.. && pwd -P)

# Indirectly exports:
# + LIB_EXTENSION: The extension of native libraries.
# + OS_NAME: The name of the OS as seen by pants.
# + OS_ID: The ID of the current OS as seen by pants.
# Exposes `build_native_code` for building target-specific native engine binaries.
source ${REPO_ROOT}/build-support/bin/native/bootstrap.sh

# Bump this when there is a new OSX released:
readonly OSX_MAX_VERSION=12

readonly NATIVE_ENGINE_VERSION=$(
  ${REPO_ROOT}/pants options --scope=native-engine --name=version --output-format=json | \
  python -c 'import json, sys; print(json.load(sys.stdin)["native-engine.version"]["value"])'
)

readonly CACHE_ROOT=${XDG_CACHE_HOME:-$HOME/.cache}/pants
readonly CACHE_TARGET_DIR=${CACHE_ROOT}/bin/native-engine

cat << EOF > ${REPO_ROOT}/native-engine.bintray.json
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
    "name": "${NATIVE_ENGINE_VERSION}",
    "desc": "The native engine at sha1: ${NATIVE_ENGINE_VERSION}",
    "released": "$(date +'%Y-%m-%d')",
    "vcs_tag": "$(git rev-parse HEAD)",
    "attributes": [],
    "gpgSign": false
  },

  "publish": true,

  "files": [
EOF

function emit_osx_files() {
  # Rust targets OSX 10.7+ as noted here: https://doc.rust-lang.org/book/getting-started.html#tier-1
  for version in $(seq 7 ${OSX_MAX_VERSION}); do
    if (( ${version} < ${OSX_MAX_VERSION} )); then
      local sep=","
    else
      local sep=""
    fi
    # It appears to be the case that upload de-dupes on includePattern keys; so we make a unique
    # includePattern per uploadPattern via a symlink here per OSX version.
    ln -fs \
      ${CACHE_TARGET_DIR}/${OS_ID}/${NATIVE_ENGINE_VERSION}/native-engine \
      ${CACHE_TARGET_DIR}/${OS_ID}/${NATIVE_ENGINE_VERSION}/native-engine.10.${version}
    cat << EOF >> ${REPO_ROOT}/native-engine.bintray.json
    {
      "includePattern": "${CACHE_TARGET_DIR}/${OS_ID}/${NATIVE_ENGINE_VERSION}/native-engine.10.${version}",
      "uploadPattern": "build-support/bin/native-engine/mac/10.${version}/${NATIVE_ENGINE_VERSION}/native-engine"
    }${sep}
EOF
  done
}

function emit_linux_files() {
  native_engine_32="$(build_native_code i686-unknown-linux-gnu)"
  native_engine_64="$(build_native_code x86_64-unknown-linux-gnu)"
  cat << EOF >> ${REPO_ROOT}/native-engine.bintray.json
    {
      "includePattern": "${native_engine_32}",
      "uploadPattern": "build-support/bin/native-engine/linux/i386/${NATIVE_ENGINE_VERSION}/native-engine"
    },
    {
      "includePattern": "${native_engine_64}",
      "uploadPattern": "build-support/bin/native-engine/linux/x86_64/${NATIVE_ENGINE_VERSION}/native-engine"
    }
EOF
}

if [ "${OS_NAME}" == "mac" ]; then
  emit_osx_files
else
  emit_linux_files
fi

cat << EOF >> ${REPO_ROOT}/native-engine.bintray.json
  ]
}
EOF
