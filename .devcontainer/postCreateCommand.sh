#!/usr/bin/env bash

echo "Making sure the VS Code user can access Pants cache folder..."
# See: https://code.visualstudio.com/remote/advancedcontainers/improve-performance#_use-a-targeted-named-volume
sudo chown -R vscode:vscode /home/vscode/.cache

echo "Installing local git hooks..."
# See: https://www.pantsbuild.org/stable/docs/contributions/development/setting-up-pants#step-3-set-up-a-pre-push-git-hook
build-support/bin/setup.sh

echo "Installing py-sy and memray for CPU and Memory profiling..."
# See: https://www.pantsbuild.org/stable/docs/contributions/development/debugging-and-benchmarking
pip install py-spy memray

echo "Bootstrapping Pants..."
mkdir dist
./pants --version
