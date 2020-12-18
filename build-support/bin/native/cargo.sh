#!/usr/bin/env bash
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../../.. && pwd -P)

# shellcheck source=build-support/common.sh
source "${REPO_ROOT}/build-support/common.sh"

PY="$(determine_python)"
export PY
# Consumed by the cpython crate.
export PYTHON_SYS_EXECUTABLE="${PY}"

# Exports:
# + CARGO_HOME: The CARGO_HOME of the Pants-controlled rust toolchain.
# Exposes:
# + bootstrap_rust: Bootstraps a Pants-controlled rust toolchain and associated extras.
# shellcheck source=build-support/bin/native/bootstrap_rust.sh
source "${REPO_ROOT}/build-support/bin/native/bootstrap_rust.sh"
cargo_bin="${CARGO_HOME}/bin/cargo"

# Exposes:
# + activate_pants_venv: Activate a virtualenv for pants requirements, creating it if needed.
#
# This is necessary for any `cpython`-dependent crates, which need a python interpeter on the PATH.
# shellcheck source=build-support/pants_venv
source "${REPO_ROOT}/build-support/pants_venv"

bootstrap_rust >&2
activate_pants_venv

exec "${cargo_bin}" "$@"
