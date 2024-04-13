#!/bin/bash

set -xeuo pipefail

bgd server start -vvv buildgrid/data/config/default.yml &

# Allow the server to start before starting a worker.
sleep 2

buildbox-worker \
  --buildbox-run=buildbox-run-hosttools \
  --bots-remote=http://localhost:50051 \
  --cas-remote=http://localhost:50051 \
  --request-timeout=30 \
  --runner-arg=--disable-localcas my_bot
