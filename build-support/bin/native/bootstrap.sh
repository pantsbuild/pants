#!/usr/bin/env bash

# Defines:
# + CACHE_TARGET_DIR: The directory containing all versions of the native engine for the current OS.
# Exposes:
# + build_native_code: Builds target-specific native engine binaries.

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../../.. && pwd -P)
source ${REPO_ROOT}/build-support/common.sh

# Defines:
# + RUST_OSX_MIN_VERSION: The minimum minor version of OSX supported by Rust; eg 7 for OSX 10.7.
# + OSX_MAX_VERSION: The current latest OSX minor version; eg 12 for OSX Sierra 10.12
# + LIB_EXTENSION: The extension of native libraries.
# + KERNEL: The lower-cased name of the kernel as reported by uname.
# + OS_NAME: The name of the OS as seen by pants.
# + OS_ID: The ID of the current OS as seen by pants.
# Exposes:
# + get_native_engine_version: Echoes the current native engine version.
# + get_rust_osx_versions: Produces the osx minor versions supported by Rust one per line.
# + get_rust_os_ids: Produces the BinaryUtil os id paths supported by rust, one per line.
source ${REPO_ROOT}/build-support/bin/native/utils.sh

readonly NATIVE_ROOT="${REPO_ROOT}/src/rust/engine"
readonly NATIVE_ENGINE_MODULE="native_engine"
readonly NATIVE_ENGINE_BINARY="${NATIVE_ENGINE_MODULE}.so"
readonly NATIVE_ENGINE_VERSION_RESOURCE="${REPO_ROOT}/src/python/pants/engine/subsystem/native_engine_version"
readonly CFFI_BOOTSTRAPPER="${REPO_ROOT}/build-support/native-engine/bootstrap_cffi.py"

# N.B. Set $MODE to "debug" to generate a binary with debugging symbols.
readonly MODE="${MODE:-release}"
case "$MODE" in
  debug) MODE_FLAG="" ;;
  *) MODE_FLAG="--release" ;;
esac

readonly CACHE_ROOT=${XDG_CACHE_HOME:-$HOME/.cache}/pants
readonly CACHE_TARGET_DIR=${CACHE_ROOT}/bin/native-engine/${OS_ID}

function calculate_current_hash() {
  # Cached and unstaged files, with ignored files excluded.
  # NB: We fork a subshell because one or both of `ls-files`/`hash-object` are
  # sensitive to the CWD, and the `--work-tree` option doesn't seem to resolve that.
  (
   cd ${REPO_ROOT}
   git ls-files -c -o --exclude-standard \
     "${NATIVE_ROOT}" \
     "${REPO_ROOT}/src/python/pants/engine/subsystem/native.py" \
   | git hash-object -t blob --stdin-paths | fingerprint_data
  )
}

function ensure_cffi_sources() {
  # N.B. Here we assume that higher level callers have already setup the pants' venv and $PANTS_SRCPATH.
  PYTHONPATH="${PANTS_SRCPATH}:${PYTHONPATH}" python "${CFFI_BOOTSTRAPPER}" "$@"
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
    local readonly rustup=$(mktemp -t pants.rustup.XXXXXX)
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
  local target_binary="${CACHE_TARGET_DIR}/${native_engine_version}/${NATIVE_ENGINE_BINARY}"
  local cffi_output_dir="${NATIVE_ROOT}/src/cffi"
  local cffi_env_script="${cffi_output_dir}/${NATIVE_ENGINE_MODULE}.sh"
  if [ ! -f "${target_binary}" ]
  then
    ensure_cffi_sources "${cffi_output_dir}"
    source "${cffi_env_script}"
    local readonly native_binary="$(build_native_code)"

    # If bootstrapping the native engine fails, don't attempt to run pants
    # afterwards.
    if ! [ -f "${native_binary}" ]
    then
      die "Failed to build native engine."
    fi

    # Pick up Cargo.lock changes if any caused by the `cargo build`.
    native_engine_version="$(calculate_current_hash)"
    target_binary="${CACHE_TARGET_DIR}/${native_engine_version}/${NATIVE_ENGINE_BINARY}"

    mkdir -p "$(dirname ${target_binary})"
    cp "${native_binary}" "${target_binary}"

    # NB: The resource file emitted/over-written below is used by the `Native` subsystem to default
    # the native engine library version used by pants. More info can be read here:
    #  src/python/pants/engine/subsystem/README.md
    echo ${native_engine_version} > ${NATIVE_ENGINE_VERSION_RESOURCE}
  fi
}
