#!/usr/bin/env bash

set -euox pipefail

# Installs a `buildbox` component given its name and commit sha.
COMPONENT=$1
COMMIT_SHA=$2
TEST_BINARY="${3:-}"

git clone --filter=tree:0 "https://gitlab.com/BuildGrid/buildbox/${COMPONENT}.git" /tmp/${COMPONENT}
cd /tmp/${COMPONENT}
git checkout "${COMMIT_SHA}"
cmake -B /tmp/${COMPONENT}/build /tmp/${COMPONENT} -DBUILD_TESTING=OFF && \
make -C /tmp/${COMPONENT}/build install
make -C /tmp/${COMPONENT}/build install DESTDIR=/out 
 if [[ -n "${TEST_BINARY}" ]]; then
     sh -c "${COMPONENT} --help &> /dev/null"
 fi
