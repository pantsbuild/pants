#!/bin/bash

PANTS_BASE=$(dirname "$0")/../..
rm -rf "${HOME}/.pex"
rm -rf "${HOME}/.cache/pants/pants_dev_deps"
rm -rf "${PANTS_BASE}/.pants.d/workdir"
find "${PANTS_BASE}" -name '*.pyc' -print0 | xargs -0 rm -f

# Legacy:
rm -rf "${PANTS_BASE}/build-support/virtualenvs"
rm -rf "${PANTS_BASE}/build-support/pants_dev_deps.venv"
rm -rf "${PANTS_BASE}/build-support/pants_dev_deps.py{2,3}.venv"
rm -rf "${PANTS_BASE}/build-support/pants_dev_deps.py{2,3}?.venv"
