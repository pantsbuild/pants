REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../../.. && pwd -P)

# Defines:
# + CACHE_ROOT: The pants cache directory, ie: ~/.cache/pants.
# Exposes:
# + log: Log a message to the console.
# + fingerprint_data: Fingerprints the data on stdin.
source "${REPO_ROOT}/build-support/common.sh"

readonly RUST_TOOLCHAIN="1.25.0"
readonly RUST_COMPONENTS=(
  "rustfmt-preview"
  "rust-src"
)

readonly rust_toolchain_root="${CACHE_ROOT}/rust"
export CARGO_HOME="${rust_toolchain_root}/cargo"
export RUSTUP_HOME="${rust_toolchain_root}/rustup"

function cargo_bin() {
  "${CARGO_HOME}/bin/rustup" which cargo
}

function ensure_native_build_prerequisites() {
  # Control a pants-specific rust toolchain.
  local -r rustup="${CARGO_HOME}/bin/rustup"

  # NB: rustup installs itself into CARGO_HOME, but fetches toolchains into RUSTUP_HOME.
  if [[ ! -x "${rustup}" ]]
  then
    log "A pants owned rustup installation could not be found, installing via the instructions at" \
        "https://www.rustup.rs ..."
    local -r rustup_tmp=$(mktemp -t pants.rustup.XXXXXX)
    curl https://sh.rustup.rs -sSf > ${rustup_tmp}
    sh ${rustup_tmp} -y --no-modify-path --default-toolchain "${RUST_TOOLCHAIN}" 1>&2
    rm -f ${rustup_tmp}
  fi

  local -r cargo="${CARGO_HOME}/bin/cargo"
  local -r cargo_components_fp=$(echo "${RUST_COMPONENTS[@]}" | fingerprint_data)
  local -r cargo_versioned="cargo-${RUST_TOOLCHAIN}-${cargo_components_fp}"
  if [[ ! -x "${rust_toolchain_root}/${cargo_versioned}" ]]
  then
    (
      cd "${REPO_ROOT}"
      "${rustup}" override set "${RUST_TOOLCHAIN}" >&2
    )
    "${rustup}" component add ${RUST_COMPONENTS[@]} >&2

    ln -fs "$(cargo_bin)" "${rust_toolchain_root}/${cargo_versioned}"
  fi

  local -r symlink_farm_root="${REPO_ROOT}/build-support/bin/native"
  if [[ ! -x "${symlink_farm_root}/.${cargo_versioned}" ]]; then
    (
      cd "${symlink_farm_root}"

      # Kill potentially stale symlinks generated from an older or newer rust toolchain.
      git clean -fdx .

      local -r cargo_bin_dir="$(dirname "$(cargo_bin)")"
      find "${cargo_bin_dir}" -type f | while read executable; do
        if [[ -x "${executable}" ]]; then
          ln -fs "rust_toolchain.sh" "$(basename "${executable}")"
        fi
      done

      ln -fs "$(dirname "${cargo_bin_dir}")/lib/rustlib/src/rust/src"
      ln -fs cargo.sh cargo
      ln -fs cargo.sh ".${cargo_versioned}"
    )
  fi
}
