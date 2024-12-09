#!/usr/bin/env bash

set -ex

# Since this repository runs VS Code as the non-root "vscode" user,
# we need to be sure the user can access the folder.
# See: https://code.visualstudio.com/remote/advancedcontainers/improve-performance#_use-a-targeted-named-volume
sudo chown -R vscode:vscode /home/vscode/.cache

# Install local git hooks.
# See: https://www.pantsbuild.org/stable/docs/contributions/development/setting-up-pants#step-3-set-up-a-pre-push-git-hook
build-support/bin/setup.sh

# Install `py-sy` and `memray` for CPU and Memory profiling.
# See: https://www.pantsbuild.org/stable/docs/contributions/development/debugging-and-benchmarking
pip install py-spy memray

# Bootstrap Pants.
./pants --version
