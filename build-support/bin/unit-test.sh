#!/usr/bin/env bash

# We use some subshell pipelines to collect target lists, make sure target collection failing
# fails the build.
set -o pipefail

./pants test $(./pants filter tests/python/pants_test:: --tag=-integration --filter-type=python_tests)
