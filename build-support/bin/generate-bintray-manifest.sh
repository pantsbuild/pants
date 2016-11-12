#!/usr/bin/env bash

readonly REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../.. && pwd -P)
readonly NATIVE_ENGINE_VERSION=$(
  ${REPO_ROOT}/pants options --scope=native-engine --name=version --output-format=json | \
  python -c 'import json, sys; print(json.load(sys.stdin)["native-engine.version"]["value"])'
)

# TODO(John Sirois): Eliminate this replication of BinaryUtil logic internal to pants code when
# https://github.com/pantsbuild/pants/issues/4006 is complete.
readonly KERNEL=$(uname -s | tr '[:upper:]' '[:lower:]')
case "${KERNEL}" in
  linux)
    readonly EXTENSION=so
    readonly OS_ID=linux/$(uname -m)
    ;;
  darwin)
    readonly EXTENSION=dylib
    readonly OS_ID=mac/$(sw_vers -productVersion | cut -d: -f2 | tr -d ' \t' | cut -d. -f1-2)
    ;;
  *)
    die "Unknown kernel ${KERNEL}, cannot bootstrap pants native code!"
    ;;
esac

readonly CACHE_ROOT=${XDG_CACHE_HOME:-$HOME/.cache}/pants
readonly CACHE_TARGET_DIR=${CACHE_ROOT}/bin/native-engine

cat << EOF > ${REPO_ROOT}/native-engine.bintray.json
{
  "package": {
    "name": "native-engine",
    "repo": "bin",
    "subject": "pantsbuild",
    "desc": "The pants native engine library.",
    "website_url": "http://www.pantsbuild.org",
    "issue_tracker_url": "https://github.com/pantsbuild/pants/issues",
    "vcs_url": "https://github.com/pantsbuild/pants.git",
    "github_use_tag_release_notes": false,
    "licenses": ["Apache-2.0"],
    "labels": [],
    "public_download_numbers": true,
    "public_stats": true,
    "attributes": []
  },

  "version": {
    "name": "${NATIVE_ENGINE_VERSION}",
    "desc": "The native engine at sha1: ${NATIVE_ENGINE_VERSION}",
    "released": "$(date +'%Y-%m-%d')",
    "vcs_tag": "$(git rev-parse HEAD)",
    "attributes": [],
    "gpgSign": false
  },

  "files": [
    {
       "includePattern": "${CACHE_TARGET_DIR}/${OS_ID}/${NATIVE_ENGINE_VERSION}/native-engine",
       "uploadPattern": "build-support/bin/native-engine/${OS_ID}/${NATIVE_ENGINE_VERSION}/native-engine"
    }
  ],

  "publish": true
}
EOF
