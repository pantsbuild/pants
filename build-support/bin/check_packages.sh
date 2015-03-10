#!/usr/bin/env bash

set -euo pipefail
IFS=$'\n\t'

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd ${REPO_ROOT}

DIRS_TO_CHECK=(
  src
  tests
  pants-plugins
  examples
  contrib
)

non_empty_files=$(find ${DIRS_TO_CHECK[@]} -type f -name "__init__.py" -not -empty)

bad_files=()
for package_file in ${non_empty_files}
do
  if [[ "$(sed -E -e 's/^[[:space:]]+//' -e 's/[[:space:]]+$//' ${package_file})" != \
        "__import__('pkg_resources').declare_namespace(__name__)" ]]
  then
    bad_files+=(${package_file})
  fi
done

if (( ${#bad_files[@]} > 0 ))
then
  echo "ERROR: All '__init__.py' files should be empty or else only contain a namespace"
  echo "declaration, but the following contain code:"
  echo "---"
  echo "${bad_files[*]}"
  exit 1
fi
