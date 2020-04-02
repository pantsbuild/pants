#!/usr/bin/env bash
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../../.. && pwd -P)"

# Defines:
# + CARGO_HOME: The CARGO_HOME of the Pants-controlled rust toolchain.
# Exposes:
# + bootstrap_rust: Bootstraps a Pants-controlled rust toolchain and associated extras.
# shellcheck source=build-support/bin/native/bootstrap_rust.sh
source "${REPO_ROOT}/build-support/bin/native/bootstrap_rust.sh"

if [ ! -h "$0" ]; then
  cat << EOF
This script should be executed via a symbolic link matching the name
of the \$CARGO_HOME binary to run.
EOF
  exit 1
fi
binary="$(basename "$0")"

bootstrap_rust >&2
exec "${CARGO_HOME}/bin/${binary}" "$@"
