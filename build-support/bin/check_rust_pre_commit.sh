#!/usr/bin/env bash

# NB: pre-commit runs in the context of GIT_WORK_TREE, ie: pwd == REPO_ROOT
source build-support/common.sh

if is_macos_arm; then
  echo "* Running \`./cargo clippy\`"
  ./cargo clippy || exit 1
else
  echo "* Running \`./cargo clippy --all\`"
  ./cargo clippy --all || exit 1
fi

echo "* Checking formatting of Rust files"
./build-support/bin/check_rust_formatting.sh || exit 1
