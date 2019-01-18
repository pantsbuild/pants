#!/usr/bin/env bash

# NB: pre-commit runs in the context of GIT_WORK_TREE, ie: pwd == REPO_ROOT

source build-support/common.sh

if [[ -z $FULL_CHECK ]]
then
    export GIT_HOOK=1
fi

# TODO(#7068): Fix all these checks to only act on staged files with
# `git diff --cached --name-only`! See check_header.sh for an example of this command.
echo "* Checking packages" && ./build-support/bin/check_packages.sh || exit 1
echo "* Checking headers" && ./build-support/bin/check_header.sh || exit 1
echo "* Checking for banned imports" && ./build-support/bin/check_banned_imports.sh || exit 1

if git diff master --name-only | grep '\.rs$' > /dev/null; then
  echo "* Checking formatting of rust files" && ./build-support/bin/check_rust_formatting.sh || exit 1
  # Clippy happens on a different shard because of separate caching concerns.
  if [[ "${RUNNING_VIA_TRAVIS_CI_SCRIPT}" != "1" ]]; then
    echo "* Running cargo clippy" && ./build-support/bin/check_clippy.sh || exit 1
  fi
  echo "* Checking rust target headers" && build-support/bin/check_rust_target_headers.sh || exit 1
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

if git diff master --name-only | grep build-support/travis > /dev/null; then
  echo "* Checking .travis.yml generation" && \
  actual_travis_yml=$(<.travis.yml) && \
  expected_travis_yml=$(./pants --quiet run build-support/travis:generate_travis_yml) && \
  [ "${expected_travis_yml}" == "${actual_travis_yml}" ] || \
  die "Travis config generator changed but .travis.yml file not regenerated. See top of that file for instructions."
fi
