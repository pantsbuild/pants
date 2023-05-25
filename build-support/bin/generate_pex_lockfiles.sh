#!/usr/bin/env bash
# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

set -euo pipefail

# A convenience script so we don't forget to update Lambdex when we update Pex.

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 1

# shellcheck source=build-support/common.sh
source "${REPO_ROOT}/build-support/common.sh"

./pants generate-lockfiles --resolve=python-default
./pants run build-support/bin/generate_builtin_lockfiles.py -- lambdex
