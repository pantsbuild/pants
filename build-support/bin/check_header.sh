#!/usr/bin/env bash

set -euo pipefail
IFS=$'\n\t'

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd ${REPO_ROOT}

build-support/bin/check_header_helper.py src tests pants-plugins examples contrib
