#!/usr/bin/env bash
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../.. && pwd -P)"

# This script is used to generate pants.pex and particularly to allow us to maintain multiple versions,
# each mapped to a particular snapshot of the source code. The different versions are maintained in
# the CACHE_ROOT, with the current one symlinked into the build root. This allows us to quickly
# change the specific pants.pex being used. This mechanism is similar to bootstrap_code.sh.

# shellcheck source=build-support/common.sh
source "${REPO_ROOT}/build-support/common.sh"

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
  # NB: We fork a subshell because one or both of `ls-files`/`hash-object` are
  # sensitive to the CWD, and the `--work-tree` option doesn't seem to resolve that.
  #
  # Assumes we're in the venv that will be used to build the native engine.
  (
   cd "${REPO_ROOT}" || exit 1
   (uname
    python --version 2>&1
    git ls-files --cached --others --exclude-standard \
     "${REPO_ROOT}/3rdparty" \
     "${REPO_ROOT}/src" \
     "${REPO_ROOT}/tests" \
     "${REPO_ROOT}/contrib" \
     "${REPO_ROOT}/pants-plugins" \
     "${REPO_ROOT}/pants*.ini" \
     "${REPO_ROOT}/BUILD" \
     "${REPO_ROOT}/BUILD.tools" \
   | git hash-object --stdin-paths) | fingerprint_data
  )
}

bootstrap_pants_pex
