#!/bin/bash -e

function nuke_if_too_big() {
  path=$1
  limit_mb=$2
  echo "## Pruning ${path} (if larger than ${limit_mb}MB)..."
  if [[ -d "${path}" ]]; then
    actual_mb=$(du -m -d0 "${path}" | cut -f 1)
    echo "Size of ${path}: ${actual_mb}MB"
    if (( actual_mb > limit_mb )); then
      echo "${path} is too large, nuking it."
      rm -rf "${path}"
      # Travis cache uploads will fail if a directory does not exist.
      #   see https://docs.travis-ci.com/user/caching/#caches-and-read-permissions
      mkdir -p "${path}"
    else
      echo "${path} is not too large, leaving it."
    fi
  else
    echo "Directory ${path} doesn't exist."
  fi
}


# Prune the dirs we cache on travis if they get too big.
# Note that some of these dirs are only relevant to native code building shards, and others only to
# pants running shards. And some only to linux or only to osx.
# However there's no harm in checking them all in all cases.

nuke_if_too_big "${HOME}/.pants_pyenv" 512
nuke_if_too_big "${HOME}/.aws_cli" 128
nuke_if_too_big "${HOME}/.cache/pants/pants_dev_deps" 128
nuke_if_too_big "${HOME}/.cache/pants/tools" 128
nuke_if_too_big src/rust/engine/target 3072

# Note that we don't prune all of ${HOME}/.cache/pants/rust/cargo, as it mostly contains git
# checkouts of rust deps, notably grpc, which is huge and takes forever to clone.
# We don't expect that data to grow rapidly anyway.
nuke_if_too_big "${HOME}/.cache/pants/rust/cargo/registry" 512
