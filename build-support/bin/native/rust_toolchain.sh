#!/usr/bin/env bash

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../../.. && pwd -P)"

# Defines:
# + CARGO_HOME: The CARGO_HOME of the Pants-controlled rust toolchain.
# Exposes:
# + ensure_native_build_prerequisites: Bootstraps a Pants-controlled rust toolchain and associated
#                                      extras.
source "${REPO_ROOT}/build-support/bin/native/bootstrap_rust.sh"

if [ ! -h $0 ]; then
  cat << EOF
This script should be executed via a symbolic link matching the name
of the \$CARGO_HOME binary to run.
EOF
  exit 1
fi
readonly binary="$(basename "$0")"

ensure_native_build_prerequisites >&2
exec "${CARGO_HOME}/bin/${binary}" "$@"
