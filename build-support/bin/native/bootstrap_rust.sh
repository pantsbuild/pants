REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../../.. && pwd -P)"

# Defines:
# + CACHE_ROOT: The pants cache directory, ie: ~/.cache/pants.
# Exposes:
# + log: Log a message to the console.
# + fingerprint_data: Fingerprints the data on stdin.
source "${REPO_ROOT}/build-support/common.sh"

rust_toolchain_root="${CACHE_ROOT}/rust"
export CARGO_HOME="${rust_toolchain_root}/cargo"
export RUSTUP_HOME="${rust_toolchain_root}/rustup"

RUSTUP="${CARGO_HOME}/bin/rustup"

function cargo_bin() {
  "${RUSTUP}" which cargo
}

function bootstrap_rust() {
  RUST_TOOLCHAIN="$(cat ${REPO_ROOT}/rust-toolchain)"
  RUST_COMPONENTS=(
    "rustfmt-preview"
    "rust-src"
    "clippy-preview"
  )

  # Control a pants-specific rust toolchain.
  if [[ ! -x "${RUSTUP}" ]]; then
    # NB: rustup installs itself into CARGO_HOME, but fetches toolchains into RUSTUP_HOME.
    log "A pants owned rustup installation could not be found, installing via the instructions at" \
        "https://www.rustup.rs ..."
    # This is the recommended installation method for Unix when '--proto' is not available on curl
    # (as in CentOS6), see # https://github.com/rust-lang/rustup.rs#other-installation-methods.
    # The workaround was added in https://github.com/rust-lang/rustup.rs/pull/1803.
    curl https://sh.rustup.rs -sSf | sh -s -- -y --no-modify-path --default-toolchain none 1>&2
  fi

  local -r cargo="${CARGO_HOME}/bin/cargo"
  local -r cargo_components_fp=$(echo "${RUST_COMPONENTS[@]}" | fingerprint_data)
  local -r cargo_versioned="cargo-${RUST_TOOLCHAIN}-${cargo_components_fp}"
  if [[ ! -x "${rust_toolchain_root}/${cargo_versioned}" || "${RUST_TOOLCHAIN}" == "nightly" ]]; then
    # If rustup was already bootstrapped against a different toolchain in the past, freshen it and
    # ensure the toolchain and components we need are installed.
    "${RUSTUP}" self update
    "${RUSTUP}" toolchain install ${RUST_TOOLCHAIN}
    "${RUSTUP}" component add --toolchain ${RUST_TOOLCHAIN} ${RUST_COMPONENTS[@]} >&2

    symlink_target="$(python -c 'import os, sys; print(os.path.relpath(*sys.argv[1:]))' "$(RUSTUP_TOOLCHAIN="${RUST_TOOLCHAIN}" cargo_bin)" "${rust_toolchain_root}")"
    ln -fs "${symlink_target}" "${rust_toolchain_root}/${cargo_versioned}"
  fi

  if [[ ! -x "${CARGO_HOME}/bin/cargo-ensure-installed" ]]; then
    "${cargo}" install cargo-ensure-installed
  fi
  "${cargo}" ensure-installed --package cargo-ensure-installed --version 0.2.1

  local -r symlink_farm_root="${REPO_ROOT}/build-support/bin/native"
  if [[ ! -x "${symlink_farm_root}/.${cargo_versioned}" ]]; then
    (
      cd "${symlink_farm_root}"

      # Kill potentially stale symlinks generated from an older or newer rust toolchain.
      git clean -fdx .

      ln -fs "rust_toolchain.sh" rustup
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
