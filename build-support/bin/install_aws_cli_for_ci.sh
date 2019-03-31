#!/usr/bin/env bash

set -euo pipefail

# Install the AWS CLI in CI jobs.

# This is the fastest, most reliable way to install the AWS CLI on Linux and, particularly, MacOS.
# Using pip is broken on some systems, and package managers (e.g., brew) must be updated prior
# to use, which slows down CI jobs significantly. This is also the installation method recommended
# by AWS, see https://docs.aws.amazon.com/cli/latest/userguide/install-bundle.html.

# We first check if AWS CLI is already installed thanks to Travis's cache.
if [[ ! -d /usr/local/aws ]]; then

  TMPDIR=$(mktemp -d)

  pushd ${TMPDIR}

  curl "https://s3.amazonaws.com/aws-cli/awscli-bundle.zip" -o "awscli-bundle.zip"
  unzip awscli-bundle.zip
  sudo ./awscli-bundle/install --install-dir /usr/local/aws

  popd

fi

# Travis does not cache symlinks (https://docs.travis-ci.com/user/caching/), so we create
# the symlink ourselves everytime to ensure `aws` is discoverable globally.
sudo ln -s /usr/local/aws/bin/aws /usr/local/bin/aws

# Multipart operations aren't supported for anonymous users, so we set the
# threshold high to avoid them being used automatically by the aws cli.
aws configure set default.s3.multipart_threshold 1024MB
