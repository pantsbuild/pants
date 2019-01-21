#!/usr/bin/env bash

# NB: pre-commit runs in the context of GIT_WORK_TREE, ie: pwd == REPO_ROOT

source build-support/common.sh

if [[ -z $FULL_CHECK ]]
then
    export GIT_HOOK=1
fi

DIRS_TO_CHECK=(
  src
  tests
  pants-plugins
  examples
  contrib
)

# TODO(#7068): Fix all these checks to only act on staged files with
# `git diff --cached --name-only`!

# TODO: test all the scripts in this file in test_git_hooks.py, remove uses of `|| exit 1`, and add an
# integration test!
set -e

# Read lines of output into the array variable ADDED_FILES, without trailing newlines (-t). See
# https://www.gnu.org/software/bash/manual/html_node/Bash-Builtins.html#index-readarray.
# NB: `readarray` is available on bash >=4.
readarray ADDED_FILES -t < <(./build-support/bin/get_added_files.sh)

echo "* Checking packages"
# TODO: Determine the most *hygienic* way to split an array on the command line in portable bash,
# and stick to it.
./build-support/bin/check_packages.sh "${DIRS_TO_CHECK[@]}"

echo "* Checking headers"
# Read added files from stdin, and ensure check_header_helper.py checks for the current copyright
# year for the intersection of these files with the ones it checks.
# Exporting IGNORE_ADDED_FILES will avoid checking the specific copyright year for added files.
printf "%s\n" "${ADDED_FILES[@]}" \
  | ./build-support/bin/check_header_helper.py "${DIRS_TO_CHECK[@]}"

echo "* Checking for banned imports"
./build-support/bin/check_banned_imports.sh

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
  # TODO: add a test case for this while including a pexrc file, as python checkstyle currently fails
  # quite often with a pexrc available.
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
