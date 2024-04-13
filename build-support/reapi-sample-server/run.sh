#!/bin/bash

set -xeuo pipefail

cd "$(git rev-parse --show-toplevel)"

if [[ -z "${NO_BUILD:-}" ]]; then
  docker build -t buildgrid_local build-support/reapi-sample-server
fi

exec docker run \
  --platform=linux/amd64 \
  -v "$HOME/.docker-run/buildgrid_local":/root \
  -p 127.0.0.1:50051:50051/tcp \
  -ti \
  --rm \
  buildgrid_local
