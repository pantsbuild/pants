#!/usr/bin/env bash

set -euo pipefail

BOOTSTRAPPED_PEX_BUCKET=$1
BOOTSTRAPPED_PEX_KEY=$2

# Fetch the pre-bootstrapped pex, so that the ./pants wrapper script can use it
# instead of running from sources (and re-bootstrapping).
./build-support/bin/get_aws_artifact.sh "${BOOTSTRAPPED_PEX_BUCKET}" "${BOOTSTRAPPED_PEX_KEY}" ./pants.pex

# Pants code executing under test expects native_engine.so to be present as a resource
# in the source tree. Normally it'll be there because we created it there during bootstrapping.
# So here we have to manually extract it there from the bootstrapped pex.
# The "|| true" is necessary because unzip returns a non-zero exit code if there were any
# bytes before the zip magic number (in our case, the pex shebang), even though the unzip
# operation otherwise succeeds.
unzip -j pants.pex pants/engine/native_engine.so -d src/python/pants/engine/ || true
