#!/usr/bin/env bash

echo "Making sure the VS Code user can access Pants cache folder..."
# See: https://code.visualstudio.com/remote/advancedcontainers/improve-performance#_use-a-targeted-named-volume
sudo chown -R vscode:vscode /home/vscode/.cache

echo "Installing local git hooks..."
# See: https://www.pantsbuild.org/stable/docs/contributions/development/setting-up-pants#step-3-set-up-a-pre-push-git-hook
build-support/bin/setup.sh

echo "Bootstrapping Pants..."
./pants --version
