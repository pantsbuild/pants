#!/usr/bin/env bash

set -e

readonly REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../../.. && pwd -P)
source ${REPO_ROOT}/build-support/common.sh

# Defines:
# + LIB_EXTENSION: The extension of native libraries.
# + KERNEL: The lower-cased name of the kernel as reported by uname.
# + OS_NAME: The name of the OS as seen by pants.
# + OS_ID: The ID of the current OS as seen by pants.
source ${REPO_ROOT}/build-support/bin/native/detect_os.sh

readonly NATIVE_ROOT="${REPO_ROOT}/src/rust/engine"
readonly MODE=debug
readonly MODE_FLAG=

readonly NATIVE_ENGINE_VERSION_RESOURCE="${REPO_ROOT}/src/python/pants/engine/subsystem/native_engine_version"

readonly CACHE_ROOT=${XDG_CACHE_HOME:-$HOME/.cache}/pants
readonly CACHE_TARGET_DIR=${CACHE_ROOT}/bin/native-engine/${OS_ID}

function calculate_current_hash() {
  # Cached and unstaged files, with ignored files excluded.
  git ls-files -c -o --exclude-standard ${NATIVE_ROOT} | \
    git hash-object -t blob --stdin-paths | fingerprint_data
}

function ensure_build_prerequisites() {
  # Control a pants-specific rust toolchain, optionally ensuring the given target toolchain is
  # installed.
  local readonly target=$1

  export CARGO_HOME=${CACHE_ROOT}/rust-toolchain
  export RUSTUP_HOME=${CARGO_HOME}

  if [[ ! -x "${RUSTUP_HOME}/bin/rustup" ]]
  then
    log "A pants owned rustup installation could not be found, installing via the instructions at" \
        "https://www.rustup.rs ..."
    local readonly rustup=$(mktemp -t pants.rustup.XXXXX)
    curl https://sh.rustup.rs -sSf > ${rustup}
    sh ${rustup} -y --no-modify-path 1>&2
    rm -f ${rustup}
    ${RUSTUP_HOME}/bin/rustup override set stable 1>&2
  fi

  if [[ -n "${target}" ]]
  then
    if ! ${RUSTUP_HOME}/bin/rustup target list | grep -E "${target} \((default|installed)\)" &> /dev/null
    then
      ${RUSTUP_HOME}/bin/rustup target add ${target}
    fi
  fi
}

function build_native_code() {
  # Builds the native code, optionally taking an explicit target triple arg, and echos the path of
  # the built binary.
  local readonly target=$1
  ensure_build_prerequisites ${target}

  local readonly cargo="${CARGO_HOME}/bin/cargo"
  local readonly build_cmd="${cargo} build --manifest-path ${NATIVE_ROOT}/Cargo.toml ${MODE_FLAG}"
  if [[ -z "${target}" ]]
  then
    ${build_cmd} || die
    echo "${NATIVE_ROOT}/target/${MODE}/libengine.${LIB_EXTENSION}"
  else
    ${build_cmd} --target ${target} || echo "FAILED to build for target ${target}"
    echo "${NATIVE_ROOT}/target/${target}/${MODE}/libengine.${LIB_EXTENSION}"
  fi
}

function bootstrap_native_code() {
  # Bootstraps the native code and overwrites the native_engine_version to the resulting hash
  # version if needed.
  local native_engine_version="$(calculate_current_hash)"
  local target_binary="${CACHE_TARGET_DIR}/${native_engine_version}/native-engine"
  if [ ! -f "${target_binary}" ]
  then
    local readonly native_binary="$(build_native_code)"

    # Pick up Cargo.lock changes if any caused by the `cargo build`.
    native_engine_version="$(calculate_current_hash)"
    target_binary="${CACHE_TARGET_DIR}/${native_engine_version}/native-engine"

    mkdir -p "$(dirname ${target_binary})"
    cp "${native_binary}" ${target_binary}

    # NB: The resource file emitted/over-written below is used by the `Native` subsystem to default
    # the native engine library version used by pants. More info can be read here:
    #  src/python/pants/engine/subsystem/README.md
    echo ${native_engine_version} > ${NATIVE_ENGINE_VERSION_RESOURCE}
  fi
}
