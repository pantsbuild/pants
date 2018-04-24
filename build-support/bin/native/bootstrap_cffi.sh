#!/usr/bin/env bash

set -e

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../../.. && pwd -P)

source "${REPO_ROOT}/build-support/pants_venv"

if (( $# != 1 )); then
  cat << USAGE
Usage: $0 <output dir>
USAGE
  exit 1
fi
readonly output_dir="$1"

activate_pants_venv 1>&2

PYTHONPATH="${REPO_ROOT}/src/python:${PYTHONPATH}" exec python << BOOTSTRAP_C_SOURCE
from pants.engine.native import bootstrap_c_source

bootstrap_c_source("${output_dir}")
BOOTSTRAP_C_SOURCE
