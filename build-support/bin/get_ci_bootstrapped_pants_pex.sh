#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && cd ../.. && pwd -P)"

AWS_BUCKET=$1
BOOTSTRAPPED_PEX_KEY=$2

BOOTSTRAPPED_PEX_URL=s3://${AWS_BUCKET}/${BOOTSTRAPPED_PEX_KEY}

# shellcheck source=build-support/common.sh
source "${REPO_ROOT}/build-support/common.sh"

# Note that in the aws cli --no-sign-request allows access to public S3 buckets without
# credentials, as long as we specify the region.

# First check that there's only one version of the object on S3, to detect malicious overwrites.
NUM_VERSIONS=$(aws --no-sign-request --region us-east-1 s3api list-object-versions \
  --bucket "${AWS_BUCKET}" --prefix "${BOOTSTRAPPED_PEX_KEY}" --max-items 2 \
  | jq '.Versions | length')
[ "${NUM_VERSIONS}" == "1" ] || die "Multiple copies of pants.pex found at" \
   "${BOOTSTRAPPED_PEX_URL}. This is not allowed as a security precaution. This likely happened" \
   "from restarting the bootstrap shards in the same Travis build. Instead, initiate a new build" \
   "by either pulling from master or pushing an empty commit (\`git commit --allow-empty\`)."


# Now fetch the pre-bootstrapped pex, so that the ./pants wrapper script can use it
# instead of running from sources (and re-bootstrapping).
aws --no-sign-request --region us-east-1 s3 cp "${BOOTSTRAPPED_PEX_URL}" ./pants.pex
chmod 755 ./pants.pex

# Pants code executing under test expects native_engine.so to be present as a resource
# in the source tree. Normally it'll be there because we created it there during bootstrapping.
# So here we have to manually extract it there from the bootstrapped pex.
# The "|| true" is necessary because unzip returns a non-zero exit code if there were any
# bytes before the zip magic number (in our case, the pex shebang), even though the unzip
# operation otherwise succeeds.
unzip -j pants.pex pants/engine/internals/native_engine.so -d src/python/pants/engine/internals || true

# TODO: As of 2019/10/24, we've seen sigbus errors while starting tests that feel potentially related
# to either the PEX or native_engine.so just having finished extraction. If we continue to see those
# issues, we can assume that this `sync` call is not necessary: otherwise, can assume that it is due
# to some behavior of either 1) the aws tool, 2) chmod, 3) zip extraction.
sync
