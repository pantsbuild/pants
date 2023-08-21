#!/usr/bin/env bash

# Creates an index file for an existing S3 pantsbuild.pants wheel set.

if [[ -z "$1" ]]; then
  echo "Usage: $0 SHA"
  exit 1
fi

set -euox pipefail

REGION=us-east-1

function aws_s3() {
  aws --region="${REGION}" s3 "$@"
}

SHA=$1
WHEEL_DIR=binaries.pantsbuild.org/wheels/pantsbuild.pants

VERSION=$(aws_s3 ls "s3://${WHEEL_DIR}/${SHA}/" | awk '{print $2}' | tr -d "/")

VERSION_DIR="${WHEEL_DIR}/${SHA}/${VERSION}"

for obj in $(aws_s3 ls "s3://${VERSION_DIR}/" | grep "\.whl" | awk '{print $4}'); do
  URL="https://${VERSION_DIR}/${obj}"
  # Note that we replace the + with its escape sequence, as a raw + in a URL is
  # interpreted as a space.
  # Note also that we disable the shellcheck "echo may not expand escape sequences"
  # check, since in this case we don't want to expand escape sequences.
  # shellcheck disable=SC2028
  echo "<br><a href=\"${URL//+/%2B}\">${obj}</a>\n"
done | aws_s3 cp --acl=public-read --content-type=text/html - "s3://${VERSION_DIR}/index.html"
