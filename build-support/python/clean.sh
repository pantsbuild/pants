#!/bin/bash

PANTS_BASE=$(dirname "$0")/../..
rm -rf "${HOME}/.pex"
rm -rf "${HOME}/.cache/pants/pants_dev_deps"
rm -rf "${PANTS_BASE}/.pants.d"
find "${PANTS_BASE}" -name '*.pyc' -print0 | xargs -0 rm -f
