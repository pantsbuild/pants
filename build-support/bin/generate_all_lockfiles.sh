#!/usr/bin/env bash
# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

set -euo pipefail

# To solve the chicken and egg problem of https://github.com/pantsbuild/pants/issues/12457, we
# temporarily disable the lockfile. This means that `./pants run` will ignore the lockfile. While
# the script is then running, it will set the option again to generate the lockfile where we want.
export PANTS_PYTHON_SETUP_EXPERIMENTAL_LOCKFILE=""

exec ./pants run build-support/bin/_generate_all_lockfiles_helper.py
