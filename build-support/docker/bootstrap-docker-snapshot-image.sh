#!/usr/bin/env bash

set -euxo pipefail

CENTOS_SNAPSHOT_TAG='pants_centos6_snapshot'
docker build -t "$CENTOS_SNAPSHOT_TAG" ./build-support/docker/centos6
TRAVIS_SNAPSHOT_TAG='travis_ci_snapshot'
docker build -t "$TRAVIS_SNAPSHOT_TAG" \
       --build-arg BASE_IMAGE="$CENTOS_SNAPSHOT_TAG" \
       ./build-support/docker/travis_ci

docker run -i \
       -v "$(pwd):/pants-repo" -w '/pants-repo'\
       -t "$TRAVIS_SNAPSHOT_TAG" \
       /bin/bash --init-file ./build-support/docker/nicer-shell-environment.sh
