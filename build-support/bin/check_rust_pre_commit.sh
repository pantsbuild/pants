#!/usr/bin/env bash

# NB: pre-commit runs in the context of GIT_WORK_TREE, ie: pwd == REPO_ROOT

echo "* Running \`./cargo clippy --all\`"
./cargo clippy --all || exit 1
echo "* Checking formatting of Rust files"
./build-support/bin/check_rust_formatting.sh || exit 1
echo "* Checking Rust target headers"
./build-support/bin/check_rust_target_headers.sh || exit 1
