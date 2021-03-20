#!/usr/bin/env bash

set -euo pipefail

# Install the AWS CLI in CI jobs.

# This is the fastest, most reliable way to install the AWS CLI on Linux and, particularly, MacOS.
# Using pip is broken on some systems, and package managers (e.g., brew) must be updated prior
# to use, which slows down CI jobs significantly. This is also the installation method recommended
# by AWS, see https://docs.aws.amazon.com/cli/latest/userguide/install-bundle.html.

source build-support/common.sh

AWS_CLI_ROOT="${HOME}/.aws_cli"
AWS_CLI_BIN="${AWS_CLI_ROOT}/bin/aws"

# We first check if AWS CLI is already installed thanks to Travis's cache.
if [[ ! -x "${AWS_CLI_BIN}" ]]; then

  TMPDIR=$(mktemp -d)

  pushd "${TMPDIR}"

  curl --fail "https://s3.amazonaws.com/aws-cli/awscli-bundle.zip" -o "awscli-bundle.zip"
  unzip awscli-bundle.zip
  ./awscli-bundle/install --install-dir "${AWS_CLI_ROOT}"

  popd

fi

# We symlink so that `aws` is discoverable on the $PATH. Our Docker image does not have `sudo`, whereas
# we need it for macOS to symlink into /usr/local/bin.
symlink="/usr/local/bin/aws"
if [[ ! -L "${symlink}" ]]; then
  case "$(uname)" in
    "Darwin")
      sudo ln -s "${AWS_CLI_BIN}" "${symlink}"
      ;;
    *)
      ln -s "${AWS_CLI_BIN}" "${symlink}"
      ;;
  esac
fi

# Multipart operations aren't supported for anonymous users, so we set the
# threshold high to avoid them being used automatically by the aws cli.
aws configure set default.s3.multipart_threshold 1024MB
