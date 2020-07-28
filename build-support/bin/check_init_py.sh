#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}"

DIRS_TO_CHECK=(
  src
  tests
  pants-plugins
  examples
  build-support/bin
)

non_empty_files=$(find "${DIRS_TO_CHECK[@]}" -type f -name "__init__.py" -not -empty)

if (( ${#non_empty_files[@]} > 0 ))
then
  echo "ERROR: All '__init__.py' files should be empty, but the following contain code:"
  echo "---"
  echo "${non_empty_files[*]}"
  exit 1
fi
