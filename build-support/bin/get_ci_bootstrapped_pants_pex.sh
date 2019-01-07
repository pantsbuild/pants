#!/usr/bin/env bash

set -euo pipefail

BOOTSTRAPPED_PEX_BUCKET=$1
BOOTSTRAPPED_PEX_KEY=$2

BOOTSTRAPPED_PEX_URL=s3://${BOOTSTRAPPED_PEX_BUCKET}/${BOOTSTRAPPED_PEX_KEY}

# Note that in the aws cli --no-sign-request allows access to public S3 buckets without
# credentials, as long as we specify the region.

# First check that there's only one version of the object on S3, to detect malicious overwrites.
NUM_VERSIONS=$(aws --no-sign-request --region us-east-1 s3api list-object-versions \
  --bucket ${BOOTSTRAPPED_PEX_BUCKET} --prefix ${BOOTSTRAPPED_PEX_KEY} --max-items 2 \
  | jq '.Versions | length')
[ "${NUM_VERSIONS}" == "1" ] || (echo "Error: Found ${NUM_VERSIONS} versions for ${BOOTSTRAPPED_PEX_URL}" && exit 1)

# Now fetch the pre-bootstrapped pex, so that the ./pants wrapper script can use it
# instead of running from sources (and re-bootstrapping).
aws --no-sign-request --region us-east-1 s3 cp ${BOOTSTRAPPED_PEX_URL} ./pants.pex
chmod 755 ./pants.pex

# Pants code executing under test expects native_engine.so to be present as a resource
# in the source tree. Normally it'll be there because we created it there during bootstrapping.
# So here we have to manually extract it there from the bootstrapped pex.
# The "|| true" is necessary because unzip returns a non-zero exit code if there were any
# bytes before the zip magic number (in our case, the pex shebang), even though the unzip
# operation otherwise succeeds.
unzip -j pants.pex pants/engine/native_engine.so -d src/python/pants/engine/ || true
