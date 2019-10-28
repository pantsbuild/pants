#!/bin/bash -e

function nuke_if_too_big() {
  path=$1
  limit_mb=$2
  actual_mb=$(du -m -d0 ${path} | cut -f 1)
  echo "Size of ${path}: ${actual_mb}MB"
  if (( ${actual_mb} > ${limit_mb} )); then
    echo "${path} is too large, nuking it."
    rm -rf ${path}
  fi
}


# Prune the dirs we cache on travis if they get too big.
# Note that some of these dirs are only relevant to native code building shards, and others only to
# pants running shards. However there's no harm in checking them all in both cases.

nuke_if_too_big ${HOME}/.pants_pyenv 9999
nuke_if_too_big ${HOME}/.aws_cli 9999
nuke_if_too_big ${HOME}/.cache/pants/lmdb_store 1024
nuke_if_too_big ${HOME}/.cache/pants/tools 9999
nuke_if_too_big ${HOME}/.cache/pants/zinc 9999
nuke_if_too_big ${HOME}/.ivy2/pants 9999
nuke_if_too_big ${HOME}/.npm 9999
nuke_if_too_big ${HOME}/.cache/pants/rust/cargo 9999
nuke_if_too_big build-support/virtualenvs 9999
nuke_if_too_big src/rust/engine/target 9999
