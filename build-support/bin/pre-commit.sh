#!/usr/bin/env bash

# NB: pre-commit runs in the context of GIT_WORK_TREE, ie: pwd == REPO_ROOT

source build-support/common.sh

if [[ -z $FULL_CHECK ]]
then
    export GIT_HOOK=1
fi

# N.B. This check needs to happen first, before any inadvertent bootstrapping can take place.
echo -n "* Checking native_engine_version: " && ./build-support/bin/check_native_engine_version.sh || exit 1
echo "* Checking packages" && ./build-support/bin/check_packages.sh || exit 1
echo "* Checking headers" && ./build-support/bin/check_header.sh || exit 1
echo "* Checking imports" && ./build-support/bin/isort.sh || \
  die "To fix import sort order, run \`./build-support/bin/isort.sh -f\`"
