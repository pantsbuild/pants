#!/usr/bin/env bash

set -euo pipefail

# Expects a sibling dir called "pantsbuild.org" containing a clean clone
# of the https://github.com/pantsbuild/pantsbuild.org repo.

DIFF_FILE=$(mktemp)

git diff main docs/ > "${DIFF_FILE}"

cd ../pantsbuild.org

git diff --stat --exit-code > /dev/null || (echo "Expected clean git state in the pantsbuild/pantsbuild.org repo" && exit 1)

git checkout main

git apply --allow-empty "${DIFF_FILE}"

rm -f "${DIFF_FILE}"

npm start
