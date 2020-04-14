#!/usr/bin/env bash
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

 REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../../.. && pwd -P)"

 # shellcheck source=build-support/bin/native/calculate_engine_hash.sh
 source "${REPO_ROOT}/build-support/bin/native/calculate_engine_hash.sh"

 # shellcheck source=build-support/pants_venv
 source "${REPO_ROOT}/build-support/pants_venv"

 export PY="${PY:-python3}"
 activate_pants_venv 1>&2  # Redirect to ensure that we don't interfere with stdout.

 calculate_current_hash
