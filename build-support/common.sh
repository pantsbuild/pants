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


function log() {
  echo -e "$@" 1>&2
}

function die() {
  (($# > 0)) && log "\n$@"
  exit 1
}

# Initialization for elapsed()
if [ -z "$elapsed_start_time" ] ; then
  export elapsed_start_time=$(date +'%s')
fi

function elapsed() {
  now=$(date '+%s')
  elapsed_secs=$(($now - $elapsed_start_time))
  echo $elapsed_secs | awk '{printf "%02d:%02d\n",int($1/60), int($1%60)}'
}

function banner() {
  echo
  echo "[== $(elapsed) $@ ==]"
  echo
}

function fingerprint_data() {
  openssl md5 | cut -d' ' -f2
}
