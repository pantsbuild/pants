#!/bin/bash

set -xeuo pipefail

bgd server start --verbose buildgrid/data/config/default.yml &

bgd bot --verbose --remote http://localhost:50051 --remote-cas http://localhost:50051 host-tools
