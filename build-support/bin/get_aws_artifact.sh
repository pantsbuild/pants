#!/usr/bin/env bash

set -euo pipefail

AWS_BUCKET=$1
AWS_KEY=$2
FILE_NAME=$3


AWS_URL=s3://${AWS_BUCKET}/${AWS_KEY}

# Note that in the aws cli --no-sign-request allows access to public S3 buckets without
# credentials, as long as we specify the region.

# First check that there's only one version of the object on S3, to detect malicious overwrites.
NUM_VERSIONS=$(aws --no-sign-request --region us-east-1 s3api list-object-versions \
  --bucket "${AWS_BUCKET}" --prefix "${AWS_KEY}" --max-items 2 \
  | jq '.Versions | length')
[ "${NUM_VERSIONS}" == "1" ] || (echo "Error: Found ${NUM_VERSIONS} versions for ${AWS_URL}" && exit 1)

# Now fetch the file
aws --no-sign-request --region us-east-1 s3 cp "${AWS_URL}" "${FILE_NAME}"

# Make it executable
chmod 755 "${FILE_NAME}"
