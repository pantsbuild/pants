#!/usr/bin/env bash

# NB: pre-commit runs in the context of GIT_WORK_TREE, ie: pwd == REPO_ROOT

source build-support/common.sh

echo "Checking packages" && ./build-support/bin/check_packages.sh || exit 1
echo "Checking imports" && GIT_HOOK=1 ./build-support/bin/isort.sh || \
  die "To fix import sort order, run \`build-support/bin/isort.sh -f\`"
echo "Checking headers" && ./build-support/bin/check_header.sh || exit 1
echo "Success"
