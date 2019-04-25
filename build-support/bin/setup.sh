#!/usr/bin/env bash

set -euo pipefail

# Set up the development environment.
# Currently this just installs local git hooks.

REPO_ROOT="$(git rev-parse --show-toplevel)"
pushd "${REPO_ROOT}" > /dev/null
./build-support/bin/install_git_hooks.sh
popd > /dev/null
