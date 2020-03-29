#!/usr/bin/env bash
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../.. && pwd -P)"

cd "$REPO_ROOT" || exit 1

# This script is used to generate pants.pex and particularly to allow us to maintain multiple versions,
# each mapped to a particular snapshot of the source code. The different versions are maintained in
# the CACHE_ROOT, with the current one copied into the build root. This allows us to quickly
# change the specific pants.pex being used. This mechanism is similar to bootstrap_code.sh.

export PY="${PY:-python3}"

# shellcheck source=build-support/common.sh
source "${REPO_ROOT}/build-support/common.sh"
# shellcheck source=build-support/pants_venv
source "${REPO_ROOT}/build-support/pants_venv"
# shellcheck source=build-support/bin/native/bootstrap_code.sh
source "${REPO_ROOT}/build-support/bin/native/bootstrap_code.sh"

readonly PANTS_PEX_CACHE_DIR="${CACHE_ROOT}/bin/pants-pex"

function bootstrap_pants_pex() {
  local pants_pex_version
  pants_pex_version="$(calculate_pants_pex_current_hash)"
  local target_binary="${PANTS_PEX_CACHE_DIR}/pants.${pants_pex_version}.pex"

  if [[ ! -f "${target_binary}" ]]; then
    log "pants.pex is outdated or does not yet exist. Bootstrapping..."
    ./pants --quiet binary src/python/pants/bin:pants_local_binary || exit 1

    mkdir -p "$(dirname "${target_binary}")"
    cp dist/pants_local_binary.pex "${target_binary}"
  fi

  # Ensure that `pants.pex` uses the correct version.
  # NB: the V2 engine does not work if this is a symlink, so we must physically copy the file.
  cp "${target_binary}" pants.pex
}

function calculate_pants_pex_current_hash() {
  # NB: These folder names were found by getting all the dependencies for `pants.pex` by running
  # `./pants dependencies --transitive src/python/pants/bin:pants_local_binary | sort`.
  (
   cd "${REPO_ROOT}" || exit 1
   (uname
    python --version 2>&1
    git ls-files --cached --others --exclude-standard \
     "${REPO_ROOT}/BUILD" \
     "${REPO_ROOT}/BUILD.tools" \
     "${REPO_ROOT}/BUILD_ROOT" \
     "${REPO_ROOT}/pants.toml" \
     "${REPO_ROOT}/3rdparty" \
     "${REPO_ROOT}/build-support/checkstyle" \
     "${REPO_ROOT}/build-support/eslint" \
     "${REPO_ROOT}/build-support/ivy" \
     "${REPO_ROOT}/build-support/mypy" \
     "${REPO_ROOT}/build-support/pylint" \
     "${REPO_ROOT}/build-support/regexes" \
     "${REPO_ROOT}/build-support/scalafmt" \
     "${REPO_ROOT}/build-support/scalastyle" \
     "${REPO_ROOT}/contrib" \
     "${REPO_ROOT}/src/python" \
     "${REPO_ROOT}/pants-plugins" \
   | git hash-object --stdin-paths) | fingerprint_data
  )
}

# Redirect to ensure that we don't interfere with stdout.
activate_pants_venv 1>&2
bootstrap_native_code 1>&2
bootstrap_pants_pex 1>&2
