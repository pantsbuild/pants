#!/usr/bin/env bash
# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 1

# shellcheck source=build-support/common.sh
source "${REPO_ROOT}/build-support/common.sh"

# To solve the chicken and egg problem of https://github.com/pantsbuild/pants/issues/12457, we
# temporarily disable the lockfile. This means that `./pants run` will ignore the lockfile. While
# the script is then running, it will set the option again to generate the lockfile where we want.
export PANTS_PYTHON_SETUP_EXPERIMENTAL_LOCKFILE=""

if is_macos_arm; then
  # Generate the lockfiles with the correct notated interpreter constraints, but make
  # Pants execute with a version of Python that actually runs on MacOS ARM
  unset PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS
  exec ./pants run build-support/bin/_generate_all_lockfiles_helper.py --python-setup-interpreter-constraints="['==3.9.*']"
else
  exec ./pants run build-support/bin/_generate_all_lockfiles_helper.py
fi
