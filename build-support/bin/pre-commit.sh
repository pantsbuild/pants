#!/usr/bin/env bash

# NB: pre-commit runs in the context of GIT_WORK_TREE, ie: pwd == REPO_ROOT

source build-support/common.sh

if [[ -z $FULL_CHECK ]]
then
    export GIT_HOOK=1
fi

echo "* Checking packages" && ./build-support/bin/check_packages.sh || exit 1
echo "* Checking headers" && ./build-support/bin/check_header.sh || exit 1
echo "* Checking for banned imports" && ./build-support/bin/check_banned_imports.sh || exit 1

if git diff master --name-only | grep '\.rs$' > /dev/null; then
  echo "* Checking formatting of rust files" && "$(pwd)/build-support/bin/check_rust_formatting.sh" || exit 1
  echo "* Running cargo clippy" && build-support/bin/ci.sh -bs || exit 1
fi

echo "* Checking for bad shell patterns" && ./build-support/bin/check_shell.sh || exit 1

$(git rev-parse --verify master > /dev/null 2>&1)
if [[ $? -eq 0 ]]; then
  echo "* Checking imports" && ./build-support/bin/isort.sh || \
    die "To fix import sort order, run \`\"$(pwd)/build-support/bin/isort.sh\" -f\`"
  # TODO(CMLivingston) Make lint use `-q` option again after addressing proper workunit labeling:
  # https://github.com/pantsbuild/pants/issues/6633
  echo "* Checking lint" && ./pants --exclude-target-regexp='testprojects/.*' --changed-parent=master lint || exit 1
else
  # When travis builds a tag, it does so in a shallow clone without master fetched, which
  # fails in pants changed.
  echo "* Skipping import/lint checks in partial working copy."
fi
