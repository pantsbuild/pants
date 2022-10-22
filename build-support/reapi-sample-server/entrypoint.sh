#!/bin/bash

set -xeuo pipefail

bgd server start -vvv buildgrid/data/config/default.yml &

bgd bot -vvv --remote http://localhost:50051 --remote-cas http://localhost:50051 host-tools
